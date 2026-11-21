"""Offer explicit geometry/background candidates; contact meaning requires review."""
import argparse
import json
import math
from pathlib import Path
from statistics import median
from PIL import Image, ImageDraw
from generate import save
from image_features import main_component,row_background_mask

def propose(image_path):
    with Image.open(image_path) as image:
        original=image.size;factor=min(1,320/max(original))
        image=image.convert('RGBA').resize(tuple(max(1,round(v*factor)) for v in original))
    alpha=image.getchannel('A')
    foreground=alpha.point(lambda v:255 if v>=16 else 0) if alpha.getextrema()[0]<255 else main_component(row_background_mask(image))
    box=foreground.getbbox()
    if box is None:return {'status':'needs_input','reason':'No distinct foreground candidate'}
    w,h=image.size;x0,y0,x1,y1=box
    bbox=[math.floor(x0/factor),math.floor(y0/factor),min(original[0],math.ceil(x1/factor)),min(original[1],math.ceil(y1/factor))]
    bottom=[x for y in range(max(y0,y1-max(1,(y1-y0)//20)),y1) for x in range(x0,x1) if foreground.getpixel((x,y))]
    return {'status':'candidate','image':str(Path(image_path).resolve()),'source_size':list(original),
        'subject_box':bbox,'ground_anchor':[round((min(bottom)+max(bottom))/2/factor,2),bbox[3]],
        'checks':{'touches_edge':x0==0 or y0==0 or x1==w or y1==h,
                  'foreground_area_fraction':round(sum(1 for v in foreground.tobytes() if v)/(w*h),4)},
        'requires_confirmation':True,
        'reason':'Foreground extent and lowest visible region are candidates, not proof of shoe contact; inspect shadows, effects and detached parts'}

def background(selection_file):
    from camera_alignment import boundary,estimate
    data=json.loads(Path(selection_file).read_text(encoding='utf-8-sig'));images=[];boxes=[]
    for path in data['selected_frames']:
        with Image.open(path) as im:
            image=im.convert('RGB');images.append(image)
            factor=min(1,320/max(image.size));small=image.resize(tuple(max(1,round(v*factor)) for v in image.size))
            box=row_background_mask(small).getbbox()
            if box:boxes.append([int(box[0]/factor),int(box[1]/factor),math.ceil(box[2]/factor),math.ceil(box[3]/factor)])
    if not images or not boxes:return {'status':'needs_input','reason':'No foreground exclusion bounds'}
    w,h=images[0].size;left=min(b[0] for b in boxes);right=max(b[2] for b in boxes)
    if left<24 or w-right<24:return {'status':'needs_input','reason':'Insufficient clear background on both sides'}
    bands=[[2,3,left-3,h-3],[right+3,3,w-2,h-3]]
    try:
        hits=[boundary(images[0],r) for r in bands]
        if abs(hits[0]['y']-hits[1]['y'])>3:raise ValueError('Independent bands disagree')
        regions=[[r[0],max(0,round(hit['y'])-40),r[2],min(h,round(hit['y'])+41)] for r,hit in zip(bands,hits)]
        shifts,tracks=estimate(images,regions)
    except ValueError as exc:return {'status':'needs_input','reason':str(exc)}
    return {'status':'candidate','regions':regions,'requires_confirmation':True,
            'checks':{'estimated_dy':shifts,'tracks':tracks},
            'reason':'Numerically consistent clear bands; confirm stationary background identity before applying'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--image');source.add_argument('--selection-file')
    parser.add_argument('--output',required=True);args=parser.parse_args()
    result=propose(args.image) if args.image else background(args.selection_file)
    if result['status']=='candidate':
        source=args.image
        if not source:source=json.loads(Path(args.selection_file).read_text(encoding='utf-8-sig'))['selected_frames'][0]
        with Image.open(source) as im:preview=im.convert('RGB')
        draw=ImageDraw.Draw(preview)
        if args.image:
            draw.rectangle(result['subject_box'],outline='yellow',width=2)
            x,y=result['ground_anchor'];draw.ellipse((x-5,y-5,x+5,y+5),outline='red',width=2)
        else:
            for region in result['regions']:draw.rectangle(region,outline='yellow',width=2)
        target=Path(args.output).with_suffix('.png');target.parent.mkdir(parents=True,exist_ok=True)
        preview.save(target);result['preview']=str(target.resolve())
    save(args.output,result);print(json.dumps(result))

if __name__=='__main__':main()
