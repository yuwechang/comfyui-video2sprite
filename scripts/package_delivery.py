"""Bundle explicit production assets, source frames and final animation into a ZIP.

Manifest JSON: {"video": "source.mp4", "animation": "animation.json",
"files": {"input/reference.png": "character.png", "prompts/video.txt": "prompt.txt"}}.
Relative input paths resolve from the manifest directory. Animation output paths
resolve from its report directory. Optional production stages are listed in files
only when used. Source frames are numbered from zero; selection uses sample_indices.
"""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import zipfile


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


def package(manifest_path, output):
    manifest_path = Path(manifest_path).resolve()
    config = read_json(manifest_path)
    base = manifest_path.parent
    video = source_file(config['video'], base)
    animation = source_file(config['animation'], base)
    report = read_json(animation)
    indices = report['sample_indices']
    if (not isinstance(indices, list) or not indices or
            any(type(index) is not int or index < 0 for index in indices) or
            len(set(indices)) != len(indices)):
        raise ValueError('sample_indices must contain unique nonnegative frame indices')
    if report['frames'] != len(indices):
        raise ValueError('Selected frame count does not match animation report')
    # Report file paths are resolved relative to the report, not to a frontend layout.
    assets = {'video/source' + video.suffix.lower(): video,
              'result/spritesheet.png': source_file(report['sheet'], animation.parent),
              'result/preview.gif': source_file(report['preview'], animation.parent)}
    reserved = {'manifest.json', 'result/animation.json'}
    for name, value in config.get('files', {}).items():
        name = archive_name(name)
        if name in assets or name in reserved or name.startswith('frames/'):
            raise ValueError(f'Reserved or duplicate archive path: {name}')
        assets[name] = source_file(value, base)
    names = list(assets) + list(reserved)
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
        portable = {key: value for key, value in report.items()
                    if key not in ('sheet', 'preview', 'input_sheet')}
        portable.update(sheet='spritesheet.png', preview='preview.gif')
        inventory = {'video': next(iter(assets)), 'animation': 'result/animation.json',
                     'files': list(assets), 'all_frames': {'directory': 'frames/all', 'count': len(paths)},
                     'selected_frames': selected,
                     'frame_index_origin': 0,
                     'selected_frame_stage': 'original source frames before scaling and crop'}
        pending = folder / 'delivery.zip'
        with zipfile.ZipFile(pending, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            for name, source in assets.items():
                archive.write(source, name)
            for path in paths:
                archive.write(path, 'frames/all/' + path.name)
            for item in selected:
                archive.write(paths[item['source_frame_index']], item['path'])
            archive.writestr('result/animation.json', json.dumps(portable, ensure_ascii=False, indent=2))
            archive.writestr('manifest.json', json.dumps(inventory, ensure_ascii=False, indent=2))
        with zipfile.ZipFile(pending) as archive:
            broken = archive.testzip()
            if broken:
                raise ValueError(f'ZIP verification failed: {broken}')
            file_count = len(archive.namelist())
        os.replace(pending, output)
    return {'zip': str(output), 'bytes': output.stat().st_size, 'files': file_count,
            'all_frames': len(paths), 'selected_frames': len(indices), 'verified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True,
                        help='JSON with video, animation report and archive-path to source-path files mapping')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(package(args.manifest, args.output), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
