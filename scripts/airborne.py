"""Rotation-aware waist tracking on explicitly selected frames only."""
from PIL import Image,ImageChops,ImageStat
import math
from statistics import median
from pathlib import Path
import json
import hashlib
from PIL import ImageDraw


def validate_roi(image, roi):
    if (not isinstance(roi, list) or len(roi) != 4 or any(type(v) is not int for v in roi)
            or not 0 <= roi[0] < roi[2] <= image.width or not 0 <= roi[1] < roi[3] <= image.height
            or min(roi[2]-roi[0], roi[3]-roi[1]) < 12):
        raise ValueError('waist_roi must be four in-bounds integers, at least 12 pixels per side')


def create_reference(image, roi, output, frame_scale=1):
    validate_roi(image, roi)
    if type(frame_scale) not in (int, float) or not math.isfinite(frame_scale) or frame_scale <= 0:
        raise ValueError('Airborne reference scale must be positive')
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    image.convert('RGB').save(folder/'reference.png')
    profile = {'reference_image': 'reference.png', 'waist_roi': roi,
               'frame_size': list(image.size), 'anchor': 'waist', 'frame_scale': frame_scale}
    (folder/'airborne-reference.json').write_text(json.dumps(profile, indent=2), encoding='utf-8')
    return folder/'airborne-reference.json'


def load_reference(path):
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    source = Path(config['reference_image'])
    source = source if source.is_absolute() else path.parent/source
    with Image.open(source) as im:
        image = im.convert('RGB')
    validate_roi(image, config['waist_roi'])
    if config.get('anchor') != 'waist' or config['frame_size'] != list(image.size):
        raise ValueError('Airborne reference dimensions or anchor are invalid')
    if (type(config['frame_scale']) not in (int, float) or not math.isfinite(config['frame_scale'])
            or config['frame_scale'] <= 0):
        raise ValueError('Airborne reference scale must be positive')
    return image, config['waist_roi']


