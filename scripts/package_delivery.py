"""Bundle explicit production assets, source frames and final animation into a ZIP.

Manifest JSON: {"video": "source.mp4",
"animations": {"with_effects": "with/animation.json", "without_effects": "without/animation.json"},
"files": {"input/reference.png": "character.png", "prompts/video.txt": "prompt.txt"}}.
Relative input paths resolve from the manifest directory. Animation output paths
resolve from its report directory. Optional production stages are listed in files
only when used. Source frames are numbered from zero; selection uses sample_indices.
"""
import argparse
import json
import os
import posixpath
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import zipfile
from PIL import Image, ImageSequence
from spritesheet import gif_frame


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def source_file(value, base):
    path = Path(value)
    path = path if path.is_absolute() else base / path
    if not path.is_file():
        raise ValueError(f'Missing asset: {path}')
    return path.resolve()


def archive_name(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('Archive names must be relative paths using forward slashes')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or ':' in value or not path.name:
        raise ValueError(f'Invalid archive path: {value}')
    return path.as_posix()


def selected_indices(report):
    indices = report['sample_indices']
    if (not isinstance(indices, list) or not indices or
            any(type(index) is not int or index < 0 for index in indices) or
            indices != sorted(set(indices))):
        raise ValueError('sample_indices must contain sorted unique nonnegative frame indices')
    if report['frames'] != len(indices):
        raise ValueError('Selected frame count does not match animation report')
    return indices


def animation_assets(animation, report, result_dir, frame_dir):
    """Use the same portable stage exporter for single and paired deliveries."""
    assets = {result_dir + '/spritesheet.png': source_file(report['sheet'], animation.parent),
              result_dir + '/preview.gif': source_file(report['preview'], animation.parent)}
    portable = {key: value for key, value in report.items()
                if key not in ('sheet', 'preview', 'input_sheet')}
    portable.update(sheet='spritesheet.png', preview='preview.gif')
    count = len(selected_indices(report))
    for field, directory in (('cropped_frames', 'cropped'), ('final_frames', 'final')):
        if field not in report:
            continue
        if len(report[field]) != count:
            raise ValueError(f'{field} count does not match selected frames')
        portable[field] = []
        for order, value in enumerate(report[field]):
            name = f'{frame_dir}/{directory}/{order:03d}.png'
            assets[name] = source_file(value, animation.parent)
            portable[field].append(posixpath.relpath(name, result_dir))
    if 'refinement' in report:
        if len(report['refinement']) != count:
            raise ValueError('Refinement count does not match selected frames')
        portable['refinement'] = []
        for order, record in enumerate(report['refinement']):
            item = dict(record)
            for field in ('input', 'refined'):
                name = f'{frame_dir}/refinement/{order:03d}/{field}.png'
                assets[name] = source_file(record[field], animation.parent)
                item[field] = posixpath.relpath(name, result_dir)
            for field in ('before_background_removal','background_job'):
                if field in record:
                    name=f'{frame_dir}/refinement/{order:03d}/{field}'+('.json' if field=='background_job' else '.png')
                    assets[name]=source_file(record[field],animation.parent)
                    item[field]=posixpath.relpath(name,result_dir)
            if 'correction_prompt' in record:
                name = f'{result_dir}/corrections/{order:03d}-prompt.txt'
                assets[name] = source_file(record['correction_prompt'], animation.parent)
                item['correction_prompt'] = posixpath.relpath(name, result_dir)
            portable['refinement'].append(item)
    if 'refinement_prompt' in report:
        name = result_dir + '/refine-prompt.txt'
        assets[name] = source_file(report['refinement_prompt'], animation.parent)
        portable['refinement_prompt'] = 'refine-prompt.txt'
    if 'background_profile' in report:
        name=result_dir+'/background-profile.json'
        assets[name]=source_file(report['background_profile'],animation.parent)
        portable['background_profile']='background-profile.json'
    return assets, portable


def verify_animation(report, base):
    """Check delivered PNG cells, GIF pixels and timeline against accepted final frames."""
    width, height = report['cell_width'], report['cell_height']
    durations = report['frame_durations_ms']
    if len(report['final_frames']) != report['frames']:
        raise ValueError('Final frame count does not match report')
    if 'refinement' in report and ([r['source_frame_index'] for r in report['refinement']]
                                   != report['sample_indices']):
        raise ValueError('Refinement source indices do not match selected frames')
    if len(durations) != report['frames'] or sum(durations) != report['duration_ms']:
        raise ValueError('Animation timing does not match report')
    if 'playback' in report:
        playback = report['playback']
        fps = playback['fps']
        if type(fps) is not int or fps <= 0 or 1000 % fps:
            raise ValueError('Invalid fixed playback FPS')
        beat = 1000 // fps
        expected = [index for index, duration in enumerate(durations) for _ in range(duration // beat)]
        if any(d % beat for d in durations) or playback['sequence'] != expected:
            raise ValueError('Fixed playback sequence differs from GIF timing')
    with Image.open(source_file(report['sheet'], base)) as sheet:
        if sheet.size != (width*report['columns'], height*report['rows']):
            raise ValueError('Spritesheet dimensions do not match report')
        frames = []
        for order, path in enumerate(report['final_frames']):
            with Image.open(source_file(path, base)) as image:
                frame = image.convert('RGBA')
            if frame.size != (width, height):
                raise ValueError('Final frame dimensions do not match report')
            x, y = order % report['columns']*width, order // report['columns']*height
            if sheet.convert('RGBA').crop((x,y,x+width,y+height)).tobytes() != frame.tobytes():
                raise ValueError('Spritesheet cell differs from final frame')
            frames.append(gif_frame(frame).convert('RGBA').convert('RGBa').tobytes())
    with Image.open(source_file(report['preview'], base)) as gif:
        if gif.size != (width,height) or gif.info.get('loop') != 0:
            raise ValueError('GIF dimensions or repeat setting do not match delivery')
        actual = [(f.convert('RGBA').convert('RGBa').tobytes(), f.info.get('duration',0))
                  for f in ImageSequence.Iterator(gif)]
    if sum(d for _,d in actual) != sum(durations):
        raise ValueError('GIF timing differs from report')
    order = 0
    remaining = durations[0]
    for pixels, duration in actual:
        while duration > 0:
            if order >= len(frames) or pixels != frames[order]:
                raise ValueError('GIF pixels or frame order differ from final frames')
            step = min(duration, remaining)
            if step <= 0:
                raise ValueError('Animation contains invalid duration')
            duration -= step
            remaining -= step
            if remaining == 0:
                order += 1
                if order < len(durations):
                    remaining = durations[order]


def package(manifest_path, output):
    manifest_path = Path(manifest_path).resolve()
    config = read_json(manifest_path)
    base = manifest_path.parent
    video = source_file(config['video'], base)
    paired = 'animations' in config
    if paired:
        if 'animation' in config or set(config['animations']) not in ({'clean'}, {'with_effects', 'without_effects'}):
            raise ValueError('animations must specify clean only, or with_effects and without_effects')
        entries = [(name, source_file(config['animations'][name], base),
                    'variants/' + name, 'frames/' + name)
                   for name in (('clean',) if set(config['animations']) == {'clean'}
                                else ('with_effects', 'without_effects'))]
    else:
        entries = [(None, source_file(config['animation'], base), 'result', 'frames')]
    video_name = 'video/source' + video.suffix.lower()
    assets, portable_reports, reports = {video_name: video}, {}, {}
    indices, first = None, None
    variant_summaries=[]
    for name, animation, result_dir, frame_dir in entries:
        report = read_json(animation)
        current = selected_indices(report)
        if indices is None:
            indices, first = current, report
        if paired:
            if report.get('effect_variant') != name:
                raise ValueError('Animation effect_variant does not match manifest label')
            required_fields=['final_frames','anchor_px','anchor_type','delivery_scale']
            required_fields+=(['background_profile'] if report.get('image_edit_performed') is False else ['refinement_prompt'])
            for field in required_fields:
                if field not in report:
                    raise ValueError(f'Paired delivery requires {field} in each animation')
            for field in ('sample_indices', 'frame_durations_ms', 'motion_type', 'frame_scale'):
                if field not in report or report[field] != first.get(field):
                    raise ValueError(f'Effect variants differ in {field}')
        if paired:
            verify_animation(report, animation.parent)
        stage_assets, portable = animation_assets(animation, report, result_dir, frame_dir)
        assets.update(stage_assets)
        portable_reports[result_dir + '/animation.json'] = portable
        reports[name] = result_dir + '/animation.json'
        variant_summaries.append({'name':name or 'single','frames':len(current),
            'sheet':result_dir+'/spritesheet.png','preview':result_dir+'/preview.gif',
            'final_frames':len(report.get('final_frames',[]))})
    reserved = {'manifest.json', *portable_reports}
    for name, value in config.get('files', {}).items():
        name = archive_name(name)
        if (name in assets or name in reserved or name.startswith('frames/') or
                name.startswith('variants/')):
            raise ValueError(f'Reserved or duplicate archive path: {name}')
        assets[name] = source_file(value, base)
    names = list(assets) + list(reserved)
    from job_contract import file_digest
    for role,item in config.get('required_materials',{}).items():
        name=archive_name(item['path'])
        if name not in assets or file_digest(assets[name])!=item['sha256']:
            raise ValueError('Required material missing or changed: '+role)
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError('Archive paths conflict on case-insensitive filesystems')
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Output already exists; choose a new ZIP filename')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='delivery-', dir=output.parent) as temporary:
        folder = Path(temporary)
        frames = folder / 'all'
        frames.mkdir()
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', str(video),
                        '-map', '0:v:0', '-fps_mode', 'passthrough', '-start_number', '0',
                        str(frames / 'frame_%06d.png')], check=True)
        paths = sorted(frames.glob('frame_*.png'))
        if not paths or max(indices) >= len(paths):
            raise ValueError('Video does not contain every selected frame')
        selected = []
        for order, index in enumerate(indices):
            name = f'frames/selected/{order:03d}_frame_{index:06d}.png'
            selected.append({'order': order, 'source_frame_index': index, 'path': name})
        inventory = {'video': video_name, 'files': list(assets),
                     'required_materials':config.get('required_materials',{}),
                     'all_frames': {'directory': 'frames/all', 'count': len(paths)},
                     'selected_frames': selected, 'frame_index_origin': 0,
                     'selected_frame_stage': 'original source frames before scaling and crop'}
        if paired:
            inventory.update(animations=reports, display_order=list(config['animations']) if set(config['animations']) == {'clean'} else ['with_effects', 'without_effects'])
        else:
            inventory['animation'] = reports[None]
        pending = folder / 'delivery.zip'
        with zipfile.ZipFile(pending, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            for name, source in assets.items():
                archive.write(source, name)
            for path in paths:
                archive.write(path, 'frames/all/' + path.name)
            for item in selected:
                archive.write(paths[item['source_frame_index']], item['path'])
            for name, portable in portable_reports.items():
                archive.writestr(name, json.dumps(portable, ensure_ascii=False, indent=2))
            archive.writestr('manifest.json', json.dumps(inventory, ensure_ascii=False, indent=2))
        with zipfile.ZipFile(pending) as archive:
            expected=set(assets)|set(reserved)|{'frames/all/'+p.name for p in paths}|{s['path'] for s in selected}
            names=archive.namelist()
            if len(names)!=len(expected) or set(names)!=expected:
                raise ValueError('ZIP inventory differs from registered assets and generated frames')
            broken = archive.testzip()
            if broken:
                raise ValueError(f'ZIP verification failed: {broken}')
            file_count = len(names)
        os.replace(pending, output)
    return {'zip': str(output), 'bytes': output.stat().st_size, 'files': file_count,
            'all_frames': len(paths), 'selected_frames': len(indices), 'verified': True,
            'verification':{'crc':'pass','inventory':'pass','variants':variant_summaries,
                'materials':sum(n.startswith('materials/') for n in names),
                'prompts':sum(n.endswith('.txt') for n in names),
                'required_material_roles':len(config.get('required_materials',{}))}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True,
                        help='JSON with video, animations (paired) or animation (single), and explicit files mapping')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(package(args.manifest, args.output), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
