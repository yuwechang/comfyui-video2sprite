"""Persist compact inspection artifacts without changing production geometry."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps
from generate import save


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Explicitly requested contact image from existing files; no selection or review changes.')
    parser.add_argument('--paths',nargs='+',required=True)
    parser.add_argument('--labels',nargs='+')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    if args.labels and len(args.labels)!=len(args.paths):parser.error('One label per input image required')
    if Path(args.output).exists():parser.error('Use a new diagnostic output path')
    result=contact(args.paths,args.output,args.labels)
    print(json.dumps({'image':str(Path(args.output).resolve()),'diagnostic_only':True}))


def contact(paths, output, labels=None, detail=False):
    if not paths:
        raise ValueError('Inspection needs images')
    columns = min(6, len(paths))
    canvas = Image.new('RGB', (columns*180, ((len(paths)+columns-1)//columns)*280), (100,100,100))
    draw = ImageDraw.Draw(canvas)
    sizes = []
    for path in paths:
        with Image.open(path) as source:
            sizes.append(source.size)
    common_scale = min(174/max(w for w,h in sizes),250/max(h for w,h in sizes))
    for i, path in enumerate(paths):
        with Image.open(path) as source:
            image = source.convert('RGBA')
        if detail:
            box = image.getchannel('A').point(lambda a: 255 if a >= 8 else 0).getbbox()
            if box:
                image = image.crop(box)
        image = (ImageOps.contain(image, (174,250)) if detail else
                 image.resize((max(1,round(image.width*common_scale)),
                               max(1,round(image.height*common_scale))),Image.Resampling.LANCZOS))
        panel = Image.new('RGBA', image.size, (110,110,110,255))
        panel.alpha_composite(image)
        x,y = i%columns*180, i//columns*280
        canvas.paste(panel.convert('RGB'), (x,y+25))
        draw.text((x+3,y+5), ('detail ' if detail else '')+str(labels[i] if labels else i), fill='white')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)
    return str(output.resolve())


def inspect_result(result, folder):
    """Keep numeric results separate from semantic decisions; never fabricate pass."""
    folder = Path(folder)
    checks, pictures, playback, detail_pictures = {}, [], [], []
    if 'variants' in result:
        from package_delivery import verify_animation
        for name, report in result['variants'].items():
            verify_animation(report, folder)
            checks[name] = {'pixels_timing_and_loop': True, 'frames': report['frames'],
                            'cell_size': [report['cell_width'], report['cell_height']],
                            'anchor_px': report['anchor_px'], 'delivery_scale': report['delivery_scale']}
            pictures.append(report['sheet'])
            from review_metrics import refinement_checks
            comparison=refinement_checks(report,folder/(name+'-comparison'))
            checks[name]['refine_comparison']=comparison
            for order,entry in enumerate(comparison['frames']):
                if entry['flags'] or order in comparison['representative_orders']:
                    detail_pictures.extend((entry['source'],entry['refined']))
    elif isinstance(result.get('rise'),dict) and isinstance(result.get('fall'),dict):
        for phase in ('rise', 'fall'):
            part = inspect_result(result[phase], folder/phase)
            checks[phase] = part['checks']
            pictures.extend(part['pictures'])
            detail_pictures.extend(part.get('detail_pictures',[]))
            playback.extend(part.get('playback',[]))
    elif 'selected_frames' in result:
        pictures.extend(result['selected_frames'])
        checks = {'indices': result['sample_indices'], 'durations_ms': result.get('frame_durations_ms'),
                  'source_bounds':result.get('source_checks'),
                  'sampling':result.get('sampling'),
                  'review_focus':['action coverage','key extension poses','actual effects','start/end connection']}
        if result.get('camera_alignment'):
            checks['camera_alignment']=result['camera_alignment']
    elif 'cropped_frames' in result:
        pictures.extend(result['cropped_frames'])
        checks = {'indices': result['sample_indices'], 'durations_ms': result['frame_durations_ms']}
    elif any(k in result for k in ('file','standing','prepared','overview')):
        path = next(result[k] for k in ('file','standing','prepared','overview') if k in result)
        with Image.open(path) as image:
            alpha = image.getchannel('A') if 'A' in image.getbands() else None
            checks = {'size': list(image.size), 'mode': image.mode,
                      'alpha_extrema': list(alpha.getextrema()) if alpha else None}
        pictures.append(str(Path(path).resolve()))
    save(folder/'checks.json', checks)
    return {'checks': checks, 'pictures': pictures,'detail_pictures':detail_pictures,'playback':playback,
            'reading_order':'Read numeric checks, then existing files directly. Open originals only for specific doubts. No browser or derived review images required. Static inspection is not proof of continuous playback.',
            'checks_file': str((folder/'checks.json').resolve())}


if __name__ == '__main__':
    main()