def align_selected(frames, indices, reference, roi, job, overrides=None, max_error=.25):
    validate_roi(reference, roi)
    if not math.isfinite(max_error) or not 0 <= max_error <= 1:
        raise ValueError('Maximum match error must be between 0 and 1')
    if len(frames) != len(indices) or not frames or any(im.size != reference.size for im in frames):
        raise ValueError('Selected frames must match reference canvas dimensions')
    overrides = {} if overrides is None else overrides
    if not isinstance(overrides, dict):
        raise ValueError('Waist overrides must map selected source indices to [x, y]')
    if set(overrides)-{str(i) for i in indices}:
        raise ValueError('Override indices must refer to selected source frames')
    folder = Path(job)
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    for frame, index in zip(frames, indices):
        if str(index) in overrides:
            point = overrides[str(index)]
            if (not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float)
                    or not math.isfinite(v) for v in point) or not 0 <= point[0] < frame.width
                    or not 0 <= point[1] < frame.height):
                raise ValueError('Waist overrides must be in-bounds [x, y] coordinates')
            record = {'x': point[0], 'y': point[1], 'source': 'explicit_override', 'error': None}
        else:
            record = match_waist(frame.convert('RGB'), reference, roi)
            record['source'] = 'python'
        record.update(source_frame_index=index, dy=round((roi[1]+roi[3])/2-record['y']))
        records.append(record)
    minimum = min(r['dy'] for r in records)
    maximum = max(r['dy'] for r in records)
    frames_out = []
    for order, (frame, record) in enumerate(zip(frames, records)):
        original = folder/'selected'/f'{order:03d}.png'
        original.parent.mkdir(exist_ok=True)
        frame.save(original)
        canvas = Image.new('RGB', (frame.width, frame.height+maximum-minimum), reference.getpixel((0, 0)))
        canvas.paste(frame.convert('RGB'), (0, record['dy']-minimum))
        target = folder/'aligned'/f'{order:03d}.png'
        target.parent.mkdir(exist_ok=True)
        canvas.save(target)
        frames_out.append(canvas.convert('RGBA'))
    needs_review = [r['source_frame_index'] for r in records if r['error'] is not None and r['error'] > max_error]
    result = {'anchor': 'waist', 'reference_roi': roi, 'source_size': list(reference.size),
              'reference_sha256': hashlib.sha256(reference.tobytes()).hexdigest(),
              'canvas_padding_top': -minimum, 'matches': records, 'needs_review': needs_review,
              'reference_point_aligned': [(roi[0]+roi[2])/2, (roi[1]+roi[3])/2-minimum]}
    (folder/'alignment.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    columns = min(6, len(frames))
    contact = Image.new('RGB', (columns*192, math.ceil(len(frames)/columns)*220), 'white')
    draw = ImageDraw.Draw(contact)
    for i, (frame, record) in enumerate(zip(frames_out, records)):
        im = frame.convert('RGB')
        y = round(result['reference_point_aligned'][1])
        ImageDraw.Draw(im).line((0, y, im.width, y), fill='cyan', width=2)
        im.thumbnail((188, 190))
        x, y = i%columns*192, i//columns*220
        contact.paste(im, (x+(192-im.width)//2, y+25))
        draw.text((x+4, y+4), f"#{record['source_frame_index']} dy={record['dy']}", fill='black')
    contact.save(folder/'alignment-preview.png')
    if needs_review:
        raise ValueError('Waist tracking needs review; inspect alignment.json and provide selected-frame overrides')
    return frames_out, result

def foreground(image, factor=4):
    image=image.convert('RGB')
    size=(max(1,image.width//factor),max(1,image.height//factor))
    small=image.resize(size,Image.Resampling.LANCZOS)
    corners=[small.getpixel(p) for p in [(0,0),(small.width-1,0),(0,small.height-1),(small.width-1,small.height-1)]]
    background=tuple(round(median(p[c] for p in corners)) for c in range(3))
    diff=ImageChops.difference(small,Image.new('RGB',size,background));r,g,b=diff.split()
    mask=ImageChops.lighter(ImageChops.lighter(r,g),b).point(lambda v:255 if v>32 else 0)
    return mask,(image.width/size[0],image.height/size[1])


def match_waist(frame, reference, roi, factor=6):
    validate_roi(reference, roi)
    template=reference.convert('RGB').crop(roi)
    bg=reference.convert('RGB').getpixel((0,0))
    diff=ImageChops.difference(template,Image.new('RGB',template.size,bg));r,g,b=diff.split()
    mask=ImageChops.lighter(ImageChops.lighter(r,g),b).point(lambda v:255 if v>32 else 0)
    if mask.getbbox() is None or max(ImageStat.Stat(template, mask).stddev) < 3:
        raise ValueError('Waist reference lacks distinguishable visible features')
    small=frame.convert('RGB').resize((frame.width//factor,frame.height//factor),Image.Resampling.LANCZOS)
    subject,_=foreground(frame,factor);box=subject.getbbox()
    if box is None:raise ValueError('Empty foreground')
    def rotated(angle,scale):
        image=template.rotate(-angle,Image.Resampling.BICUBIC,expand=True,fillcolor=bg)
        weight=mask.rotate(-angle,Image.Resampling.BILINEAR,expand=True,fillcolor=0)
        if scale!=1:
            size=(max(1,round(image.width/scale)),max(1,round(image.height/scale)))
            image=image.resize(size,Image.Resampling.BILINEAR);weight=weight.resize(size,Image.Resampling.BILINEAR)
        return image,weight,Image.merge('RGB',(weight,)*3),max(1,sum(ImageStat.Stat(weight).sum)*3)
    def error(source,image,weights,denominator,x,y):
        patch=source.crop((x,y,x+image.width,y+image.height))
        return sum(ImageStat.Stat(ImageChops.multiply(ImageChops.difference(patch,image),weights)).sum)/denominator
    candidates=[]
    for angle in range(0,360,30):
        image,mask3,weights,denom=rotated(angle,factor)
        for cy in range(max(image.height//2,box[1]),min(small.height-(image.height+1)//2,box[3])+1):
            y=cy-image.height//2
            for cx in range(max(image.width//2,box[0]),min(small.width-(image.width+1)//2,box[2])+1):
                x=cx-image.width//2
                candidates.append((error(small,image,weights,denom,x,y),angle,x,y,image.width,image.height))
    candidates.sort()
    hypotheses=[]
    for item in candidates:
        _,angle,x,y,width,height=item
        if all(math.hypot(x+width/2-(h[2]+h[4]/2),y+height/2-(h[3]+h[5]/2))>3
               or min((angle-h[1])%360,(h[1]-angle)%360)>=60 for h in hypotheses):
            hypotheses.append(item)
        if len(hypotheses)==4:break
    refined=[]
    source=frame.convert('RGB')
    for _,angle,x,y,width,height in hypotheses:
        target=((x+width/2)*factor,(y+height/2)*factor)
        for degree in range(angle-15,angle+16,5):
            image,mask3,weights,denom=rotated(degree,1)
            cx=round(target[0]-image.width/2);cy=round(target[1]-image.height/2)
            for y in range(max(0,cy-factor),min(frame.height-image.height,cy+factor)+1):
                for x in range(max(0,cx-factor),min(frame.width-image.width,cx+factor)+1):
                    refined.append((error(source,image,weights,denom,x,y),degree,x+image.width/2,y+image.height/2))
    score,angle,x,y=min(refined)
    return {'x':x,'y':y,'angle':angle%360,'error':round(score,5)}
