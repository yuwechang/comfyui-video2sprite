"""Source presentation times and bounded playback budgets (20 ms preview grid)."""
from fractions import Fraction
import bisect
import json
import math
import subprocess

QUANTUM_MS = 20


def total_ticks(seconds):
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('Duration must be finite and positive')
    ticks = int(Fraction(str(seconds)) * 1000 // QUANTUM_MS)
    if ticks < 1:
        raise ValueError('Duration below 20 ms preview resolution')
    return ticks


class FrameClock:
    def __init__(self, timestamps, end_time):
        self.pts = [Fraction(str(t)) for t in timestamps]
        self.end = Fraction(str(end_time))
        if (not self.pts or any(b <= a for a, b in zip(self.pts, self.pts[1:]))
                or self.end <= self.pts[-1]):
            raise ValueError('Invalid presentation timestamps')

    def boundary(self, index):
        if type(index) is not int or not 0 <= index <= len(self.pts):
            raise ValueError('Frame boundary outside source')
        return self.end if index == len(self.pts) else self.pts[index]

    def center(self, index):
        return (self.boundary(index) + self.boundary(index + 1)) / 2

    @classmethod
    def read(cls, video):
        data = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
            'frame=best_effort_timestamp_time,duration_time,pkt_duration_time:'
            'stream=avg_frame_rate,duration:format=duration', '-of', 'json', str(video)]))
        frames = data.get('frames', [])
        if not frames or any('best_effort_timestamp_time' not in f for f in frames):
            raise ValueError('Source has no usable presentation timestamps')
        pts = [Fraction(f['best_effort_timestamp_time']) for f in frames]
        duration = frames[-1].get('duration_time', frames[-1].get('pkt_duration_time'))
        if duration and Fraction(duration) > 0:
            end = pts[-1] + Fraction(duration)
        else:
            stream = data['streams'][0]
            # Stream duration is relative to its start, not necessarily timestamp zero.
            duration = stream.get('duration')
            if duration and duration != 'N/A':
                end = pts[0] + Fraction(duration)
            elif len(pts) > 1:
                end = pts[-1] + (pts[-1] - pts[-2])
            else:
                rate = Fraction(stream['avg_frame_rate'])
                if rate <= 0:
                    raise ValueError('Cannot determine final source frame duration')
                end = pts[-1] + 1 / rate
            if end <= pts[-1]:
                raise ValueError('Final source duration is inconsistent with timestamps')
        return cls(pts, end)


def allocate_ticks(weights, ticks):
    if not weights or any(not math.isfinite(w) or w <= 0 for w in weights):
        raise ValueError('Timing weights must be finite and positive')
    if ticks < len(weights):
        raise ValueError('Too many images for phase time budget; use fewer samples or a longer duration')
    weights = [Fraction(w) for w in weights]
    total, cumulative, edges = sum(weights), 0, [0]
    for i, weight in enumerate(weights[:-1]):
        cumulative += weight
        ideal = round(cumulative / total * ticks)
        edges.append(max(edges[-1] + 1, min(ticks - (len(weights) - i - 1), ideal)))
    edges.append(ticks)
    return [b - a for a, b in zip(edges, edges[1:])]


def y_weights(clock, indices, start, end):
    if (not indices or indices != sorted(set(indices)) or indices[0] != start
            or indices[-1] != end or not 0 <= start <= end < len(clock.pts)):
        raise ValueError('Timing indices must include ordered endpoints within source')
    edges = ([clock.boundary(start)]
             + [(clock.center(a) + clock.center(b)) / 2 for a, b in zip(indices, indices[1:])]
             + [clock.boundary(end + 1)])
    return [b - a for a, b in zip(edges, edges[1:])]


def phase_budget(clock, a, b, d, target_seconds):
    if not 0 <= a <= b <= d < len(clock.pts):
        raise ValueError('Need A <= B <= D within source')
    ticks = total_ticks(target_seconds)
    tx = clock.boundary(b) - clock.boundary(a)
    ty = clock.boundary(d + 1) - clock.boundary(b)
    x_ticks = int(ticks * tx / (tx + ty))
    y_ticks = ticks - x_ticks
    if tx > 0 and x_ticks == 0 or y_ticks == 0:
        raise ValueError('Phase budget below 20 ms preview resolution')
    return dict(x_ticks=x_ticks, y_ticks=y_ticks, quantum_ms=QUANTUM_MS,
                actual_total_ms=ticks * QUANTUM_MS,
                source_x_seconds=float(tx), source_y_seconds=float(ty),
                source_total_seconds=float(tx + ty),
                scale=float(Fraction(ticks * QUANTUM_MS, 1000) / (tx + ty)),
                ideal_x_ms=float(ticks * QUANTUM_MS * tx / (tx + ty)),
                x_ms=x_ticks * QUANTUM_MS, y_ms=y_ticks * QUANTUM_MS)


def representative_x(clock, a, b, ticks, refresh_ms=160, static=False):
    """Time bins for subtle performance; extra images cannot increase its duration."""
    if ticks == 0:
        return dict(indices=[], ticks=[], source_bins=[])
    if not a < b or not math.isfinite(refresh_ms) or refresh_ms <= 0:
        raise ValueError('Need a nonempty X range and positive refresh interval')
    count = 1 if static else min(b - a, ticks, max(1, math.ceil(ticks * QUANTUM_MS / refresh_ms)))
    durations = allocate_ticks([1] * count, ticks)
    start, span = clock.boundary(a), clock.boundary(b) - clock.boundary(a)
    elapsed, indices, weights, bins = 0, [], [], []
    for k, duration in enumerate(durations):
        left = start + span * Fraction(elapsed, ticks)
        right = start + span * Fraction(elapsed + duration, ticks)
        index = max(a, min(b - 1, bisect.bisect_right(clock.pts, (left + right) / 2) - 1))
        if k == 0 and count > 1:
            index = a
        if indices and indices[-1] == index:
            weights[-1] += duration
            bins[-1][1] = right
        else:
            indices.append(index)
            weights.append(duration)
            bins.append([left, right])
        elapsed += duration
    return dict(indices=indices, ticks=weights, source_bins=bins)
