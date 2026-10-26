"""Locate a continuous loop, paused loop, or one-shot interval from visual motion."""
import argparse
import json
import math
from pathlib import Path
from statistics import median
import subprocess
from PIL import Image, ImageChops, ImageStat


def features(video):
    info = json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
        '-show_entries','stream=width,height,avg_frame_rate','-of','json',str(video)]))['streams'][0]
    numerator,denominator = map(float,info['avg_frame_rate'].split('/'))
    stride = max(1,math.ceil(numerator/denominator/12))
    scale = min(1,96/max(info['width'],info['height']))
    size = tuple(max(1,round(info[k]*scale)) for k in ('width','height'))
    command=['ffmpeg','-v','error','-i',str(video),'-vf',
             f'select=not(mod(n\\,{stride})),scale={size[0]}:{size[1]}',
             '-fps_mode','vfr','-f','rawvideo','-pix_fmt','rgb24','-']
    images=[]
    with subprocess.Popen(command,stdout=subprocess.PIPE) as process:
        while raw:=process.stdout.read(size[0]*size[1]*3):
            if len(raw)!=size[0]*size[1]*3:
                raise ValueError('Incomplete analysis frame')
            im=Image.frombytes('RGB',size,raw)
            corners=[im.getpixel(p) for p in ((0,0),(size[0]-1,0),(0,size[1]-1),(size[0]-1,size[1]-1))]
            bg=tuple(round(median(p[c] for p in corners)) for c in range(3))
            diff=ImageChops.difference(im,Image.new('RGB',size,bg))
            r,g,b=diff.split()
            mask=ImageChops.lighter(ImageChops.lighter(r,g),b).point(lambda v:255 if v>28 else 0)
            silhouette=mask.point(lambda v:128 if v else 0)
            intensity=ImageChops.multiply(im.convert('L'),mask)
            images.append(ImageChops.lighter(silhouette,intensity))
        if process.wait()!=0:
            raise ValueError('Video analysis decode failed')
    if len(images)<4:
        raise ValueError('Video is too short for segment analysis')
    bounds=[im.getbbox() for im in images if im.getbbox()]
    if not bounds:
        raise ValueError('No foreground for analysis')
    box=(min(b[0] for b in bounds),min(b[1] for b in bounds),
         max(b[2] for b in bounds),max(b[3] for b in bounds))
    return [im.crop(box).resize((48,64),Image.Resampling.BILINEAR) for im in images],stride


def stable_runs(motion, threshold, minimum=2):
    runs=[]; start=None
    for i,value in enumerate(motion+[float('inf')]):
        if value<=threshold:
            if start is None:start=i
        elif start is not None:
            if i-start+1>=minimum:runs.append((start,i))
            start=None
    return runs


def locate(images, kind, stride=1, count=8, stable_threshold=None):
    if kind not in ('continuous','paused','once'):
        raise ValueError('Unknown motion type')
    if count<2 or len(images)<4:
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
    minimum=max(4,math.ceil(count/stride))
    def movement(a,b):
        return max(distance(a,k) for k in range(a+1,b)) if b>a+1 else 0
    candidates=[]
    if kind=='continuous':
        for a in range(n-minimum):
            for b in range(a+minimum,n):
                seam=distance(a,b)
                if seam>.30 or movement(a,b)<.16:continue
                neighbours=[distance(a+d,b+d) for d in (-1,0,1) if 0<=a+d<n and 0<=b+d<n]
                score=seam+.35*sum(neighbours)/len(neighbours)+.025*(b-a)/n
                candidates.append((score,a,b,seam))
    elif kind=='paused':
        for i,(_,head) in enumerate(runs):
            for tail,_ in runs[i+1:]:
                if tail-head<minimum or movement(head,tail)<.16:continue
                seam=distance(head,tail)
                if seam<=.30:
                    candidates.append((seam+.02*(tail-head)/n,head,tail,seam))
    else:
        # Final stable run is the terminal pose, not another start candidate.
        terminal=[run for run in runs if run[1]>=n-3]
        if terminal:
            tail=terminal[-1][0]
            for start,end in reversed(runs):
                if end>=tail or tail-end<minimum or movement(end,tail)<.16:continue
                seam=distance(end,tail)
                score=(tail-end)/n
                candidates.append((score,end,tail,seam))
                break
    if not candidates:
        return {'status':'needs_review','motion_type':kind,'stable_threshold':threshold,
                'stable_runs':[[a*stride,b*stride] for a,b in runs]}
    candidates.sort()
    score,a,b,seam=candidates[0]
    start,tail=a*stride,b*stride
    return {'status':'selected','motion_type':kind,'start':start,
            'end':tail-1 if kind=='continuous' else tail,'matching_tail':tail,
            'loop':kind=='continuous','seam_distance':round(seam,5),
            'analysis_stride':stride,'stable_threshold':threshold,
            'stable_runs':[[x*stride,y*stride] for x,y in runs]}


def select(video,kind,count=8,stable_threshold=None):
    images,stride=features(video)
    return locate(images,kind,stride,count,stable_threshold)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video')
    parser.add_argument('--motion-type',required=True,choices=('continuous','paused','once'))
    parser.add_argument('--count',type=int,default=8)
    parser.add_argument('--stable-threshold',type=float)
    parser.add_argument('--output')
    args=parser.parse_args()
    try:
        result=select(args.video,args.motion_type,args.count,args.stable_threshold)
        if args.output:
            path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({'status':'error','error':str(exc)}))
        raise SystemExit(1)
