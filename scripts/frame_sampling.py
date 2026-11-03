"""Local novelty sampling, subtle lead-in performance and source-proportional timing."""
import math
from PIL import ImageChops, ImageStat
from source_clock import (FrameClock, QUANTUM_MS, allocate_ticks, phase_budget,
                          representative_x, total_ticks, y_weights)

PROFILES = {'compact': .75, 'balanced': .60, 'smooth': .45}


class AdaptiveScorer:
    """Split intervals only when an interior pose differs enough from both ends."""
    def __init__(self, images, noise_floor=4):
        if len(images) < 2 or any(im.mode != 'L' or im.size != images[0].size for im in images):
            raise ValueError('Need at least two same-size grayscale analysis images')
        if not 0 <= noise_floor < 255:
            raise ValueError('Invalid noise floor')
        baseline = images[0].copy()
        for image in images[1:]:
            baseline = ImageChops.darker(baseline, image)
        self.images = [ImageChops.subtract(im, baseline).point(
            lambda v: 0 if v <= noise_floor else v) for im in images]
        self.energy = [sum(ImageStat.Stat(im).sum) for im in self.images]
        self.cache = {}

    def distance(self, a, b):
        key = (min(a, b), max(a, b))
        if key not in self.cache:
            delta = sum(ImageStat.Stat(ImageChops.difference(self.images[a], self.images[b])).sum)
            self.cache[key] = delta / max(self.energy[a], self.energy[b], 1)
        return self.cache[key]

    def candidate(self, a, b):
        best = None
        for i in range(a + 1, b):
            score = round(min(self.distance(a, i), self.distance(i, b)), 6)
            activity = max(self.distance(i - 1, i),
                           self.distance(i, i + 1) if i + 1 < len(self.images) else 0)
            key = (score, activity, -abs(i - (a + b) / 2), -i)
            if best is None or key > best[0]:
                best = (key, i)
        return best

    def select(self, threshold, count=None):
        if not math.isfinite(threshold) or threshold < 0:
            raise ValueError('Threshold must be finite and nonnegative')
        if count is not None and (type(count) is not int or not 2 <= count <= len(self.images)):
            raise ValueError('Sampling interval must contain at least count frames')
        last = len(self.images) - 1
        selected, spans, trace = {0, last}, {(0, last): self.candidate(0, last)}, []
        while True:
            available = [(span, candidate) for span, candidate in spans.items() if candidate]
            residual = max((c[0][0] for _, c in available), default=0)
            if not available:
                reason = 'source_exhausted'
                break
            if count is not None and len(selected) >= count:
                reason = 'explicit_count'
                break
            if count is None and residual <= threshold:
                reason = 'all_local_scores_within_tolerance'
                break
            (a, b), best = max(available, key=lambda item: item[1][0])
            i = best[1]
            selected.add(i)
            trace.append(dict(frame=i, left=a, right=b, score=best[0][0]))
            del spans[a, b]
            spans[a, i], spans[i, b] = self.candidate(a, i), self.candidate(i, b)
        return dict(indices=sorted(selected), count=len(selected), threshold=threshold,
                    max_remaining_score=residual, stop_reason=reason, insertions=trace)


def adaptive_indices(images, count=None, quality='compact'):
    result = AdaptiveScorer(images).select(PROFILES[quality], count)
    return result['indices'], result['max_remaining_score']


def source_weights(indices, start, end):
    """CFR index coverage for explicit callers; video sampling uses actual PTS."""
    if len(indices) < 2 or indices != sorted(set(indices)) or indices[0] != start or indices[-1] != end:
        raise ValueError('Timing samples must include ordered endpoints')
    edges = [start - .5] + [(a + b) / 2 for a, b in zip(indices, indices[1:])] + [end + .5]
    return [b - a for a, b in zip(edges, edges[1:])]


def weighted_timings(seconds, weights):
    return [n * QUANTUM_MS for n in allocate_ticks(weights, total_ticks(seconds))]


