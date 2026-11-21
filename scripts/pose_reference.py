"""Record external pose-tool inputs before generation and import its actual output."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from PIL import Image


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def prepare(reference, prompt_file, job, previous=None):
    folder=Path(job).resolve()
    if folder.exists() and any(folder.iterdir()):
        raise ValueError('Use a new pose job; existing records are immutable')
    source=Path(reference).resolve(); prompt=Path(prompt_file).resolve()
    with Image.open(source) as image:image.verify()
    text=prompt.read_text(encoding='utf-8-sig')
    if not text.strip():raise ValueError('Pose prompt is empty')
    lineage=[]
    if previous:
        parent=load_manifest(previous)
        if digest(source)!=digest(parent['file']):
            raise ValueError('Revision reference must be the previous recorded output')
        lineage=parent['lineage']+[parent['record']]
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/('reference'+source.suffix.lower())
    shutil.copyfile(source,target)
    (folder/'prompt.txt').write_text(text,encoding='utf-8')
    request={'provider':'gpt_image','reference':str(target),'prompt_file':str(folder/'prompt.txt'),
             'reference_sha256':digest(target),'prompt_sha256':digest(folder/'prompt.txt'),
             'lineage':lineage}
    write(folder/'request.json',request)
    return request


def accept(job, image):
    folder=Path(job).resolve()
    if (folder/'manifest.json').exists():raise ValueError('Pose output already recorded; use a new job')
    request=json.loads((folder/'request.json').read_text(encoding='utf-8'))
    for key in ('reference','prompt'):
        path=request['reference' if key=='reference' else 'prompt_file']
        if digest(path)!=request[key+'_sha256']:raise ValueError('Recorded input changed')
    with Image.open(image) as im:im.verify()
    output=folder/('result'+Path(image).suffix.lower())
    shutil.copyfile(image,output)
    record={**request,'file':str(output),'sha256':digest(output)}
    write(folder/'manifest.json',record)
    write(folder/'stage-args.json',{'manifest':str(folder/'manifest.json')})
    return {'manifest':str(folder/'manifest.json'),'file':str(output),
            'stage_args':str(folder/'stage-args.json')}


def load_manifest(manifest):
    data=json.loads(Path(manifest).read_text(encoding='utf-8'))
    records=data.get('lineage',[])+[data]
    for record in records:
        for key,hash_key in (('reference','reference_sha256'),('prompt_file','prompt_sha256'),('file','sha256')):
            if digest(record[key])!=record[hash_key]:raise ValueError('Pose material changed: '+record[key])
    return {'file':data['file'],'record':{k:v for k,v in data.items() if k!='lineage'},
            'lineage':data.get('lineage',[]),'provider':data['provider']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare')
    for key in ('reference','prompt-file','job'):p.add_argument('--'+key,required=True)
    p.add_argument('--previous')
    a=sub.add_parser('accept');a.add_argument('--job',required=True);a.add_argument('--image',required=True)
    args=vars(parser.parse_args());command=args.pop('command')
    print(json.dumps((prepare if command=='prepare' else accept)(**args),ensure_ascii=False))


if __name__=='__main__':main()
