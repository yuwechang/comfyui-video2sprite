"""Local novelty sampling, subtle lead-in performance and source-proportional timing."""
import math
from PIL import ImageChops, ImageStat
from source_clock import (FrameClock, QUANTUM_MS, allocate_ticks, phase_budget,
                          representative_x, total_ticks, y_weights)

PROFILES = {'compact': .75, 'balanced': .60, 'smooth': .45}


class AdaptiveScorer:
    """Split intervals only when an interior pose differs enough from both ends."""
    def __init__(self, images, noise_floor=4):
        if len(images) < 2 or any(im.mode not in ('L','RGB') or im.mode != images[0].mode or im.size != images[0].size for im in images):
            raise ValueError('Need at least two same-size, same-mode L or RGB analysis images')
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
            difference=ImageChops.difference(self.images[a],self.images[b])
            energy=max(self.energy[a],self.energy[b],1)
            global_score=sum(ImageStat.Stat(difference).sum)/energy
            self.cache[key] = global_score
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

    def select(self, threshold, count=None, anchors=()):
        if not math.isfinite(threshold) or threshold < 0:
            raise ValueError('Threshold must be finite and nonnegative')
        if count is not None and (type(count) is not int or not 2 <= count <= len(self.images)):
            raise ValueError('Sampling interval must contain at least count frames')
        last = len(self.images) - 1
        selected={0,last}
        for i in anchors:
            if not 0<=i<=last:raise ValueError('Anchor outside interval')
            if count is None or len(selected)<count:selected.add(i)
        ordered=sorted(selected)
        spans={(a,b):self.candidate(a,b) for a,b in zip(ordered,ordered[1:])}
        trace=[]
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


