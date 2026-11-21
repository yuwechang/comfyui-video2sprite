"""Opt-in Y research: four automatic pose-keyframe prototypes, not production defaults."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import numpy as np
from pose_reliability import (JOINTS,input_quality,confidence_weights,weighted_smooth,
                              EvidenceMetric,POLICY)



def smooth(values,radius):
    return np.asarray([np.mean(values[max(0,i-radius):min(len(values),i+radius+1)],axis=0)
                       for i in range(len(values))])


def otsu(values):
    values=np.asarray(values,float)
    if np.ptp(values)<1e-12:return float(values.max())
    counts,edges=np.histogram(values,bins=min(64,max(8,len(values))))
    centres=(edges[:-1]+edges[1:])/2
    mass=np.cumsum(counts);moment=np.cumsum(counts*centres)
    denominator=mass*(mass[-1]-mass)
    score=np.divide((moment[-1]*mass-moment*mass[-1])**2,denominator,
                    out=np.zeros_like(moment),where=denominator>0)
    return float(centres[np.argmax(score)])


def pose_distance(a,b):
    return np.linalg.norm(a-b,axis=-1).mean(axis=-1)


def recursive_simplify(poses,times,tolerance):
    chosen={0,len(poses)-1};trace=[]
    def split(a,b):
        if b<=a+1:return
        t=(times[a+1:b]-times[a])/(times[b]-times[a])
        prediction=poses[a][None]+t[:,None,None]*(poses[b]-poses[a])[None]
        errors=pose_distance(poses[a+1:b],prediction)
        i=a+1+int(np.argmax(errors));error=float(errors.max())
        trace.append({'head':a,'tail':b,'candidate':i,'error':error})
        if error>tolerance:
            chosen.add(i);split(a,i);split(i,b)
    split(0,len(poses)-1)
    return sorted(chosen),trace


def recursive_knee(poses,times,weights=None,appearance=None):
    """Hierarchical largest-error splitting; automatic error/complexity knee."""
    metric=EvidenceMetric(poses,weights,appearance) if weights is not None else None
    def interval(a,b):
        if b<=a+1:return (0,None)
        t=(times[a+1:b]-times[a])/(times[b]-times[a])
        prediction=poses[a]+t[:,None,None]*(poses[b]-poses[a])
        errors=(pose_distance(poses[a+1:b],prediction) if metric is None else
                metric.interpolation(a,b,np.arange(a+1,b),t))
        return float(errors.max()),a+1+int(np.argmax(errors))
    indices=[0,len(poses)-1];states=[]
    while True:
        candidates=[(interval(a,b),a,b) for a,b in zip(indices,indices[1:])]
        best=max(candidates,key=lambda row:row[0][0])
        error,i=best[0];states.append({'indices':indices.copy(),'max_error':error})
        if i is None or error<=1e-12:break
        indices=sorted(indices+[i])
    initial=states[0]['max_error']
    if initial<=1e-12:return states[0]['indices'],states
    for state in states:
        complexity=(len(state['indices'])-2)/max(len(poses)-2,1)
        state['knee_score']=1-state['max_error']/initial-complexity
    chosen=max(states,key=lambda state:(state['knee_score'],-len(state['indices'])))
    return chosen['indices'],states


def local_peaks(signal):
    return [i for i in range(1,len(signal)-1)
            if signal[i]>signal[i-1] and signal[i]>=signal[i+1]]


def curve_saliency(poses):
    # Multiscale curvature prototypes: shared scales, no action-specific joints.
    score=np.zeros(len(poses))
    for width in (1,2,4):
        for i in range(width,len(poses)-width):
            left=poses[i]-poses[i-width];right=poses[i+width]-poses[i]
            numerator=np.sum(left*right,axis=-1)
            lengths=np.linalg.norm(left,axis=-1)*np.linalg.norm(right,axis=-1)
            cosine=np.divide(numerator,lengths,out=np.ones_like(numerator),where=lengths>1e-12)
            amount=np.minimum(np.linalg.norm(left,axis=-1),np.linalg.norm(right,axis=-1))
            score[i]+=float(np.mean((1-np.clip(cosine,-1,1))*amount))/width
    return [0]+[i for i in local_peaks(score) if score[i]>otsu(score)]+[len(poses)-1],score.tolist()


def speed_minima(poses,times):
    speed=np.r_[0,pose_distance(poses[1:],poses[:-1])/np.diff(times)]
    prominence=np.zeros(len(poses))
    for radius in (1,2,4):
        filtered=smooth(speed,radius)
        for i in local_peaks(-filtered):
            left=filtered[max(0,i-2*radius):i]
            right=filtered[i+1:min(len(poses),i+2*radius+1)]
            if len(left) and len(right):
                prominence[i]+=max(0,min(left.max(),right.max())-filtered[i])
    return [0]+[i for i in local_peaks(prominence) if prominence[i]>otsu(prominence)]+[len(poses)-1],prominence.tolist()


def temporal_clusters(poses,noise):
    # BIC-penalized contiguous segmentation; representative is an actual medoid.
    x=poses.reshape(len(poses),-1);n,d=x.shape
    prefix=np.vstack((np.zeros(d),np.cumsum(x,axis=0)))
    squares=np.r_[0,np.cumsum(np.sum(x*x,axis=1))]
    variance=max(noise**2/2,1e-12);penalty=d*np.log(max(n,2))
    cost=np.full(n+1,np.inf);cost[0]=-penalty;previous=np.zeros(n+1,int)
    for b in range(1,n+1):
        for a in range(b):
            total=prefix[b]-prefix[a]
            sse=max(0,squares[b]-squares[a]-np.sum(total*total)/(b-a))
            value=cost[a]+sse/variance+penalty
            if value<cost[b]:cost[b]=value;previous[b]=a
    representatives={0,n-1};segments=[];b=n
    while b:
        a=int(previous[b]);part=poses[a:b]
        distances=np.asarray([pose_distance(part,p).sum() for p in part])
        candidates=np.flatnonzero(np.isclose(distances,distances.min()))
        index=a+int(min(candidates,key=lambda i:abs(i-(b-a-1)/2)))
        if not any(a<=j<b and pose_distance(poses[index],poses[j])<=1e-12 for j in representatives):
            representatives.add(index)
        segments.append([a,b,index]);b=a
    return sorted(representatives),list(reversed(segments))


def benchmark(poses,times,weights=None,appearance=None):
    filtered=smooth(poses,1)
    reliable_filtered=filtered if weights is None else weighted_smooth(poses,weights)
    metric=EvidenceMetric(reliable_filtered,weights,appearance) if weights is not None else None
    noise=float(np.median(pose_distance(poses,filtered)))
    residual=pose_distance(poses,filtered)
    tolerance=float(np.median(residual)+3*np.median(np.abs(residual-np.median(residual))))
    tolerance=max(tolerance,1e-8)
    methods={};routines={
        'recursive_trajectory':lambda:recursive_simplify(filtered,times,tolerance),
        'recursive_automatic_knee':lambda:recursive_knee(reliable_filtered,times,weights,appearance),
        'multiscale_saliency':lambda:curve_saliency(filtered),
        'speed_minima':lambda:speed_minima(filtered,times),
        'temporal_clusters':lambda:temporal_clusters(filtered,noise)}
    for name,routine in routines.items():
        start=time.perf_counter();indices,trace=routine();errors=[]
        for a,b in zip(indices,indices[1:]):
            for i in range(a,b+1):
                t=(times[i]-times[a])/(times[b]-times[a])
                if name=='recursive_automatic_knee' and weights is not None:
                    errors.append(float(metric.interpolation(a,b,i,t)))
                else:errors.append(float(pose_distance(filtered[i],(1-t)*filtered[a]+t*filtered[b])))
        methods[name]={'indices':indices,'count':len(indices),'seconds':time.perf_counter()-start,
            'max_pose_reconstruction_error':max(errors,default=0),
            'mean_pose_reconstruction_error':float(np.mean(errors)),'trace':trace}
    return {'noise':noise,'recursive_tolerance':tolerance,'methods':methods,
            'prototypes_not_exact_paper_reproductions':True,
            'reconstruction_is_numeric_diagnostic_not_sprite_playback':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',required=True);parser.add_argument('--model',required=True)
    parser.add_argument('--start',type=int,required=True);parser.add_argument('--end',type=int,required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--analysis-masks',help='Existing original-size RGB/Alpha analysis masks for occlusion evidence')
    args=parser.parse_args();folder=Path(args.output).resolve();folder.mkdir(parents=True,exist_ok=True)
    signature={'video_sha256':hashlib.sha256(Path(args.video).read_bytes()).hexdigest(),
        'model_sha256':hashlib.sha256(Path(args.model).read_bytes()).hexdigest(),
        'start':args.start,'end':args.end,'joints':JOINTS}
    cache=folder/'landmarks.json';started=time.perf_counter()
    if cache.exists():
        data=json.loads(cache.read_text())
        if json.dumps(data['signature'],sort_keys=True)!=json.dumps(signature,sort_keys=True):
            raise ValueError('Pose cache inputs changed')
    else:
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
            '-show_entries','stream=width,height,avg_frame_rate','-of','json',args.video]))['streams'][0]
        width,height=info['width'],info['height'];p,q=map(int,info['avg_frame_rate'].split('/'));fps=p/q
        command=['ffmpeg','-v','error','-i',args.video,'-vf',
            f'select=between(n\\,{args.start}\\,{args.end})','-fps_mode','vfr','-f','rawvideo','-pix_fmt','rgb24','-']
        rows=[];visibility=[];missing=[]
        options=vision.PoseLandmarkerOptions(base_options=python.BaseOptions(model_asset_path=args.model),
            running_mode=vision.RunningMode.VIDEO,num_poses=1)
        with vision.PoseLandmarker.create_from_options(options) as model,subprocess.Popen(command,stdout=subprocess.PIPE) as process:
            index=args.start
            while raw:=process.stdout.read(width*height*3):
                image=np.frombuffer(raw,dtype=np.uint8).reshape(height,width,3).copy()
                result=model.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,data=image),round(index/fps*1000))
                if not result.pose_landmarks:missing.append(index)
                else:
                    landmarks=result.pose_landmarks[0]
                    rows.append([[landmarks[j].x*width,landmarks[j].y*height] for j in JOINTS])
                    visibility.append([landmarks[j].visibility for j in JOINTS])
                index+=1
            if process.wait()!=0:raise ValueError('Video decode failed')
        if missing:raise ValueError('Automatic pose extraction failed at frames '+str(missing))
        data={'signature':signature,'positions':rows,'visibility':visibility,
              'times':[(args.start+i)/fps for i in range(len(rows))]}
        cache.write_text(json.dumps(data),encoding='utf-8')
    positions=np.asarray(data['positions']);visibility=np.asarray(data['visibility'])
    if len(positions)!=args.end-args.start+1:raise ValueError('Incomplete pose sequence')
    appearance=None;appearance_contract=None
    if args.analysis_masks:
        from pose_appearance import extract
        appearance,appearance_contract=extract(args.video,args.analysis_masks,args.start,args.end,folder/'appearance.npz')
    quality=input_quality(positions,visibility,args.start,args.end,appearance)
    if not quality['passed']:
        report={'status':'input_rejected','quality':quality,'source_signature':signature}
        (folder/'benchmark.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({'status':'input_rejected','quality':quality}));return
    # One constant scale retains global movement and natural height changes.
    left_shoulder=JOINTS.index(11);left_hip=JOINTS.index(23)
    right_shoulder=JOINTS.index(12);right_hip=JOINTS.index(24)
    shoulders=(positions[:,left_shoulder]+positions[:,right_shoulder])/2
    hips=(positions[:,left_hip]+positions[:,right_hip])/2
    torso_reliable=(visibility[:,[JOINTS.index(j) for j in (11,12,23,24)]]>=.5).all(axis=1)
    scale_source='reliable_torso'
    if torso_reliable.any():scale=float(np.median(np.linalg.norm(shoulders-hips,axis=-1)[torso_reliable]))
    else:
        spans=[float(np.linalg.norm(np.ptp(row[v>=.5],axis=0)))
               for row,v in zip(positions,visibility) if (v>=.5).sum()>=2]
        spans=[span for span in spans if span>0]
        scale=float(np.median(spans)) if spans else 1.0
        scale_source='visible_joint_extent' if spans else 'appearance_only'
    if scale<=0:raise ValueError('Invalid pose scale')
    report=benchmark(positions/scale,np.asarray(data['times']),confidence_weights(visibility),appearance)
    report.update(quality=quality,reliability_policy=POLICY,common_scale=scale,scale_source=scale_source,
                  appearance_contract=appearance_contract,
                  confidence_aware_methods=['recursive_automatic_knee'])
    report.update(source_start=args.start,source_end=args.end,pose_extraction_seconds=time.perf_counter()-started,
        min_visibility=float(visibility.min()),low_visibility_fraction=float((visibility<.5).mean()),
        per_joint_min_visibility={str(j):float(visibility[:,i].min()) for i,j in enumerate(JOINTS)},
        manual_frame_selection=False,source_signature=signature)
    for result in report['methods'].values():result['source_indices']=[args.start+i for i in result['indices']]
    (folder/'benchmark.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(folder/'benchmark.json'),'low_visibility_fraction':report['low_visibility_fraction'],
        'methods':{name:{k:v for k,v in row.items() if k not in ('trace','indices')} for name,row in report['methods'].items()}}))


if __name__=='__main__':main()
