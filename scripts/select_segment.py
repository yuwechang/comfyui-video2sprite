"""Locate a loop, return-to-start action, or end-pose hold from visual motion."""
import argparse
import json
import math
from pathlib import Path
from statistics import median
import subprocess
from PIL import Image, ImageChops, ImageStat
from image_features import main_component,row_background_mask


def features(video, start=None, end=None, full_rate=False, subject_only=False, horizontal_background=False,
             foreground=None, mask_output=None):
    info = json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
        '-show_entries','stream=width,height,avg_frame_rate','-of','json',str(video)]))['streams'][0]
    numerator,denominator = map(float,info['avg_frame_rate'].split('/'))
    stride = 1 if full_rate else max(1,math.ceil(numerator/denominator/12))
    if (start is None) != (end is None) or (start is not None and not 0 <= start <= end):
        raise ValueError('Analysis interval requires 0 <= start <= end')
    engine = None
    if foreground is not None:
        from subject_mask import SubjectMask,WorkflowMask
        engine = WorkflowMask(**foreground) if 'profile' in foreground else SubjectMask(**foreground)
    scale = (1 if foreground and 'profile' in foreground else
             min(1,(1024 if engine else 96)/max(info['width'],info['height'])))
    size = tuple(max(1,round(info[k]*scale)) for k in ('width','height'))
    selection = f'between(n\\,{start}\\,{end})' if start is not None else f'not(mod(n\\,{stride}))'
    command=['ffmpeg','-v','error','-i',str(video),'-vf',
             f'select={selection},scale={size[0]}:{size[1]}',
             '-fps_mode','vfr','-f','rawvideo','-pix_fmt','rgb24','-']
    images=[]
    with subprocess.Popen(command,stdout=subprocess.PIPE) as process:
        while raw:=process.stdout.read(size[0]*size[1]*3):
            if len(raw)!=size[0]*size[1]*3:
                raise ValueError('Incomplete analysis frame')
            im=Image.frombytes('RGB',size,raw)
            if engine:
                if hasattr(engine,'source_index'):
                    engine.source_index=start+len(images) if start is not None else len(images)*stride
                mask=engine.mask(im)
                if mask_output:
                    folder=Path(mask_output);folder.mkdir(parents=True,exist_ok=True)
                    mask.save(folder/f'mask-{len(images):04d}.png')
                mask=mask.point(lambda v:255 if v>=128 else 0)
                target=tuple(max(1,round(v*96/max(size))) for v in size)
                im=im.resize(target,Image.Resampling.BILINEAR)
                mask=mask.resize(target,Image.Resampling.NEAREST)
            else:
                corners=[im.getpixel(p) for p in ((0,0),(size[0]-1,0),(0,size[1]-1),(size[0]-1,size[1]-1))]
                bg=tuple(round(median(p[c] for p in corners)) for c in range(3))
                diff=ImageChops.difference(im,Image.new('RGB',size,bg))
                r,g,b=diff.split()
                mask=ImageChops.lighter(ImageChops.lighter(r,g),b).point(lambda v:255 if v>28 else 0)
                if horizontal_background:mask=row_background_mask(im)
                if subject_only:mask=main_component(mask)
            images.append(appearance_feature(im,mask))
        if process.wait()!=0:
            raise ValueError('Video analysis decode failed')
    if start is not None and len(images) != end-start+1:
        raise ValueError('Video did not contain every analysis frame')
    if len(images)<(2 if full_rate else 4):
        raise ValueError('Video is too short for segment analysis')
    if engine and mask_output:
        indices=list(range(start,end+1)) if start is not None else [i*stride for i in range(len(images))]
        metadata={**engine.metadata,'video':str(Path(video).resolve()),'source_indices':indices,
                  'analysis_size':list(size),'mask_threshold':128}
        (Path(mask_output)/'analysis.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    bounds=[im.getbbox() for im in images if im.getbbox()]
    if not bounds:
        raise ValueError('No foreground for analysis')
    box=(min(b[0] for b in bounds),min(b[1] for b in bounds),
         max(b[2] for b in bounds),max(b[3] for b in bounds))
    return [im.crop(box).resize((48,64),Image.Resampling.BILINEAR) for im in images],stride


def appearance_feature(image,mask):
    """Keep masked colour and dark internal detail, with a small silhouette floor."""
    appearance=image.convert('RGB').point(lambda v:32+round(v*223/255))
    return ImageChops.multiply(appearance,mask.convert('RGB'))


def stable_runs(motion, threshold, minimum=2):
    runs=[]; start=None
    for i,value in enumerate(motion+[float('inf')]):
        if value<=threshold:
            if start is None:start=i
        elif start is not None:
            if i-start+1>=minimum:runs.append((start,i))
            start=None
    return runs


def locate(images, kind, stride=1, count=None, stable_threshold=None):
    if kind not in ('loop','return_to_start','hold_end_pose'):
        raise ValueError('Unknown motion type')
    if (count is not None and (type(count) is not int or count<2)) or len(images)<4:
        raise ValueError('Need at least two samples and four analysis frames')
    if stable_threshold is not None and (not math.isfinite(stable_threshold) or stable_threshold<0):
        raise ValueError('Stable threshold must be finite and nonnegative')
    sums=[sum(ImageStat.Stat(im).sum) for im in images]
    cache={}
    def distance(a,b):
        key=(min(a,b),max(a,b))
        if key not in cache:
            cache[key]=sum(ImageStat.Stat(ImageChops.difference(images[a],images[b])).sum)/max(sums[a],sums[b],1)
        return cache[key]
    n=len(images)
    motion=[distance(i,i+1) for i in range(n-1)]
    ordered=sorted(motion)
    threshold=stable_threshold if stable_threshold is not None else max(.008,min(.18,ordered[len(ordered)*35//100]*1.5))
    runs=stable_runs(motion,threshold)
    minimum=max(4 if kind=='loop' else 2,
                math.ceil((count if count is not None else (4 if kind=='loop' else 2))/stride))
    def movement(a,b):
        return max(distance(a,k) for k in range(a+1,b)) if b>a+1 else 0
    candidates=[]
    return_candidates=[]
    cycle_candidates=[]
    activity_episodes=[]
    if kind=='loop':
        chains=[]
        # Search phase baselines throughout the clip: an opening transition need
        # not recur, and a valid cycle may begin after it. One chain uses a common
        # baseline and only consecutive returns, never overlapping long pairs.
        for anchor in range(n-minimum):
            departure=[distance(anchor,i) for i in range(anchor,n)]
            meaningful=max(.16,max(departure)*.5)
            limit=min(.30,max(.08,max(departure)*.25))
            boundaries=[anchor];away=False;i=anchor+1
            while i<n:
                if distance(anchor,i)>meaningful:away=True
                if away and distance(anchor,i)<=limit:
                    last=i
                    while last+1<n and distance(anchor,last+1)<=limit:last+=1
                    boundaries.append(min(range(i,last+1),key=lambda k:(distance(anchor,k),k)))
                    away=False;i=last
                i+=1
            chain=[]
            for a,b in zip(boundaries,boundaries[1:]):
                seam=distance(a,b)
                if b-a<minimum or seam>.30 or movement(a,b)<meaningful:continue
                neighbours=[distance(a+d,b+d) for d in (-1,0,1) if 0<=a+d<n and 0<=b+d<n]
                score=seam+.35*sum(neighbours)/len(neighbours)
                chain.append((score,a,b,seam))
            if chain:chains.append(chain)
        if chains:
            candidates=min(chains,key=lambda chain:(-len(chain),sum(c[0] for c in chain)/len(chain),chain[0][1]))
        for score,a,b,seam in candidates:
            cycle_candidates.append({'start':a*stride,'end':b*stride-1,'matching_tail':b*stride,
                'score':round(score,6),'seam_distance':round(seam,5)})
    elif kind=='return_to_start':
        # Stable visits near the opening baseline divide repeated performances.
        # Compare complete neighbouring visits before considering a long return.
        anchor=runs[0][1] if runs and runs[0][0]<=2 else 0
        for first,last in runs[1:]:
            if first>anchor+1:break
            anchor=last
        departure=[distance(anchor,i) for i in range(n)]
        excursion=max(departure)
        meaningful=max(.16,excursion*.5)
        return_limit=min(.30,max(.08,excursion*.25))
        visit_limit=max(return_limit,min(.60,excursion*.45))
        visits=[]
        for first,last in runs:
            if min(departure[first:last+1])>visit_limit:continue
            if visits and movement(visits[-1][1],first)<meaningful:
                visits[-1]=(visits[-1][0],last)
            else:
                visits.append((first,last))
        for (_,head),(first,last) in zip(visits,visits[1:]):
            # Finish at the first settled return, not a later frame that happens
            # to match the opening more exactly after an unrelated idle hold.
            tail=next((k for k in range(first,last+1) if distance(head,k)<=visit_limit),first)
            peak=movement(head,tail)
            seam=distance(head,tail)
            if tail-head<minimum or peak<meaningful or seam>visit_limit:continue
            # Relative closure ranks local returns despite modest baseline drift;
            # ties favour the earlier complete performance, never extra duration.
            score=seam/max(peak,.16)
            candidates.append((score,head,tail,seam))
            return_candidates.append({'start':head*stride,'end':tail*stride,
                'seam_distance':round(seam,5),'excursion':round(peak,5),
                'score':round(score,6),'method':'stable_baseline_visits'})
        left=next((i for i in range(anchor+1,n) if departure[i]>max(meaningful,return_limit*2)),None)
        returned=next((i for i in range(left+1,n) if departure[i]<=return_limit),None) if left is not None else None
        if not candidates and returned is not None and returned-anchor>=minimum:
            candidates.append((distance(anchor,returned),anchor,returned,distance(anchor,returned)))
        if not candidates:
            for i,(_,head) in enumerate(runs):
                for tail,_ in runs[i+1:]:
                    if tail-head<minimum or movement(head,tail)<meaningful:continue
                    seam=distance(head,tail)
                    if seam<=.30:
                        candidates.append((seam+.02*(tail-head)/n,head,tail,seam))
        if not candidates:
            # A single action need not pause at both ends. Fall back to matching poses;
            # this remains a candidate requiring visual confirmation, not a type change.
            for head in range(n-minimum):
                for tail in range(head+minimum,n):
                    seam=distance(head,tail)
                    if distance(anchor,head)<=return_limit and seam<=return_limit and movement(head,tail)>=meaningful:
                        candidates.append((seam+.02*(1-(tail-head)/n),head,tail,seam))
    else:
        # Locate the principal activity before choosing its preceding stable boundary.
        # A late settling movement must not hide the earlier complete action.
        terminal=[run for run in runs if run[1]>=n-3]
        if terminal:
            tail=terminal[-1][0]
            episodes=[]
            for (_,head),(stop,_) in zip(runs,runs[1:]):
                if head>=tail or stop<=head:continue
                # Excess motion excludes stable noise. Integrated energy ranks whole
                # activity episodes rather than individual flashing/noisy frames.
                energy=sum(max(0,v-threshold)**2 for v in motion[head:min(stop,tail)])
                episodes.append((energy,head,min(stop,tail)))
            activity_episodes=[{'start':head*stride,'end':stop*stride,'energy':round(energy,6)}
                               for energy,head,stop in episodes]
            if episodes:
                energy,head,stop=max(episodes,key=lambda item:(item[0],-item[1]))
                # A held final pose may follow several substantial phases. Use
                # the energy/complexity knee to retain a set of episodes, rather
                # than dropping every phase before the single largest burst.
                ranked=sorted((item for item in episodes if item[0]>0),key=lambda item:(-item[0],item[1]))
                if ranked:
                    total=sum(item[0] for item in ranked);cumulative=0;choices=[]
                    for count,item in enumerate(ranked,1):
                        cumulative+=item[0]
                        choices.append((cumulative/total-count/len(ranked),-count,count))
                    keep=max(choices)[2]
                    retained=ranked[:keep]
                    head=min(item[1] for item in retained)
                    for row in activity_episodes:
                        row['retained_major_phase']=any(row['start']==item[1]*stride for item in retained)
                if energy>0 and tail-head>=minimum and movement(head,tail)>=.16:
                    candidates.append((-energy,head,tail,distance(head,tail)))
    if not candidates:
        return {'status':'needs_review','motion_type':kind,'stable_threshold':threshold,
                'stable_runs':[[a*stride,b*stride] for a,b in runs]}
    candidates.sort()
    score,a,b,seam=candidates[0]
    start,tail=a*stride,b*stride
    lead_review=(kind=='hold_end_pose' and not
                 (a==0 or (runs and runs[0][0]==0 and runs[0][1]>=a)))
    return {'status':'selected','motion_type':kind,'start':start,
            'end':tail-1 if kind=='loop' else tail,'matching_tail':tail,
            'loop':kind=='loop','seam_distance':round(seam,5),
            'analysis_stride':stride,'stable_threshold':threshold,
            'review_required':True, 'lead_review_required':lead_review,
            'lead_start':start if kind=='hold_end_pose' and not lead_review else None,
            'lead_candidate_range':[0,start] if kind=='hold_end_pose' else None,
            'activity_episodes':activity_episodes if kind=='hold_end_pose' else None,
            'return_candidates':return_candidates if kind=='return_to_start' else None,
            'cycle_candidates':cycle_candidates if kind=='loop' else None,
            'complete_cycle_count':len(cycle_candidates) if kind=='loop' and cycle_candidates else None,
            'stable_runs':[[x*stride,y*stride] for x,y in runs]}


def select(video,kind,count=None,stable_threshold=None,foreground=None,mask_output=None):
    # Hold boundaries describe X/Y timing; preserve exact source-frame resolution.
    images,stride=features(video,full_rate=kind in ('hold_end_pose','return_to_start'),
                          subject_only=kind in ('return_to_start','loop'),horizontal_background=kind=='loop',
                          foreground=foreground,mask_output=mask_output)
    result=locate(images,kind,stride,count,stable_threshold)
    if foreground is not None:
        result['foreground']={**foreground,'mask_output':str(Path(mask_output).resolve()) if mask_output else None}
        if mask_output:
            result['analysis_metadata']=str((Path(mask_output)/'analysis.json').resolve())
            result['analysis_masks']=[str((Path(mask_output)/f'mask-{i:04d}.png').resolve()) for i in range(len(images))]
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video')
    parser.add_argument('--motion-type',required=True,choices=('loop','return_to_start','hold_end_pose'))
    parser.add_argument('--count',type=int,help='Optional explicit sample count, not a default segment length')
    parser.add_argument('--stable-threshold',type=float)
    parser.add_argument('--output')
    parser.add_argument('--foreground-profile',help='JSON with model_dir, device, model for independent Python segmentation')
    parser.add_argument('--mask-output')
    args=parser.parse_args()
    try:
        foreground=json.loads(Path(args.foreground_profile).read_text(encoding='utf-8-sig')) if args.foreground_profile else None
        result=select(args.video,args.motion_type,args.count,args.stable_threshold,foreground,args.mask_output)
        if args.output:
            path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({'status':'error','error':str(exc)}))
        raise SystemExit(1)
