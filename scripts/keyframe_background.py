"""Share one deterministic wall/floor plate across video reference images."""
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFilter


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def background_plate(image,mask):
    rgb=np.asarray(image.convert('RGB'));alpha=np.asarray(mask.convert('L'))
    width,height=image.size;edge=max(1,width//30)
    columns=np.r_[np.arange(edge),np.arange(width-edge,width)]
    rows=[]
    for y in range(height):
        samples=rgb[y,columns][alpha[y,columns]<128]
        if not len(samples):raise ValueError('No clean background margin at row '+str(y))
        rows.append(np.median(samples,axis=0))
    rows=np.asarray(rows)
    gradient=np.linalg.norm(np.diff(rows,axis=0),axis=-1)
    boundary=int(np.argmax(gradient))+1
    if not gradient.max():boundary=height
    wall=tuple(map(int,np.rint(np.median(rows[:boundary],axis=0))))
    floor=tuple(map(int,np.rint(np.median(rows[boundary:],axis=0)))) if boundary<height else wall
    plate=Image.new('RGB',image.size,wall)
    if boundary<height:plate.paste(floor,(0,boundary,width,height))
    return plate,{'boundary_y':boundary,'wall_rgb':list(wall),'floor_rgb':list(floor)}


def contact_shadow(mask):
    active=np.asarray(mask)>=128;ys,xs=np.nonzero(active)
    if not len(xs):raise ValueError('Empty subject mask')
    height=int(ys.max()-ys.min()+1);band=active[max(0,int(ys.max())-round(height*.12)):]
    columns=np.flatnonzero(band.any(axis=0));runs=[]
    for x in columns:
        if not runs or x>runs[-1][-1]+1:runs.append([int(x)])
        else:runs[-1].append(int(x))
    shadow=Image.new('L',mask.size);draw=ImageDraw.Draw(shadow)
    for run in runs:
        x0,x1=run[0],run[-1]+1;y=int(np.nonzero(active[:,x0:x1])[0].max())
        radius=max(2,(x1-x0)*.12)
        draw.ellipse((x0,y-radius,x1,y+radius),fill=40)
    return shadow.filter(ImageFilter.GaussianBlur(max(1,height*.004)))


def compose(images,masks,output,shadows=True):
    if not images or len(images)!=len(masks):raise ValueError('Each keyframe requires its own Alpha mask')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    loaded=[];loaded_masks=[]
    with Image.open(images[0]) as source:size=source.size
    for image_path,mask_path in zip(images,masks):
        with Image.open(image_path) as source:image=source.convert('RGB')
        with Image.open(mask_path) as source:mask=source.convert('L')
        if image.size!=mask.size:raise ValueError('Mask changed source dimensions')
        if abs(image.width/image.height/(size[0]/size[1])-1)>.01:
            raise ValueError('Keyframe aspect ratios differ; explicit layout alignment required')
        # Resize the entire source canvas, never fit each pose's bounding box.
        if image.size!=size:
            image=image.resize(size,Image.Resampling.LANCZOS)
            mask=mask.resize(size,Image.Resampling.LANCZOS)
        if not mask.point(lambda v:255 if v>=128 else 0).getbbox():raise ValueError('Empty subject mask')
        loaded.append(image);loaded_masks.append(mask)
    plate,geometry=background_plate(loaded[0],loaded_masks[0])
    plate_path=output/'background.png';plate.save(plate_path)
    results=[];boxes=[]
    for i,(image,mask) in enumerate(zip(loaded,loaded_masks)):
        base=plate.copy()
        if shadows:base=Image.composite(Image.new('RGB',size),base,contact_shadow(mask))
        result=Image.composite(image,base,mask);path=output/f'keyframe-{i+1}.png';result.save(path)
        results.append(str(path));boxes.append(list(mask.point(lambda v:255 if v>=128 else 0).getbbox()))
    return {'images':results,'background':str(plate_path),'canvas_size':list(size),
        'background_geometry':geometry,'subject_boxes':boxes,'contact_shadows':shadows,
        'placement':'whole-canvas resize only; no per-pose scale or reposition',
        'source_images':[str(Path(p).resolve()) for p in images],
        'source_masks':[str(Path(p).resolve()) for p in masks]}


def normalize(images,profile,job,output,contact_shadows=True):
    from process_image import process
    output=Path(output).resolve();record=output/'normalization.json'
    contract={'images':[digest(p) for p in images],'profile':digest(profile),
              'contact_shadows':contact_shadows,'algorithm':'shared-flat-wall-floor-v1'}
    if record.exists():
        result=json.loads(record.read_text(encoding='utf-8'))
        if result['contract']!=contract:raise ValueError('Background inputs changed; use new output/job directories')
        if any(digest(p)!=h for p,h in result['output_hashes'].items()):raise ValueError('Normalized keyframe changed')
        return result
    masks=[]
    for i,image in enumerate(images):
        result=process(profile,image,None,Path(job)/f'alpha-{i+1}')
        masks.append(result['file'])
    result=compose(images,masks,output,contact_shadows)
    result.update(contract=contract,profile=str(Path(profile).resolve()),report_file=str(record))
    result['output_hashes']={p:digest(p) for p in result['images']+[result['background']]}
    record.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images',nargs='+',required=True)
    for name in ('profile','job','output'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--no-contact-shadows',action='store_true')
    args=parser.parse_args()
    result=normalize(args.images,args.profile,args.job,args.output,not args.no_contact_shadows)
    print(json.dumps({key:result[key] for key in ('images','background','background_geometry','canvas_size','report_file')}))
