"""Formal pose sampling adapter: automatic segment -> major poses -> transitions."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from source_clock import FrameClock,phase_budget,QUANTUM_MS


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_script(python,script,args):
    result=subprocess.run([python,str(Path(__file__).with_name(script))]+list(map(str,args)),
                          capture_output=True,text=True,encoding='utf-8',errors='replace')
    if result.returncode:raise ValueError('Pose sampling failed: '+(result.stdout+'\n'+result.stderr)[-2000:])


def combine(clock,start,end,lead_start,seconds,result,x=None):
    a=start if lead_start is None else lead_start
    budget=phase_budget(clock,a,start,end,seconds)
    y=result['source_indices'];yticks=[v//QUANTUM_MS for v in result['frame_durations_ms']]
    x=x or {'indices':[],'ticks':[]}
    indices=x['indices']+y;durations=[t*QUANTUM_MS for t in x['ticks']+yticks]
    if indices!=sorted(set(indices)) or sum(durations)!=budget['actual_total_ms']:
        raise ValueError('Pose/X timing budget does not match')
    return indices,{'strategy':'segmented_pose' if a<start else 'pose_transition',
        'method':'pose','major_indices':result['source_major_indices'],
        'added_indices':result['source_added_indices'],'frame_durations_ms':durations,
        'phases':{'a':a,'b':start,'d':end,'x':x,'y':{'indices':y,'ticks':yticks}},'budget':budget,
        'source_timestamps_seconds':[float(clock.boundary(i)) for i in indices],
        'review_required':True,'lead_review_required':lead_start is None,
        'manual_frame_selection':False,'target_count':None}


def sample(video,start,end,output,seconds,motion_type,pose,foreground,lead_start=None,lead_refresh_ms=160):
    if motion_type not in ('return_to_start','hold_end_pose'):
        raise ValueError('Pose sampling supports return_to_start and hold_end_pose; choose another explicit method for other types')
    if not pose or not pose.get('model'):raise ValueError('Pose sampling requires pose.model and an environment with mediapipe')
    if not foreground:raise ValueError('Pose sampling requires foreground Alpha for occlusion evidence')
    python=pose.get('python',sys.executable);model=str(Path(pose['model']).resolve())
    clock=FrameClock.read(video);a=start if lead_start is None else lead_start
    steps=[float(clock.boundary(i+1)-clock.boundary(i)) for i in range(len(clock.pts))]
    if max(steps)-min(steps)>1e-4:raise ValueError('Pose extraction currently requires constant frame rate')
    seconds=float(clock.boundary(end+1)-clock.boundary(a)) if seconds is None else seconds
    budget=phase_budget(clock,a,start,end,seconds)
    root=Path(output).resolve()/'pose-analysis';root.mkdir(parents=True,exist_ok=True)
    # Explicit contract enables restart without silently recomputing a changed job.
    names=('pose_sampling.py','pose_reliability.py','pose_appearance.py','benchmark_pose_methods.py','pose_transition_research.py')
    contract={'video':digest(video),'model':digest(model),'start':start,'end':end,'a':a,
        'seconds':seconds,'foreground':foreground,'python':python,
        'foreground_profile':digest(foreground['profile']) if foreground.get('profile') else None,
        'code':{name:digest(Path(__file__).with_name(name)) for name in names}}
    state=root/'contract.json'
    if state.exists() and json.loads(state.read_text())!=contract:
        raise ValueError('Pose sampling inputs changed; use a new output directory')
    state.write_text(json.dumps(contract,indent=2),encoding='utf-8')
    masks=Path(output).resolve()/'analysis-masks'
    metadata=masks/'analysis.json'
    available=[]
    if metadata.exists():available=json.loads(metadata.read_text())['source_indices']
    if not set(range(start,end+1)).issubset(available):
        from select_segment import features
        features(video,start,end,full_rate=True,foreground=foreground,mask_output=masks)
    benchmark=root/'benchmark';benchmark_file=benchmark/'benchmark.json'
    if not benchmark_file.exists():
        run_script(python,'benchmark_pose_methods.py',['--video',video,'--model',model,'--start',start,
            '--end',end,'--analysis-masks',masks,'--output',benchmark])
    report=json.loads(benchmark_file.read_text())
    if not report.get('quality',{}).get('passed'):raise ValueError('Pose analysis rejected: '+str(report.get('quality')))
    transitions=root/'transition';transition_file=transitions/'report.json'
    if not transition_file.exists():
        run_script(python,'pose_transition_research.py',['--video',video,'--landmarks',benchmark/'landmarks.json',
            '--benchmark',benchmark_file,'--seconds',budget['y_ticks']*QUANTUM_MS/1000,
            '--motion-type',motion_type,'--output',transitions])
    result=json.loads(transition_file.read_text())
    if result.get('status')=='input_rejected':raise ValueError('Pose transitions rejected: '+str(result.get('quality')))
    from pose_appearance import load
    load(report['appearance_contract'],video,start,end)
    x=None
    if a<start:
        from select_segment import features
        from frame_sampling import lead_samples
        images,_=features(video,a,start,full_rate=True,foreground=foreground)
        x=lead_samples(images[:-1],clock,a,start,budget['x_ticks'],lead_refresh_ms,key_images=images)
    indices,sampling=combine(clock,start,end,lead_start,seconds,result,x)
    if motion_type!='hold_end_pose':sampling['lead_review_required']=False
    sampling.update(pose_report=str(benchmark_file),pose_landmarks=str(benchmark/'landmarks.json'),
        pose_transition_report=str(transition_file),pose_contract=str(state),
        pose_evidence=report['appearance_contract'],reliability_policy=report['reliability_policy'])
    return indices,sampling,seconds