def lead_samples(images, clock, a, b, ticks, refresh_ms, key_images=None):
    """Keep small changes in X, adding salient poses inside existing time bins."""
    minimum, maximum = images[0].copy(), images[0].copy()
    for im in images[1:]:
        minimum, maximum = ImageChops.darker(minimum, im), ImageChops.lighter(maximum, im)
    static = ImageChops.difference(minimum, maximum).getextrema()[1] <= 4
    key_images = images if key_images is None else key_images
    keys = ([a + i for i in AdaptiveScorer(key_images).select(PROFILES['compact'])['indices']]
            if len(key_images) > 1 else [a])
    base = representative_x(clock, a, b, ticks, refresh_ms, static)
    if len(base['indices']) == 1:
        return dict(indices=base['indices'], ticks=base['ticks'], static=static, refresh_ms=refresh_ms)
    indices, durations = [], []
    for rep, budget, (left, right) in zip(base['indices'], base['ticks'], base['source_bins']):
        chosen = sorted({rep} | {i for i in keys if a <= i < b and left <= clock.center(i) < right})
        if len(chosen) > budget or static:
            chosen = [rep]
        edges = [left] + [(clock.center(i) + clock.center(j)) / 2
                          for i, j in zip(chosen, chosen[1:])] + [right]
        for i, duration in zip(chosen, allocate_ticks([r-l for l, r in zip(edges, edges[1:])], budget)):
            if indices and indices[-1] == i:
                durations[-1] += duration
            else:
                indices.append(i)
                durations.append(duration)
    return dict(indices=indices, ticks=durations, static=static, refresh_ms=refresh_ms)


def sample_video(video, start, end, count=None, motion_type=None, loop=False,
                 seconds=None, quality='compact', lead_start=None, lead_refresh_ms=160):
    """Explicit A=lead_start, B=start, D=end; only hold_end_pose may have X."""
    from spritesheet import sample_indices
    if quality not in PROFILES:
        raise ValueError('Unknown sampling quality')
    if motion_type not in (None, 'loop', 'return_to_start', 'hold_end_pose'):
        raise ValueError('Unknown motion type')
    if lead_start is not None and (motion_type != 'hold_end_pose' or not 0 <= lead_start <= start):
        raise ValueError('lead_start requires hold_end_pose and 0 <= A <= B')
    if motion_type not in ('return_to_start', 'hold_end_pose'):
        count = min(8, end-start+1) if count is None else count
        return sample_indices(start, end, count, loop), {'strategy': 'uniform'}
    if seconds is None:
        raise ValueError('Adaptive sampling requires playback seconds')
    from select_segment import features
    images, _ = features(video, start, end, full_rate=True)
    selection = AdaptiveScorer(images).select(PROFILES[quality], count)
    y = [start + i for i in selection['indices']]
    clock = FrameClock.read(video)
    a = start if lead_start is None else lead_start
    budget = phase_budget(clock, a, start, end, seconds)
    yticks = allocate_ticks(y_weights(clock, y, start, end), budget['y_ticks'])
    x = dict(indices=[], ticks=[])
    if a < start:
        # Decode only the selected X interval as numeric features, never image-edit all source frames.
        xi, _ = features(video, a, start, full_rate=True)
        x = lead_samples(xi[:-1], clock, a, start, budget['x_ticks'], lead_refresh_ms, key_images=xi)
    indices = x['indices'] + y
    durations = [t * QUANTUM_MS for t in x['ticks'] + yticks]
    if indices != sorted(set(indices)) or sum(durations) != budget['actual_total_ms']:
        raise ValueError('Invalid segmented sampling timeline')
    report = dict(strategy='segmented_novelty' if a < start else 'local_novelty',
                  quality=quality, analysis_frames=len(images), analysis_size=list(images[0].size),
                  selection=selection, phases=dict(a=a, b=start, d=end, x=x, y=dict(indices=y, ticks=yticks)),
                  source_timestamps_seconds=[float(clock.boundary(i)) for i in indices],
                  budget=budget, frame_durations_ms=durations, review_required=True,
                  lead_review_required=motion_type == 'hold_end_pose' and lead_start is None)
    return indices, report
