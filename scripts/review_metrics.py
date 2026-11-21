"""Numerical review aids; never infer identity, correct action or effect removal."""
import math
from pathlib import Path
from statistics import median
from PIL import Image, ImageChops, ImageStat
from image_features import main_component


def geometry_check(arguments, result):
    from prepare_character import reference_with_inset, place_at_scale, flatten, transparent_subject
    source=Path(arguments['image'])
    with Image.open(source) as im:original=im.convert('RGBA')
    if result.get('background_mode')=='preserve':
        from prepare_character import extend_edges
        from job_contract import file_digest
        source=Path(result['source_image'])
        with Image.open(source) as im:original=im.convert('RGB')
        factor=result['placement']['factor']
        size=tuple(max(1,round(v*factor)) for v in original.size)
        scaled=original.resize(size,Image.Resampling.LANCZOS)
        expected=extend_edges(scaled,(result['geometry']['width'],result['geometry']['height']),result['placement']['offset'])
        with Image.open(result['prepared']) as im:actual=im.convert('RGB')
        same=(file_digest(source)==result['source_sha256'] and actual.size==expected.size
              and actual.tobytes()==expected.tobytes())
        return {'passed':same,'reason':'Exact preserved-background scale/placement transform' if same else 'Preserved geometry mismatch',
                'scope':'pixel geometry only; contact meaning and body proportions require reviewed input'}
    if not transparent_subject(original):
        return {'passed':False,'reason':'Input requires content editing; inspect its actual output'}
    if arguments.get('stage','layout')=='standing':
        expected,_=reference_with_inset(original)
        target=result['standing']
    elif arguments.get('standing_reference') and not arguments.get('preparation'):
        import json
        meta=json.loads(Path(arguments['standing_reference']).read_text(encoding='utf-8'))
        subject,_=place_at_scale(original,result['geometry'],meta['scale_side'],meta['anchor'])
        expected=flatten(subject,tuple(result['background_rgb'])).convert('RGBA')
        target=result['prepared']
    else:
        return {'passed':False,'reason':'No reproducible transparent-source transform for this layout'}
    with Image.open(target) as im:actual=im.convert('RGBA')
    same=actual.size==expected.size and actual.tobytes()==expected.tobytes()
    report={'passed':same,'reason':'Exact pixel match to declared scale/placement transform' if same
            else 'Output differs from declared geometry transform',
            'source':str(source.resolve()),'output':str(Path(target).resolve()),
            'scope':'geometry only; inherits reviewed source identity and pose'}
    return report


def foreground(image, alpha=False):
    image=image.convert('RGBA')
    if alpha:
        return image.getchannel('A').point(lambda a:255 if a>=16 else 0)
    rgb=image.convert('RGB');w,h=rgb.size
    corners=[rgb.getpixel(p) for p in ((0,0),(w-1,0),(0,h-1),(w-1,h-1))]
    bg=tuple(round(median(p[c] for p in corners)) for c in range(3))
    channels=ImageChops.difference(rgb,Image.new('RGB',rgb.size,bg)).split()
    return ImageChops.lighter(ImageChops.lighter(channels[0],channels[1]),channels[2]).point(
        lambda v:255 if v>32 else 0)


def compare_pair(source, refined):
    """Same-coordinate coarse silhouette checks, independent of final crop sizes."""
    if source.size!=refined.size:
        return {'flags':['size_changed'],'source_size':list(source.size),'refined_size':list(refined.size)}
    factor=min(1,128/max(source.size))
    size=tuple(max(1,round(v*factor)) for v in source.size)
    masks=[main_component(foreground(im.resize(size,Image.Resampling.BILINEAR),alpha))
           for im,alpha in ((source,False),(refined,True))]
    boxes=[m.getbbox() for m in masks]
    if any(b is None for b in boxes):return {'flags':['empty_subject'],'boxes':boxes}
    a,b=boxes
    ratio=lambda v,w:v/max(w,1)
    shift=math.hypot((a[0]+a[2]-b[0]-b[2])/2,(a[1]+a[3]-b[1]-b[3])/2)/max(1,math.hypot(a[2]-a[0],a[3]-a[1]))
    intersection=sum(ImageStat.Stat(ImageChops.darker(*masks)).sum)
    union=sum(ImageStat.Stat(ImageChops.lighter(*masks)).sum)
    overlap=intersection/max(1,union)
    area=[sum(ImageStat.Stat(m).sum) for m in masks]
    area_ratio=ratio(area[1],area[0]);height_ratio=ratio(b[3]-b[1],a[3]-a[1])
    flags=[]
    if shift>.12:flags.append('position_change')
    if not .80<=height_ratio<=1.20:flags.append('height_change')
    if not .65<=area_ratio<=1.50:flags.append('silhouette_area_change')
    if overlap<.55:flags.append('low_silhouette_overlap')
    return {'flags':flags,'center_shift':round(shift,4),'height_ratio':round(height_ratio,4),
            'area_ratio':round(area_ratio,4),'silhouette_iou':round(overlap,4),
            'interpretation':'Review hints only; connected effects or low contrast may affect measurements'}


def refinement_checks(report, folder,render_pairs=False):
    """Save compact paired evidence at identical coordinates and list suspect source indices."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    entries=[]
    records=report.get('refinement',[])
    representatives={0,len(records)//2,len(records)-1}
    pairs=[]
    for order,item in enumerate(records):
        with Image.open(item['input']) as im:source=im.convert('RGBA')
        with Image.open(item['refined']) as im:refined=im.convert('RGBA')
        padding=item.get('padding',[0,0])
        unpadded=(source.width-padding[0],source.height-padding[1])
        if any(padding) and unpadded==refined.size:
            source=source.crop((0,0,*unpadded))
        metrics=compare_pair(source,refined)
        index=item['source_frame_index']
        entries.append({'source_index':index,**metrics,'source':item['input'],'refined':item['refined']})
        if render_pairs and (metrics['flags'] or order in representatives):
            # Remove the same background margins from both panels, never align the
            # subject independently: a shifted result must remain visibly shifted.
            if source.size!=refined.size:continue
            union=ImageChops.lighter(foreground(source),foreground(refined,True)).getbbox()
            if not union:continue
            a,b=source.crop(union),refined.crop(union)
            scale=min(1,260/max(a.size))
            size=tuple(max(1,round(v*scale)) for v in a.size)
            a,b=a.resize(size),b.resize(size)
            canvas=Image.new('RGB',(size[0]*2+12,size[1]+24),(100,100,100))
            from PIL import ImageDraw
            draw=ImageDraw.Draw(canvas)
            draw.text((2,2),f'{index}: source | refined',fill='white')
            for im,x in ((a,0),(b,size[0]+12)):
                panel=Image.new('RGBA',size,(110,110,110,255));panel.alpha_composite(im)
                canvas.paste(panel.convert('RGB'),(x,24))
            path=folder/f'pair-{index}.png';canvas.save(path);pairs.append(str(path.resolve()))
    return {'frames':entries,'suspect_indices':[e['source_index'] for e in entries if e['flags']],
            'representative_orders':sorted(representatives) if records else [],'pairs':pairs,
            'semantic_status':'requires_visual_review'}
