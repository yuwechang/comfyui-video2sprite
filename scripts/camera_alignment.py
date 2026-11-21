"""Register selected frames using stationary horizontal background boundaries."""
import argparse
import copy
import json
import math
from pathlib import Path
from statistics import median
from PIL import Image
from generate import save


def boundary(image, roi, expected=None, max_shift=32):
    if len(roi)!=4 or any(type(v) is not int for v in roi):
        raise ValueError('Background ROI must contain four integer source coordinates')
    x0,y0,x1,y1=roi
    if not (0<=x0<x1<=image.width and 0<=y0<y1<=image.height and x1-x0>=12 and y1-y0>=12):
        raise ValueError('Background ROI must be inside the image and at least 12 pixels per side')
    im=image.convert('L');pixels=im.load()
    profile=[median(pixels[x,y] for x in range(x0,x1,3)) for y in range(y0,y1)]
    gradients=[(sum(profile[i-3:i])/3-sum(profile[i:i+3])/3,i) for i in range(3,len(profile)-3)]
    noise=median(abs(v) for v,_ in gradients)
    candidates=[(abs(v),i,v) for v,i in gradients
                if expected is None or abs(y0+i-expected)<=max_shift]
    if not candidates:raise ValueError('No boundary inside the search range')
    strength,i,signed=max(candidates)
    return {'y':y0+i,'strength':strength,'prominence':strength/max(.1,noise),'polarity':1 if signed>=0 else -1}


def estimate(images, regions, max_shift=32, max_disagreement=3):
    if len(images)<2 or any(im.size!=images[0].size for im in images):
        raise ValueError('Need at least two same-size selected frames')
    if len(regions)<2:raise ValueError('Use at least two separate background ROIs')
    if not math.isfinite(max_shift) or max_shift<=0 or not math.isfinite(max_disagreement) or max_disagreement<0:
        raise ValueError('Invalid registration limits')
    for roi in regions:boundary(images[0],roi)
    for i,a in enumerate(regions):
        for b in regions[i+1:]:
            if max(a[0],b[0])<min(a[2],b[2]):
                raise ValueError('Tracking regions must use separate horizontal bands')
    reference=[boundary(images[0],roi) for roi in regions]
    tracks=[];shifts=[]
    for image in images:
        row=[boundary(image,roi,ref['y'],max_shift) for roi,ref in zip(regions,reference)]
        if any(t['strength']<3 or t['prominence']<3 or t['polarity']!=r['polarity']
               for t,r in zip(row,reference)):
            raise ValueError('Background boundary is weak or changed; inspect regions before aligning')
        corrections=[r['y']-t['y'] for t,r in zip(row,reference)]
        if max(corrections)-min(corrections)>max_disagreement:
            raise ValueError('Background regions disagree; vertical translation is not supported by this evidence')
        shift=round(median(corrections))
        if abs(shift)>=max_shift:
            raise ValueError('Boundary reached search limit; review before extending the range')
        tracks.append(row);shifts.append(shift)
    return shifts,tracks


def translate(images, shifts):
    top=max(0,-min(shifts));bottom=max(0,max(shifts));result=[]
    for im,dy in zip(images,shifts):
        canvas=Image.new('RGBA',(im.width,im.height+top+bottom))
        canvas.paste(im.convert('RGBA'),(0,top+dy));result.append(canvas)
    return result,[top,bottom]


def preview(images, durations, path):
    from spritesheet import gif_frame
    factor=min(1,840/images[0].width)
    frames=[gif_frame(im.resize((round(im.width*factor),round(im.height*factor)))) for im in images]
    frames[0].save(path,save_all=True,append_images=frames[1:],duration=durations,
                   loop=0,disposal=2,transparency=255,optimize=False)
    return str(Path(path).resolve())


def align(selection_file, regions_file, output, max_shift=32, max_disagreement=3):
    data=json.loads(Path(selection_file).read_text(encoding='utf-8-sig'))
    settings=json.loads(Path(regions_file).read_text(encoding='utf-8-sig'))
    if data.get('camera_alignment'):raise ValueError('Selection already has camera compensation')
    paths=data['selected_frames'];indices=data['sample_indices']
    if len(paths)!=len(indices) or indices!=sorted(set(indices)):
        raise ValueError('Selected frames must match ordered unique source indices')
    durations=data['frame_durations_ms']
    if len(durations)!=len(indices) or any(type(v) is not int or v<=0 for v in durations):
        raise ValueError('Provide a positive integer duration for every selected frame')
    images=[]
    for path in paths:
        with Image.open(path) as im:images.append(im.convert('RGBA'))
    shifts,tracks=estimate(images,settings['regions'],max_shift,max_disagreement)
    aligned,padding=translate(images,shifts)
    validation=[]
    for roi in settings.get('validation_regions',[]):
        values=[boundary(im,roi)['y'] for im in images]
        corrected=[y+dy for y,dy in zip(values,shifts)]
        before=max(values)-min(values);after=max(corrected)-min(corrected)
        if after>max_disagreement or after>before:
            raise ValueError('Independent background region does not confirm the correction')
        validation.append({'roi':roi,'before':values,'after':corrected,'range_before':before,'range_after':after})
    folder=Path(output).resolve()
    if folder.exists() and any(folder.iterdir()):raise ValueError('Use a new alignment output directory')
    folder.mkdir(parents=True,exist_ok=True)
    final_paths=[]
    for index,im in zip(indices,aligned):
        path=folder/f'aligned-{index}.png';im.save(path);final_paths.append(str(path))
    metadata={'method':'background_vertical_translation','reference_source_index':indices[0],
              'regions':settings['regions'],'dy':dict(zip(map(str,indices),shifts)),
              'tracks':tracks,'padding':padding,'reference_origin_aligned':[0,padding[0]],
              'validation':validation,'scope':'vertical translation only; no rotation, zoom or body anchoring'}
    save(folder/'alignment.json',metadata)
    result=copy.deepcopy(data)
    result.update(original_selected_frames=paths,selected_frames=final_paths,camera_alignment=metadata,
                  alignment_report=str(folder/'alignment.json'))
    from diagnostics import contact
    result['comparison']=contact(final_paths,folder/'aligned-overview.png',indices)
    baseline,_=translate(images,[0]*len(images))
    # Identical presentation canvas for the two previews; no per-frame recentering.
    original=[]
    for im in baseline:
        canvas=Image.new('RGBA',aligned[0].size);canvas.paste(im,(0,padding[0]));original.append(canvas)
    result['original_preview']=preview(original,durations,folder/'original.gif')
    result['corrected_preview']=preview(aligned,durations,folder/'corrected.gif')
    save(folder/'selection.json',result)
    return {**result,'selection_file':str(folder/'selection.json')}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('selection-file','regions-file','output'):parser.add_argument('--'+key,required=True)
    parser.add_argument('--max-shift',type=float,default=32)
    parser.add_argument('--max-disagreement',type=float,default=3)
    args=parser.parse_args()
    result=align(**vars(args))
    print(json.dumps({'selection_file':result['selection_file'],'dy':result['camera_alignment']['dy'],
                      'previews':[result['original_preview'],result['corrected_preview']]}))
