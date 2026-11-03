"""Select return-to-start poses by visual reconstruction error, preserving source time."""
import math
from PIL import Image, ImageChops, ImageStat


def adaptive_indices(images, count):
    """Greedily split the least represented interval; endpoints are always retained.

    Pixel interpolation is only an error probe. No interpolated image is delivered.
    A held pose needs its entry/exit, rather than many copies of the same pose.
    """
    if type(count) is not int or not 2 <= count <= len(images):
        raise ValueError('Sampling interval must contain at least count frames')
    if any(im.size != images[0].size or im.mode != images[0].mode for im in images):
        raise ValueError('Analysis images must share dimensions and mode')
    energies = [sum(ImageStat.Stat(im).sum) for im in images]
    steps = [sum(ImageStat.Stat(ImageChops.difference(a, b)).sum)/max(ea, eb, 1)
             for a, b, ea, eb in zip(images, images[1:], energies, energies[1:])]

    def candidate(a, b):
        best = None
        for i in range(a+1, b):
            estimate = Image.blend(images[a], images[b], (i-a)/(b-a))
            error = sum(ImageStat.Stat(ImageChops.difference(images[i], estimate)).sum)
            error /= max(energies[i], energies[a], energies[b], 1)
            # Equal-error held poses prefer their transition boundaries, not plateau copies.
            activity = max(steps[i-1], steps[i] if i < len(steps) else 0)
            key = (round(error, 6), activity, -abs(i-(a+b)/2), -i)
            if best is None or key > best[0]:
                best = (key, i)
        return best

    intervals = {(0, len(images)-1): candidate(0, len(images)-1)}
    selected = {0, len(images)-1}
    while len(selected) < count:
        (a, b), best = max(((span, value) for span, value in intervals.items() if value is not None),
                           key=lambda item: item[1][0])
        i = best[1]
        selected.add(i)
        del intervals[a, b]
        intervals[a, i] = candidate(a, i)
        intervals[i, b] = candidate(i, b)
    residual = max((value[0][0] for value in intervals.values() if value is not None), default=0)
    return sorted(selected), round(residual, 6)


def source_weights(indices, start, end):
    """Each source frame belongs to its nearest selected sample in time."""
    if indices != sorted(set(indices)) or len(indices) < 2 or indices[0] != start or indices[-1] != end:
        raise ValueError('Timing samples must be ordered unique indices including both endpoints')
    edges = [start-.5] + [(a+b)/2 for a, b in zip(indices, indices[1:])] + [end+.5]
    return [b-a for a, b in zip(edges, edges[1:])]


def sample_video(video, start, end, count, motion_type=None, loop=False):
    """The same selection policy serves ground and air before any selected-frame edits."""
    from spritesheet import sample_indices
    uniform = sample_indices(start, end, count, loop)
    if motion_type != 'return_to_start':
        return uniform, {'strategy': 'uniform'}
    from select_segment import features
    images, _ = features(video, start, end, full_rate=True)
    local, residual = adaptive_indices(images, count)
    indices = [start+i for i in local]
    return indices, {'strategy': 'visual_reconstruction',
                     'analysis_frames': len(images), 'analysis_size': list(images[0].size),
                     'max_reconstruction_error': residual,
                     'timing_weights': source_weights(indices, start, end),
                     'review_required': True}


def weighted_timings(seconds, weights):
    """Scale relative source coverage to the requested duration on a 10 ms GIF grid."""
    if not math.isfinite(seconds) or seconds <= 0 or not weights or any(
            not math.isfinite(w) or w <= 0 for w in weights):
        raise ValueError('Duration and timing weights must be finite and positive')
    total = round(seconds*100)
    if total < len(weights):
        raise ValueError('GIF timing requires at least 10 ms per frame')
    edges = [0]
    cumulative = 0
    whole = sum(weights)
    for i, weight in enumerate(weights[:-1]):
        cumulative += weight
        edges.append(max(edges[-1]+1, min(total-(len(weights)-i-1), round(cumulative/whole*total))))
    edges.append(total)
    return [(b-a)*10 for a, b in zip(edges, edges[1:])]
