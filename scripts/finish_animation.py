"""Sample, refine each cropped frame, crop transparent results and pack previews."""
import argparse
import json
import math
from pathlib import Path
from PIL import Image
from process_image import process
from spritesheet import prepare, finish, common_crop, pack, scale_frames
from generate import save


def finish_action(video, max_side, image_profile, prompt_file, job, output,
                  count, start, end, seconds, loop, tolerance=32, scale=1, motion_type=None,
                  alpha_cutoff=8):
    validate_alpha_cutoff(alpha_cutoff)
    # The optional size cap belongs to the final transparent crop, not the input.
    report = prepare(video, job, None, count, start, end, seconds, loop, tolerance, scale, motion_type)
    return finish_prepared(report, image_profile, prompt_file, job, output, max_side, alpha_cutoff)


def finish_prepared(report, image_profile, prompt_file, job, output, max_side=None, alpha_cutoff=8):
    """Refine only explicitly prepared selected frames; independent of their source pipeline."""
    validate_alpha_cutoff(alpha_cutoff)
    prompt = Path(prompt_file).read_text(encoding='utf-8')
    profile = json.loads(Path(image_profile).read_text(encoding='utf-8'))
    alignment = profile.get('input_alignment', {'width': 1, 'height': 1})
    multiples = [alignment[dimension] for dimension in ('width', 'height')]
    if any(type(value) is not int or value <= 0 for value in multiples):
        raise ValueError('Image input alignment must be positive integers')
    refined, records = [], []
    for i, path in enumerate(report['cropped_frames']):
        frame_job = Path(job) / 'refine' / f'{i:03d}'
        frame_job.mkdir(parents=True, exist_ok=True)
        with Image.open(path) as source:
            size = source.size
            padded_size = tuple(math.ceil(v / m) * m for v, m in zip(size, multiples))
            canvas = Image.new('RGB', padded_size, tuple(report['frame_backgrounds'][i]))
            canvas.paste(source.convert('RGB'), (0, 0))
            image_input = frame_job / 'input.png'
            canvas.save(image_input)
        processed = process(image_profile, image_input, prompt, frame_job / 'image-job')
        with Image.open(processed['file']) as source:
            if source.size != padded_size:
                raise ValueError(f'Frame {i}: image workflow changed dimensions to {source.size}')
            if 'A' not in source.getbands():
                raise ValueError(f'Frame {i}: image output has no alpha channel')
            frame = source.convert('RGBA').crop((0, 0, *size))
        low, high = frame.getchannel('A').getextrema()
        if low != 0 or high < 128:
            raise ValueError(f'Frame {i}: image output lacks transparent background or visible content')
        target = frame_job / 'refined.png'
        frame.save(target)
        refined.append(frame)
        records.append({'source_frame_index': report['sample_indices'][i],
                        'input': str(image_input.resolve()), 'refined': str(target.resolve()),
                        'padding': [padded_size[0]-size[0], padded_size[1]-size[1]]})
    frames, crop = crop_refined(refined, max_side, alpha_cutoff)
    final_paths = []
    for i, frame in enumerate(frames):
        target = Path(job) / 'final-frames' / f'{i:03d}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.save(target)
        final_paths.append(str(target.resolve()))
    sheet, columns, rows = pack(frames)
    target = Path(job) / 'refined-sheet.png'
    sheet.save(target)
    first_crop = {key: report[key] for key in
                  ('crop_box', 'source_size', 'source_content_boxes', 'bottom_padding')}
    first_crop['scale'] = report.get('scale', 1)
    report.update({'first_crop': first_crop,
                   'refinement': records, 'final_frames': final_paths,
                   'refined_crop': crop, 'cell_width': frames[0].width,
                   'cell_height': frames[0].height, 'columns': columns, 'rows': rows,
                   'bottom_padding': 1, 'target_max_side': max_side})
    save(Path(job) / 'selection.json', report)
    return finish(target, report, output)


def validate_alpha_cutoff(cutoff):
    if type(cutoff) is not int or not 0 <= cutoff <= 255:
        raise ValueError('Alpha cutoff must be an integer from 0 to 255')


def clean_alpha(frame, cutoff):
    validate_alpha_cutoff(cutoff)
    if 'A' not in frame.getbands():
        raise ValueError('Refined frame has no alpha channel')
    result = frame.convert('RGBA')
    result.putalpha(result.getchannel('A').point(lambda value: 0 if value < cutoff else value))
    return result


def crop_refined(frames, max_side=None, alpha_cutoff=8):
    validate_alpha_cutoff(alpha_cutoff)
    if not frames or any(frame.size != frames[0].size for frame in frames):
        raise ValueError('Refined frames must have matching dimensions')
    if max_side is not None and max_side < 2:
        raise ValueError('Target maximum side must be at least 2 pixels')
    frames = [clean_alpha(frame, alpha_cutoff) for frame in frames]
    boxes = [frame.getchannel('A').getbbox() for frame in frames]
    if any(box is None for box in boxes):
        raise ValueError('Refined frame is empty')
    rect = common_crop(boxes, frames[0].width)
    cropped = [frame.crop(rect) for frame in frames]
    width, height = cropped[0].size
    factor = min(1, max_side / width, (max_side-1) / height) if max_side is not None else 1
    cropped = scale_frames(cropped, factor)
    # Rounding must not exceed an explicit final size cap.
    if max_side is not None and (cropped[0].width > max_side or cropped[0].height >= max_side):
        size = (min(cropped[0].width, max_side), min(cropped[0].height, max_side-1))
        cropped = [frame.resize(size, Image.Resampling.LANCZOS) for frame in cropped]
    # Resampling can create tiny alpha values again; enforce the same rule in delivery.
    cropped = [clean_alpha(frame, alpha_cutoff) for frame in cropped]
    result = []
    for frame in cropped:
        cell = Image.new('RGBA', (frame.width, frame.height+1))
        cell.paste(frame, (0, 0))
        result.append(cell)
    return result, {'source_size': list(frames[0].size), 'alpha_boxes': [list(b) for b in boxes],
                    'crop_box': rect, 'scale': factor, 'bottom_padding': 1,
                    'alpha_cutoff': alpha_cutoff}



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video')
    parser.add_argument('--image-profile', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--job', required=True)
    parser.add_argument('--prompt-file', required=True)
    parser.add_argument('--max-side', type=int, help='Optional cap on the final cropped cell')
    parser.add_argument('--scale', type=float, default=1, help='Uniform frame scale before common crop')
    parser.add_argument('--background-tolerance', type=int, default=32)
    parser.add_argument('--alpha-cutoff', type=int, default=8,
                        help='Clear alpha below this value before final crop (0 disables; default 8)')
    parser.add_argument('--count', type=int, default=8)
    parser.add_argument('--start', type=int)
    parser.add_argument('--end', type=int)
    parser.add_argument('--motion-type', choices=('loop','return_to_start','hold_end_pose'))
    parser.add_argument('--seconds', type=float, required=True)
    parser.add_argument('--loop', action='store_true',
                        help='Use loop sampling for manual intervals without --motion-type; GIF always repeats')
    args = parser.parse_args()
    try:
        result = finish_action(args.video, args.max_side, args.image_profile, args.prompt_file,
                               args.job, args.output, args.count, args.start, args.end,
                               args.seconds, args.loop, args.background_tolerance, args.scale,
                               args.motion_type, args.alpha_cutoff)
        print(json.dumps({key: result[key] for key in
                          ('frames', 'cell_width', 'cell_height', 'columns', 'rows', 'sheet', 'preview', 'verified')},
                         ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc), 'job': args.job}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
