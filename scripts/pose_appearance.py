"""Numerical source RGB/Alpha evidence, never synthesized review images."""
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np
from PIL import Image


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def extract(video,mask_folder,start,end,output):
    mask_folder=Path(mask_folder).resolve();metadata=mask_folder/'analysis.json'
    info=json.loads(metadata.read_text(encoding='utf-8'))
    if Path(info['video']).resolve()!=Path(video).resolve():raise ValueError('Analysis masks belong to another source')
    mapping={int(index):i for i,index in enumerate(info['source_indices'])}
    paths=[mask_folder/f'mask-{mapping[i]:04d}.png' for i in range(start,end+1)]
    masks=[];bounds=[]
    for path in paths:
        with Image.open(path) as image:mask=image.convert('L')
        if not mask.getbbox():raise ValueError('Empty subject mask: '+str(path))
        masks.append(mask);bounds.append(mask.getbbox())
    size=masks[0].size
    if any(mask.size!=size for mask in masks):raise ValueError('Mask dimensions changed')
    stream=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
        '-show_entries','stream=width,height','-of','json',str(video)]))['streams'][0]
    if size!=(stream['width'],stream['height']):raise ValueError('Appearance requires original-size masks')
    box=(min(b[0] for b in bounds),min(b[1] for b in bounds),max(b[2] for b in bounds),max(b[3] for b in bounds))
    command=['ffmpeg','-v','error','-i',str(video),'-vf',f'select=between(n\\,{start}\\,{end})',
        '-fps_mode','vfr','-f','rawvideo','-pix_fmt','rgb24','-']
    rows=[];frame_bytes=size[0]*size[1]*3
    with subprocess.Popen(command,stdout=subprocess.PIPE) as process:
        for mask in masks:
            raw=process.stdout.read(frame_bytes)
            if len(raw)!=frame_bytes:raise ValueError('Incomplete appearance source')
            rgb=Image.frombytes('RGB',size,raw)
            alpha=np.asarray(mask.crop(box).resize((48,64),Image.Resampling.BILINEAR),float)/255
            rgb=Image.composite(rgb,Image.new('RGB',size),mask)
            rgb=np.asarray(rgb.crop(box).resize((48,64),Image.Resampling.BILINEAR),float)/255
            rows.append(np.concatenate((rgb,alpha[...,None]),axis=-1))
        if process.stdout.read(1) or process.wait()!=0:raise ValueError('Appearance source interval differs')
    output=Path(output).resolve();np.savez_compressed(output,appearance=np.asarray(rows))
    contract={'path':str(output),'sha256':digest(output),'metadata':str(metadata),
        'metadata_sha256':digest(metadata),'masks':[{'path':str(p),'sha256':digest(p)} for p in paths],
        'start':start,'end':end,'video_sha256':digest(video),'common_crop':list(box),
        'descriptor':'original masked RGB and Alpha, shared crop 48x64, no per-frame alignment'}
    return np.asarray(rows),contract


def load(contract,video,start,end):
    if (contract['start'],contract['end'])!=(start,end) or contract['video_sha256']!=digest(video):
        raise ValueError('Appearance source contract changed')
    for item in [{'path':contract['path'],'sha256':contract['sha256']},
                 {'path':contract['metadata'],'sha256':contract['metadata_sha256']}]+contract['masks']:
        if digest(item['path'])!=item['sha256']:raise ValueError('Appearance evidence changed: '+item['path'])
    with np.load(contract['path'],allow_pickle=False) as data:return data['appearance']
