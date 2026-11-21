"""Opt-in rhythm/transition experiment; accepted major indices remain immutable."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from benchmark_pose_methods import JOINTS,pose_distance
from source_clock import FrameClock,allocate_ticks,total_ticks,QUANTUM_MS
from pose_reliability import (input_quality,confidence_weights,weighted_smooth,
                              EvidenceMetric,POLICY)


def refine(poses,times,major,durations,reliability=None,appearance=None):
    if len(times)!=len(poses) or len(durations)!=len(poses) or not np.isfinite(poses).all():
        raise ValueError('Incomplete or nonfinite pose/timing sequence')
    if major!=sorted(set(major)) or major[0]!=0 or major[-1]!=len(poses)-1:
        raise ValueError('Major poses must include ordered source endpoints')
    if any(b<=a for a,b in zip(times,times[1:])) or any(d<=0 for d in durations):
        raise ValueError('Invalid source timing')
    n=len(poses);weights=np.asarray(durations,float)
    metric=EvidenceMetric(poses,reliability,appearance) if reliability is not None else None
    distances=(np.asarray([pose_distance(poses,p) for p in poses]) if metric is None else metric.pairs())**2
    cache={}
    def span(a,b):
        if (a,b) not in cache:
            choices=[]
            for cut in range(a+1,b+1):
                cost=float(np.sum(distances[a,a:cut]*weights[a:cut])+
                           np.sum(distances[b,cut:b+1]*weights[cut:b+1]))
                choices.append((cost,abs(times[cut]-(times[a]+times[b])/2),cut))
            cost,_,cut=min(choices);cache[a,b]=(cost,cut)
        return cache[a,b]
    def total(indices):return sum(span(a,b)[0] for a,b in zip(indices,indices[1:]))
    selected=major.copy();states=[{'indices':selected.copy(),'error':total(selected)}]
    insertions=[]
    while len(selected)<n:
        candidates=[]
        for a,b in zip(selected,selected[1:]):
            before=span(a,b)[0]
            for i in range(a+1,b):
                gain=before-span(a,i)[0]-span(i,b)[0]
                candidates.append((gain,-abs(times[i]-(times[a]+times[b])/2),-i,i,a,b))
        if not candidates:break
        gain,_,_,i,a,b=max(candidates)
        if gain<=1e-14:break
        selected=sorted(selected+[i]);insertions.append({'frame':i,'interval':[a,b],'gain':gain})
        states.append({'indices':selected.copy(),'error':total(selected)})
    initial=states[0]['error']
    for state in states:
        complexity=(len(state['indices'])-len(major))/max(n-len(major),1)
        state['knee_score']=(1-state['error']/initial if initial>1e-14 else 0)-complexity
    chosen=max(states,key=lambda state:(state['knee_score'],-len(state['indices'])))
    selected=chosen['indices'];cuts=[span(a,b)[1] for a,b in zip(selected,selected[1:])]
    edges=[0]+cuts+[n]
    source_weights=[float(weights[a:b].sum()) for a,b in zip(edges,edges[1:])]
    major_edges=[0]+[span(a,b)[1] for a,b in zip(major,major[1:])]+[n]
    major_weights=[float(weights[a:b].sum()) for a,b in zip(major_edges,major_edges[1:])]
    speed=(pose_distance(poses[1:],poses[:-1]) if metric is None else
        np.asarray([metric.interpolation(i,i,i+1,0.) for i in range(n-1)]))/np.diff(times)
    return {'major_indices':major,'indices':selected,'added_indices':[i for i in selected if i not in major],
        'source_weights':source_weights,'source_bins':list(map(list,zip(edges,edges[1:]))),
        'major_source_weights':major_weights,
        'states':states,'insertions':insertions,'error_model':('source-duration-weighted squared visible-pose and masked-appearance hold error'
            if appearance is not None else 'source-duration-weighted squared pose hold error'),
        'stopping_rule':'maximum normalized error reduction minus added-frame fraction; no target count',
        'speed':speed.tolist(),'initial_error':initial,'selected_error':chosen['error']}


def selection_parameters(indices,durations,seconds,motion_type,start,end):
    parameters={'indices':indices,'frame_durations_ms':durations,'seconds':seconds,'motion_type':motion_type}
    if motion_type=='hold_end_pose':
        # This research input is already a complete supplied interval. All of it
        # is Y; do not invent a separate X phase or silently label it a return.
        if indices[0]!=start or indices[-1]!=end:raise ValueError('Research endpoints changed')
        parameters.update(lead_start=start,start=start,end=end)
    return parameters


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('landmarks','benchmark','video','output'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--seconds',type=float,required=True)
    parser.add_argument('--motion-type',choices=('return_to_start','hold_end_pose'),default='return_to_start')
    args=parser.parse_args();folder=Path(args.output).resolve()
    if folder.exists():raise ValueError('Use a new research output directory')
    data=json.loads(Path(args.landmarks).read_text());benchmark=json.loads(Path(args.benchmark).read_text())
    if data['signature']['video_sha256']!=hashlib.sha256(Path(args.video).read_bytes()).hexdigest():
        raise ValueError('Pose cache video changed')
    if data['signature']!=benchmark['source_signature']:raise ValueError('Benchmark and landmark inputs differ')
    start=data['signature']['start'];end=data['signature']['end']
    positions=np.asarray(data['positions']);visibility=np.asarray(data['visibility'])
    appearance=None
    if benchmark.get('appearance_contract'):
        from pose_appearance import load
        appearance=load(benchmark['appearance_contract'],args.video,start,end)
    quality=input_quality(positions,visibility,start,end,appearance)
    if not quality['passed']:
        folder.mkdir(parents=True)
        report={'status':'input_rejected','quality':quality,'source_signature':data['signature'],
                'request_generated':False,'manual_substitution':False}
        (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({'status':'input_rejected','report':str(folder/'report.json'),
            'reason':quality['reason'],'affected_frames':len(quality.get('affected_frames',[]))}))
        return
    if benchmark.get('reliability_policy')!=POLICY:
        raise ValueError('Recompute benchmark with the same confidence-aware policy before transitions')
    scale=benchmark['common_scale']
    if not np.isfinite(scale) or scale<=0:raise ValueError('Invalid common pose scale')
    reliability=confidence_weights(visibility)
    poses=weighted_smooth(positions/scale,reliability)
    major=[i-start for i in benchmark['methods']['recursive_automatic_knee']['source_indices']]
    clock=FrameClock.read(args.video)
    times=[float(clock.boundary(i)) for i in range(start,end+1)]
    durations=[float(clock.boundary(i+1)-clock.boundary(i)) for i in range(start,end+1)]
    result=refine(poses,times,major,durations,reliability,appearance)
    frame_durations=[tick*QUANTUM_MS for tick in allocate_ticks(result['source_weights'],total_ticks(args.seconds))]
    indices=[start+i for i in result['indices']]
    result.update(source_indices=indices,source_major_indices=[start+i for i in major],
        source_added_indices=[start+i for i in result['added_indices']],frame_durations_ms=frame_durations,
        source_signature=data['signature'],research_only=True,quality=quality,
        reliability_policy=POLICY,appearance_contract=benchmark.get('appearance_contract'),manual_substitution=False,
        motion_type=args.motion_type,input_scope='complete supplied interval; no separate X phase')
    request={'tasks':{'provided-animation':{'selection':{'parameters':selection_parameters(
        indices,frame_durations,args.seconds,args.motion_type,start,end)}}}}
    folder.mkdir(parents=True);(folder/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    (folder/'request.json').write_text(json.dumps(request,indent=2),encoding='utf-8')
    major_durations=[tick*QUANTUM_MS for tick in allocate_ticks(result['major_source_weights'],total_ticks(args.seconds))]
    baseline={'tasks':{'provided-animation':{'selection':{'parameters':selection_parameters(
        result['source_major_indices'],major_durations,args.seconds,args.motion_type,start,end)}}}}
    (folder/'major-timing-request.json').write_text(json.dumps(baseline,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(folder/'report.json'),'major':result['source_major_indices'],
        'added':result['source_added_indices'],'indices':indices,'durations':frame_durations,
        'initial_error':result['initial_error'],'selected_error':result['selected_error']}))


if __name__=='__main__':main()
