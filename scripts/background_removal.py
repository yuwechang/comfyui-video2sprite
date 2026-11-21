"""Run a mask-only background workflow and enforce unchanged image geometry and RGB."""
import argparse
import json
from pathlib import Path
from PIL import Image
from process_image import process


def configure(output,url='http://127.0.0.1:8188',model='birefnet.safetensors',grow_mask=-1):
    from generate import request,save
    info=request(url,'/object_info/LoadBackgroundRemovalModel')
    field=info['LoadBackgroundRemovalModel']['input']['required']['bg_removal_name']
    available=field[0] if isinstance(field[0],list) else field[1]['options']
    if model not in available:raise ValueError('Background model is not installed: '+model)
    if type(grow_mask) is not int:raise ValueError('grow_mask must be an integer')
    template=Path(__file__).resolve().parents[1]/'assets/workflows/birefnet-alpha.json'
    workflow=json.loads(template.read_text(encoding='utf-8-sig'))
    workflow['1']['inputs']['bg_removal_name']=model
    workflow['24']['inputs']['expand']=grow_mask
    profile={'kind':'background','output_mode':'mask','url':url,'bindings':{'image_1':[{'node':'3','input':'image'}]},
             'output_node':'43','workflow':workflow}
    save(output,profile)
    return profile


def apply_mask(image,mask,output):
    """Apply an already processed white-foreground mask without erosion or resampling."""
    with Image.open(image) as original,Image.open(mask) as alpha:
        if original.size!=alpha.size:raise ValueError('Mask dimensions differ from source image')
        alpha=alpha.convert('L')
        low,high=alpha.getextrema()
        if low!=0 or high<128:raise ValueError('Mask is opaque or empty')
        result=original.convert('RGBA');result.putalpha(alpha)
        Path(output).parent.mkdir(parents=True,exist_ok=True);result.save(output)
    return str(Path(output).resolve())


def remove_background(profile,image,job):
    result=process(profile,image,None,job)
    config=json.loads(Path(profile).read_text(encoding='utf-8-sig'))
    if config.get('output_mode')=='mask':
        mask=result['file']
        result={**result,'mask':mask,'file':apply_mask(image,mask,Path(job)/'foreground.png')}
    with Image.open(image) as original,Image.open(result['file']) as output:
        if output.size!=original.size or 'A' not in output.getbands():
            raise ValueError('Background removal must preserve dimensions and output alpha')
        if original.convert('RGB').tobytes()!=output.convert('RGB').tobytes():
            raise ValueError('Background removal changed original RGB pixels')
        low,high=output.getchannel('A').getextrema()
        if low!=0 or high<128:
            raise ValueError('Background removal returned opaque or empty foreground')
        result={**result,'image':{'width':output.width,'height':output.height,'mode':output.mode,
                                 'alpha_extrema':[low,high]}}
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    bind=sub.add_parser('configure')
    bind.add_argument('--url',default='http://127.0.0.1:8188')
    bind.add_argument('--model',default='birefnet.safetensors')
    bind.add_argument('--grow-mask',type=int,default=-1)
    bind.add_argument('--output',default='.local/background-profile.json')
    run=sub.add_parser('run')
    for name in ('profile','image','job'):run.add_argument('--'+name,required=True)
    args=parser.parse_args()
    if args.command=='configure':
        configure(args.output,args.url,args.model,args.grow_mask)
        print(json.dumps({'profile':str(Path(args.output).resolve())}))
    else:print(json.dumps(remove_background(args.profile,args.image,args.job)))