class LeadScorer(AdaptiveScorer):
    """X-only sensitivity to small local lead-in performances."""
    def __init__(self,images):
        super().__init__(images)
        width,height=images[0].size
        self.regions=[(x*width//4,y*height//4,(x+1)*width//4,(y+1)*height//4)
                      for y in range(4) for x in range(4)]
        self.local_energy=[[sum(ImageStat.Stat(im.crop(box)).sum) for box in self.regions]
                           for im in self.images]
        self.local_cache={}

    def distance(self,a,b):
        key=(min(a,b),max(a,b))
        if key not in self.local_cache:
            difference=ImageChops.difference(self.images[a],self.images[b])
            energy=max(self.energy[a],self.energy[b],1)
            local=max(sum(ImageStat.Stat(difference.crop(box)).sum)/
                max(self.local_energy[a][i],self.local_energy[b][i],energy/len(self.regions),1)
                for i,box in enumerate(self.regions))
            self.local_cache[key]=max(super().distance(a,b),local)
        return self.local_cache[key]


class CurveScorer(AdaptiveScorer):
    """Source-feature reconstruction error, without generating delivery frames."""
    def __init__(self,images,method,times):
        super().__init__(images)
        import numpy as np
        if method not in ('linear','cubic'):raise ValueError('Unknown curve method')
        self.np=np;self.method=method
        self.interval_errors={}
        self.times=np.asarray(times,dtype=float)
        if len(times)!=len(images) or np.any(np.diff(self.times)<=0):
            raise ValueError('Curve fitting requires increasing source timestamps')
        self.values=np.asarray([np.asarray(im,dtype=float) for im in self.images])
        if self.values.ndim==3:self.values=self.values[...,None]

    def tangent(self,index):
        a=max(0,index-1);b=min(len(self.images)-1,index+1)
        return (self.values[b]-self.values[a])/(self.times[b]-self.times[a])

    def select(self,threshold,count=None,anchors=()):
        result=super().select(threshold,count,anchors)
        result['pruning']={'removed':[],'initial_count':result['count']}
        if count is not None:return result
        selected=result['indices'];protected={0,len(self.images)-1,*anchors}
        while True:
            choices=[]
            for position,index in enumerate(selected[1:-1],1):
                if index in protected:continue
                candidate=self.candidate(selected[position-1],selected[position+1])
                error=candidate[0][0] if candidate else 0
                if error<=threshold:choices.append((error,index,position))
            if not choices:break
            error,index,position=min(choices)
            selected.pop(position)
            result['pruning']['removed'].append({'frame':index,'merged_error':error})
        result['count']=len(selected)
        result['max_remaining_score']=max((self.candidate(a,b)[0][0] for a,b in zip(selected,selected[1:]) if b>a+1),default=0)
        result['pruning']['stop_reason']='no_removable_frame_within_tolerance'
        result['error_model']='max_curve_and_ordered_hold'
        result['interval_errors']=[dict(left=a,right=b,**self.interval_errors[a,b])
                                  for a,b in zip(selected,selected[1:]) if b>a+1]
        return result

    def candidate(self,a,b):
        if b<=a+1:return None
        np=self.np;span=self.times[b]-self.times[a];best=None
        # Match the ordered source-time assignment used by the displayed sprites.
        weights=[self.times[k+1]-self.times[k] for k in range(a,b)]
        left=[self.distance(a,k)*weights[k-a] for k in range(a,b)]
        right=[self.distance(k,b)*weights[k-a] for k in range(a,b)]
        cost=sum(right);splits=[]
        for cut in range(a+1,b+1):
            cost+=left[cut-a-1]-right[cut-a-1]
            splits.append((round(float(cost),12),abs(cut-(a+b+1)/2),cut))
        cut=min(splits)[2];curve_max=hold_max=0
        for i in range(a+1,b):
            t=(self.times[i]-self.times[a])/span
            if self.method=='linear':predicted=(1-t)*self.values[a]+t*self.values[b]
            else:
                predicted=((2*t**3-3*t**2+1)*self.values[a]+(t**3-2*t**2+t)*span*self.tangent(a)
                           +(-2*t**3+3*t**2)*self.values[b]+(t**3-t**2)*span*self.tangent(b))
            predicted=np.clip(predicted,0,255)
            actual=self.values[i];delta=np.abs(actual-predicted)
            energy=max(actual.sum(),predicted.sum(),1)
            score=delta.sum()/energy
            hold=self.distance(a,i) if i<cut else self.distance(i,b)
            curve_max=max(curve_max,float(score));hold_max=max(hold_max,hold)
            score=max(score,hold)
            key=(round(float(score),6),self.distance(i-1,i),-abs(t-.5),-i)
            if best is None or key>best[0]:best=(key,i)
        self.interval_errors[a,b]={'curve_error':round(curve_max,6),'hold_error':round(hold_max,6),'source_cut':cut}
        return best


def extent_anchors(images):
    """Preserve pronounced silhouette excursions beyond both endpoint silhouettes."""
    boxes=[im.point(lambda v:255 if v>16 else 0).getbbox() for im in images]
    if not boxes[0] or not boxes[-1]:return []
    candidates=[]
    for axis in range(4):
        sign=-1 if axis<2 else 1
        baseline=max(sign*boxes[0][axis],sign*boxes[-1][axis])
        scored=[(sign*b[axis]-baseline,i) for i,b in enumerate(boxes) if b]
        value=max(v for v,i in scored)
        dimension=images[0].size[axis%2]
        if value<max(2,dimension*.10):continue
        tied=[i for v,i in scored if v==value]
        candidates.append((value/dimension,tied[len(tied)//2]))
    return list(dict.fromkeys(i for _,i in sorted(candidates,reverse=True)))


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


def pose_timing(images, indices, clock, start, end):
    """Assign source time to adjacent representatives by ordered visual fit.

    Each boundary stays between its two selected source frames. A sustained pose
    therefore contributes time to its representative instead of a distant temporal
    midpoint assigning that hold to an unrelated transition pose.
    """
    y_weights(clock,indices,start,end)  # Validate source bounds and ordered endpoints.
    if len(images)!=end-start+1:raise ValueError('Timing needs every source analysis frame')
    scorer=AdaptiveScorer(images)
    cuts=[]
    for left,right in zip(indices,indices[1:]):
        a,b=left-start,right-start
        durations=[float(clock.boundary(i+1)-clock.boundary(i)) for i in range(left,right+1)]
        to_left=[scorer.distance(a,i)*w for i,w in zip(range(a,b+1),durations)]
        to_right=[scorer.distance(i,b)*w for i,w in zip(range(a,b+1),durations)]
        cost=sum(to_right);candidates=[]
        for split in range(a+1,b+1):
            offset=split-a-1
            cost+=to_left[offset]-to_right[offset]
            candidates.append((round(cost,12),abs(split-(a+b+1)/2),split))
        cuts.append(start+min(candidates)[2])
    edges=[start]+cuts+[end+1]
    weights=[clock.boundary(b)-clock.boundary(a) for a,b in zip(edges,edges[1:])]
    return weights,{'method':'ordered_pose_similarity','source_bins':[[a,b] for a,b in zip(edges,edges[1:])]}


def lead_samples(images, clock, a, b, ticks, refresh_ms, key_images=None):
    """Keep small changes in X, adding salient poses inside existing time bins."""
    minimum, maximum = images[0].copy(), images[0].copy()
    for im in images[1:]:
        minimum, maximum = ImageChops.darker(minimum, im), ImageChops.lighter(maximum, im)
    delta=ImageChops.difference(minimum,maximum)
    extrema=delta.getextrema()
    static=(max(high for low,high in extrema) if delta.mode=='RGB' else extrema[1])<=4
    key_images = images if key_images is None else key_images
    keys = ([a + i for i in LeadScorer(key_images).select(PROFILES['compact'])['indices']]
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


def fixed_playback(images, indices, clock, start, end, seconds, fps, timing):
    """Allocate fixed-rate slots, adding distinct source poses within each time bin."""
    if type(fps) is not int or fps <= 0 or 1000 % (fps * QUANTUM_MS):
        raise ValueError('Playback FPS must produce a whole number of 20 ms ticks per frame')
    beat = 1000 // fps
    slot_count = max(len(indices), round(seconds * fps))
    weights, assignment = pose_timing(images, indices, clock, start, end)
    slots = allocate_ticks(weights, slot_count)
    motion = AdaptiveScorer(images)
    frames, durations, sequence = [], [], []
    for representative, budget, (left, right) in zip(indices, slots, assignment['source_bins']):
        chosen = [representative]
        while len(chosen) < budget:
            score, index = max(
                ((min(motion.distance(i-start, kept-start) for kept in chosen), i)
                 for i in range(left, right) if i not in chosen),
                default=(0, representative))
            if score <= .18:
                break
            chosen.append(index)
        chosen.sort()
        boundaries = [clock.boundary(left)] + [
            (clock.center(a) + clock.center(b)) / 2 for a,b in zip(chosen, chosen[1:])
        ] + [clock.boundary(right)]
        counts = allocate_ticks([b-a for a,b in zip(boundaries,boundaries[1:])], budget)
        for index, repeats in zip(chosen, counts):
            sequence.extend([len(frames)] * repeats)
            frames.append(index)
            durations.append(repeats * beat)
    timing.update(frame_durations_ms=durations,
                  playback={'fps':fps, 'sequence':sequence, 'primary_source_indices':indices},
                  timing_assignment=assignment)
    return frames, slot_count / fps


def sample_video(video, start, end, count=None, motion_type=None, loop=False,
                 seconds=None, quality='compact', lead_start=None, lead_refresh_ms=160,foreground=None,
                 sampling_method='novelty', playback_fps=None):
    """Explicit A=lead_start, B=start, D=end; only hold_end_pose may have X."""
    from spritesheet import sample_indices
    if quality not in PROFILES:
        raise ValueError('Unknown sampling quality')
    if sampling_method not in ('novelty','linear','cubic'):raise ValueError('Unknown sampling method')
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
    images, _ = features(video, start, end, full_rate=True,
                         subject_only=motion_type=='return_to_start',foreground=foreground)
    anchors=extent_anchors(images) if motion_type=='return_to_start' and sampling_method=='novelty' else []
    clock = FrameClock.read(video)
    scorer=(AdaptiveScorer(images) if sampling_method=='novelty' else
            CurveScorer(images,sampling_method,[float(clock.boundary(i)) for i in range(start,end+1)]))
    selection = scorer.select(PROFILES[quality], count, anchors)
    selection['method']=sampling_method
    selection['extent_anchors']=anchors
    y = [start + i for i in selection['indices']]
    clock = FrameClock.read(video)
    a = start if lead_start is None else lead_start
    fixed = playback_fps is not None and motion_type == 'return_to_start'
    budget = phase_budget(clock, a, start, end,
                          max(seconds, len(y) * QUANTUM_MS / 1000) if fixed else seconds)
    weights,timing_assignment=pose_timing(images,y,clock,start,end)
    yticks = allocate_ticks(weights, budget['y_ticks'])
    x = dict(indices=[], ticks=[])
    if a < start:
        # Decode only the selected X interval as numeric features, never image-edit all source frames.
        xi, _ = features(video, a, start, full_rate=True,foreground=foreground)
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
                  timing_assignment=timing_assignment,
                  lead_review_required=motion_type == 'hold_end_pose' and lead_start is None)
    if fixed:
        indices, _ = fixed_playback(images, indices, clock, start, end, seconds, playback_fps, report)
    return indices, report
