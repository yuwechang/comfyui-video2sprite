"""Make equal-canvas chat previews by padding accepted frames without resizing."""
import argparse
import html
import json
import math
from pathlib import Path
import re
from PIL import Image
from generate import save
from spritesheet import gif_frame
from package_delivery import verify_animation


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def character_entries(path):
    character=read(path)
    entries=[]
    for task in character['tasks']:
        if task['status']!='completed':
            raise ValueError('Display requires reviewed completed animations: '+task['id'])
        assets=task['artifacts']
        for key in ('animation','rise_animation','fall_animation'):
            if key in assets:
                suffix='' if key=='animation' else '-'+key.split('_')[0]
                entries.append({'id':task['id']+suffix,'label':task['id']+suffix,
                                'summary':assets[key],'source_video':assets.get('source_video')})
    return entries


def render(entries, output):
    output=Path(output).resolve()
    if not entries:
        raise ValueError('No animation previews to display')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use a new display output directory')
    groups=[];scales=[];identifiers=set()
    for entry in entries:
        identifier=entry['id']
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',identifier) or identifier in identifiers:
            raise ValueError('Display IDs must be unique safe identifiers')
        identifiers.add(identifier)
        path=Path(entry['summary']).resolve();summary=read(path)
        variants=summary.get('variants')
        if not variants or set(variants) not in ({'clean'},{'with_effects','without_effects'}):
            raise ValueError('Display summary must contain clean or an effect pair')
        ordered=['clean'] if 'clean' in variants else ['with_effects','without_effects']
        items=[]
        for name in ordered:
            report=dict(variants[name])
            # Resolve file fields against the report location for standalone data inputs.
            for key in ('sheet','preview'):
                value=Path(report[key]);report[key]=str(value if value.is_absolute() else path.parent/value)
            report['final_frames']=[str(Path(v) if Path(v).is_absolute() else path.parent/v)
                                    for v in report['final_frames']]
            verify_animation(report,path.parent)
            scale=report['delivery_scale'];scales.append(scale)
            anchor=report['anchor_px']
            if len(anchor)!=2 or not all(math.isfinite(v) for v in anchor):
                raise ValueError('Invalid display anchor')
            origin=[-round(v) for v in anchor]
            items.append((name,report,origin))
        left=min(p[0] for _,_,p in items);top=min(p[1] for _,_,p in items)
        right=max(p[0]+r['cell_width'] for _,r,p in items)
        bottom=max(p[1]+r['cell_height'] for _,r,p in items)
        groups.append((entry,items,(left,top,right,bottom)))
    if any(not math.isfinite(s) or s<=0 or not math.isclose(s,scales[0],rel_tol=1e-9) for s in scales):
        raise ValueError('Equal-scale display requires equal delivery_scale; padding cannot correct scaled content')
    width=max(b[2]-b[0] for _,_,b in groups)+16
    height=max(b[3]-b[1] for _,_,b in groups)+16
    if width*height>16_000_000:
        raise ValueError('Display canvas is too large; check anchor coordinates')
    output.mkdir(parents=True,exist_ok=True)
    records=[];markdown=['| Animation | Original video | Preview / with effects | Without effects |',
                         '| --- | --- | --- | --- |'];rows=[]
    for entry,items,box in groups:
        pictures=[];tags=[]
        for name,report,origin in items:
            offset=[8+(width-16-(box[2]-box[0]))//2+origin[0]-box[0],
                    8+(height-16-(box[3]-box[1]))//2+origin[1]-box[1]]
            frames=[]
            for source in report['final_frames']:
                with Image.open(source) as image:
                    indexed=gif_frame(image.convert('RGBA'))
                    canvas=Image.new('P',(width,height),255)
                    canvas.putpalette(indexed.getpalette())
                    canvas.paste(indexed,tuple(offset))
                    canvas.info['transparency']=255
                    frames.append(canvas)
            target=output/(entry['id']+'-'+name+'.gif')
            frames[0].save(target,save_all=True,append_images=frames[1:],
                duration=report['frame_durations_ms'],disposal=2,transparency=255,
                background=255,optimize=False,loop=0)
            records.append({'id':entry['id'],'variant':name,'gif':str(target),
                'source_preview':report['preview'],'offset':offset,
                'source_frames':report['final_frames'],'durations_ms':report['frame_durations_ms']})
            pictures.append(f'![{name}]({target.as_posix()})')
            tags.append('<figure><figcaption>'+html.escape(name)+'</figcaption><img src="'+
                        html.escape(target.name,quote=True)+'" alt="'+html.escape(name)+'"></figure>')
        label=str(entry.get('label',entry['id']))
        source=entry.get('source_video')
        if source and not Path(source).is_file():raise ValueError('Missing original video: '+str(source))
        video=f'![Original video]({Path(source).resolve().as_posix()})' if source else ''
        cells=pictures+['']*(2-len(pictures))
        markdown.append('| '+label.replace('|','\\|').replace('\n',' ')+' | '+video+' | '+' | '.join(cells)+' |')
        rows.append('<section><h2>'+html.escape(label)+'</h2><div class="pair">'+''.join(tags)+'</div></section>')
    page='''<!doctype html><html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Animation previews</title><style>
body{background:#181818;color:#eee;font:16px sans-serif;margin:24px}section{border-top:1px solid #444;padding:16px 0}
.pair{display:flex;gap:16px}figure{margin:0;flex:none}figcaption{margin-bottom:8px}
img{display:block;width:WIDTHpx;height:HEIGHTpx;max-width:none;border:1px solid #444}
</style>'''.replace('WIDTH',str(width)).replace('HEIGHT',str(height))+''.join(rows)+'</html>'
    (output/'index.html').write_text(page,encoding='utf-8')
    (output/'chat.md').write_text('\n'.join(markdown)+'\n',encoding='utf-8')
    result={'canvas_size':[width,height],'delivery_scale':scales[0],'previews':records,
            'chat':str(output/'chat.md'),'page':str(output/'index.html')}
    save(output/'display.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sources=parser.add_mutually_exclusive_group(required=True)
    sources.add_argument('--manifest',help='JSON containing an animations list of id/label/summary')
    sources.add_argument('--character-plan')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    try:
        if args.character_plan:
            entries=character_entries(args.character_plan)
        else:
            manifest=Path(args.manifest).resolve();entries=read(manifest)['animations']
            entries=[dict(e,summary=str((manifest.parent/e['summary']).resolve())) for e in entries]
        result=render(entries,args.output)
        print(json.dumps({k:v for k,v in result.items() if k!='previews'},ensure_ascii=False))
    except (ValueError,KeyError,OSError) as exc:
        parser.exit(1,str(exc)+'\n')


if __name__=='__main__':main()
