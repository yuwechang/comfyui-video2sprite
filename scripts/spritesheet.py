"""Sample a selected video interval, pack fixed cells, and preview the final sheet."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import tempfile
from statistics import median
from PIL import Image, ImageChops


def sample_indices(start, end, count, loop):
    if start < 0 or count < 2 or end - start + 1 < count:
        raise ValueError('Sampling interval must contain at least count frames')
    span = end - start + (1 if loop else 0)
    return [start + round(i * span / (count if loop else count - 1)) for i in range(count)]


def pack(frames, background=None):
    size = frames[0].size
    if any(frame.size != size for frame in frames):
        raise ValueError('All cell sizes must match')
    count = len(frames)
    columns = count if count <= 6 else math.ceil(count / 2) if count <= 12 else 6
    rows = math.ceil(count / columns)
    fill = tuple(background) + (255,) if background is not None else (0, 0, 0, 0)
    sheet = Image.new('RGBA', (columns * size[0], rows * size[1]), fill)
    for i, frame in enumerate(frames):
        sheet.paste(frame, ((i % columns) * size[0], (i // columns) * size[1]))
    return sheet, columns, rows


def timings(seconds, count):
    durations = [round((i + 1) * seconds * 100 / count) * 10 -
                 round(i * seconds * 100 / count) * 10 for i in range(count)]
    if min(durations) < 10:
        raise ValueError('GIF timing requires at least 10 ms per frame')
    return durations


def gif_frame(frame):
    transparent = frame.getchannel('A').point(lambda alpha: 255 if alpha < 128 else 0)
    rgb = frame.convert('RGB')
    rgb.paste((0, 0, 0), mask=transparent)
    indexed = rgb.quantize(colors=255, dither=Image.Dither.NONE)
    indexed.putpalette(indexed.getpalette()[:765] + [0, 0, 0])
    indexed.paste(255, mask=transparent)
    indexed.info['transparency'] = 255
    return indexed


def content_bbox(frame, background, tolerance=32):
    if not 0 <= tolerance < 255:
        raise ValueError('Background tolerance must be between 0 and 254')
    rgb = frame.convert('RGB')
    diff = ImageChops.difference(rgb, Image.new('RGB', rgb.size, tuple(background)))
    r, g, b = diff.split()
    difference = ImageChops.lighter(ImageChops.lighter(r, g), b)
    mask = difference.point(lambda value: 255 if value > tolerance else 0)
    if frame.mode == 'RGBA':
        mask = ImageChops.multiply(mask, frame.getchannel('A').point(lambda a: 255 if a >= 16 else 0))
    bbox = mask.getbbox()
    if bbox is None:
        raise ValueError('Selected frame has no foreground distinct from background')
    return bbox


def common_crop(boxes, video_width):
    if not boxes or video_width <= 0:
        raise ValueError('Need foreground boxes and a positive video width')
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[2] for box in boxes)
    bottom = max(box[3] for box in boxes)
    centre = video_width / 2
    radius = max(centre - left, right - centre)
    return [math.floor(centre - radius), top, math.ceil(centre + radius), bottom]


def frame_background(frame, tolerance):
    rgb = frame.convert('RGB')
    samples = []
    for i in range(16):
        x = round(i * (rgb.width - 1) / 15)
        y = round(i * (rgb.height - 1) / 15)
        samples.extend((rgb.getpixel((x, 0)), rgb.getpixel((x, rgb.height - 1)),
                        rgb.getpixel((0, y)), rgb.getpixel((rgb.width - 1, y))))
    colour = tuple(round(median(pixel[c] for pixel in samples)) for c in range(3))
    matching = sum(max(abs(pixel[c] - colour[c]) for c in range(3)) <= tolerance for pixel in samples)
    if matching < len(samples) * .6:
        raise ValueError('Cannot infer a simple background from the selected frame border')
    return list(colour)


def crop_frames(frames, max_side=None, tolerance=32):
    if not frames:
        raise ValueError('No selected frames')
    if max_side is not None and max_side < 2:
        raise ValueError('Target maximum side must be at least 2 pixels')
    source_size = frames[0].size
    if any(frame.size != source_size for frame in frames):
        raise ValueError('Selected frames have different dimensions')
    backgrounds = [frame_background(frame, tolerance) for frame in frames]
    boxes = [content_bbox(frame, colour, tolerance) for frame, colour in zip(frames, backgrounds)]
    rect = common_crop(boxes, source_size[0])
    left, top, right, bottom = rect
    width, height = right - left, bottom - top
    scale = min(1, max_side / width, (max_side - 1) / height) if max_side is not None else 1
    content_size = (max(1, math.floor(width * scale + 1e-9)),
                    max(1, math.floor(height * scale + 1e-9)))
    cropped = []
    for frame, colour in zip(frames, backgrounds):
        content = frame.crop(rect).convert('RGBA')
        if content.size != content_size:
            content = content.resize(content_size, Image.Resampling.LANCZOS)
        cell = Image.new('RGBA', (content_size[0], content_size[1] + 1), tuple(colour) + (255,))
        cell.paste(content, (0, 0))
        cropped.append(cell)
    return cropped, {'source_size': list(source_size), 'source_content_boxes': [list(box) for box in boxes],
                     'crop_box': rect, 'centre_x': source_size[0] / 2, 'background_rgb': backgrounds[0],
                     'frame_backgrounds': backgrounds,
                     'background_tolerance': tolerance, 'bottom_padding': 1, 'scale': scale,
                     'target_max_side': max_side, 'scaled_content_size': list(content_size)}


def scale_frames(frames, scale):
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('Frame scale must be finite and positive')
    size = frames[0].size
    if any(frame.size != size for frame in frames):
        raise ValueError('Selected frames have different dimensions')
    target = tuple(max(1, round(value*scale)) for value in size)
    return [frame.resize(target, Image.Resampling.LANCZOS) if target != size else frame.copy()
            for frame in frames]


def prepare(video, output, max_side, count, start, end, seconds, loop, tolerance=32, scale=1, motion_type=None):
    if seconds <= 0:
        raise ValueError('Duration must be positive')
    timings(seconds, count)
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    automatic = None
    if motion_type is not None:
        loop = motion_type == 'continuous'
    if start is None and end is None:
        if motion_type is None:
            raise ValueError('Provide a motion type for automatic selection, or both start and end')
        from select_segment import select
        automatic = select(video, motion_type, count)
        (folder/'auto-segment.json').write_text(json.dumps(automatic,indent=2),encoding='utf-8')
        if automatic['status'] != 'selected':
            raise ValueError('No clear automatic interval; inspect auto-segment.json and set start/end')
        start,end = automatic['start'],automatic['end']
    elif start is None or end is None:
        raise ValueError('Manual selection requires both start and end')
    indices = sample_indices(start, end, count, loop)
    selection = '+'.join(f'eq(n\\,{index})' for index in indices)
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', str(video),
                        '-vf', 'select=' + selection, '-fps_mode', 'vfr',
                        str(Path(tmp) / '%06d.png')], check=True)
        paths = sorted(Path(tmp).glob('*.png'))
        if len(paths) != count:
            raise ValueError('Video did not contain every requested frame')
        frames = []
        for path in paths:
            with Image.open(path) as source:
                frames.append(source.convert('RGBA'))
    original_size = list(frames[0].size)
    frames = scale_frames(frames, scale)
    frames, crop_info = crop_frames(frames, max_side, tolerance)
    sheet, columns, rows = pack(frames, crop_info['background_rgb'])
    target = folder / 'input-sheet.png'
    sheet.save(target)
    width, height = frames[0].size
    return {'frames': count, 'cell_width': width, 'cell_height': height,
            'columns': columns, 'rows': rows, 'order': 'left-to-right, top-to-bottom',
            'sample_indices': indices, 'duration_ms': sum(timings(seconds, count)),
            'requested_seconds': seconds, 'loop': loop, 'input_sheet': str(target.resolve()),
            'original_frame_size': original_size, 'frame_scale': scale,
            'motion_type': motion_type, 'automatic_selection': automatic, **crop_info}


def finish(processed_sheet, report, output):
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    width, height, columns = report['cell_width'], report['cell_height'], report['columns']
    with Image.open(processed_sheet) as source:
        if source.size != (width * columns, height * report['rows']):
            raise ValueError(f'Image workflow changed sheet dimensions to {source.size}')
        if 'A' not in source.getbands() or source.getchannel('A').getextrema()[0] == 255:
            raise ValueError('Image output does not contain transparent pixels')
        sheet = source.convert('RGBA')
    padding = report.get('bottom_padding', 0)
    if padding:
        for i in range(report['frames']):
            x, bottom = (i % columns) * width, (i // columns + 1) * height
            sheet.paste((0, 0, 0, 0), (x, bottom - padding, x + width, bottom))
    for i in range(report['frames'], columns * report['rows']):
        sheet.paste((0, 0, 0, 0), ((i % columns) * width, (i // columns) * height,
                                 (i % columns + 1) * width, (i // columns + 1) * height))
    frames = [sheet.crop(((i % columns) * width, (i // columns) * height,
                          (i % columns + 1) * width, (i // columns + 1) * height))
              for i in range(report['frames'])]
    for i, frame in enumerate(frames):
        low, high = frame.getchannel('A').getextrema()
        if low == 255 or high == 0:
            raise ValueError(f'Cell {i} is opaque or empty; inspect image result')
    sheet_path, gif_path = folder / 'spritesheet.png', folder / 'preview.gif'
    sheet.save(sheet_path)
    preview = [gif_frame(frame) for frame in frames]
    durations = timings(report['requested_seconds'], len(frames))
    preview[0].save(gif_path, save_all=True, append_images=preview[1:],
                    duration=durations, disposal=2, transparency=255,
                    background=255, optimize=False, loop=0)
    with Image.open(gif_path) as gif:
        actual_duration = 0
        for i in range(gif.n_frames):
            gif.seek(i)
            actual_duration += gif.info['duration']
            if gif.convert('RGBA').getchannel('A').getextrema()[0] != 0:
                raise ValueError('GIF frame has no transparent background')
        if actual_duration != sum(durations) or gif.size != (width, height):
            raise ValueError('GIF verification failed')
    result = {**report, 'sheet': str(sheet_path.resolve()), 'preview': str(gif_path.resolve()),
              'verified': {'dimensions': True, 'cell_alpha': True, 'gif_transparency': True,
                           'gif_duration_ms': actual_duration}}
    (folder / 'animation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video')
    parser.add_argument('--output', required=True)
    parser.add_argument('--max-side', type=int, help='Optional cap on the final cropped cell')
    parser.add_argument('--scale', type=float, default=1, help='Uniform frame scale before common crop')
    parser.add_argument('--background-tolerance', type=int, default=32)
    parser.add_argument('--count', type=int, default=8)
    parser.add_argument('--start', type=int)
    parser.add_argument('--end', type=int)
    parser.add_argument('--motion-type', choices=('continuous','paused','once'))
    parser.add_argument('--seconds', type=float, required=True)
    parser.add_argument('--loop', action='store_true')
    args = parser.parse_args()
    result = prepare(args.video, args.output, args.max_side, args.count, args.start, args.end,
                     args.seconds, args.loop, args.background_tolerance, args.scale, args.motion_type)
    (Path(args.output) / 'selection.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
