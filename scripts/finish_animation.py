"""Run sampling, packing, image-workflow background removal and final preview."""
import argparse
import json
import math
from pathlib import Path
from PIL import Image
from process_image import process
from spritesheet import prepare, finish


def finish_action(video, max_side, image_profile, prompt_file, job, output,
                  count, start, end, seconds, loop, tolerance=32, scale=1, motion_type=None):
    report = prepare(video, job, max_side, count, start, end, seconds, loop, tolerance, scale, motion_type)
    prompt = Path(prompt_file).read_text(encoding='utf-8')
    profile = json.loads(Path(image_profile).read_text(encoding='utf-8'))
    alignment = profile.get('input_alignment', {'width': 1, 'height': 1})
    source_width = report['columns'] * report['cell_width']
    source_height = report['rows'] * report['cell_height']
    sizes = []
    for dimension, size in (('width', source_width), ('height', source_height)):
        multiple = alignment[dimension]
        if type(multiple) is not int or multiple <= 0:
            raise ValueError('Image input alignment must be positive integers')
        sizes.append(math.ceil(size / multiple) * multiple)
    padded_size = tuple(sizes)
    image_input = Path(report['input_sheet'])
    padded = padded_size != (source_width, source_height)
    if padded:
        with Image.open(image_input) as source:
            canvas = Image.new('RGB', padded_size, tuple(report['background_rgb']))
            canvas.paste(source.convert('RGB'), (0, 0))
            image_input = Path(job) / 'image-input.png'
            canvas.save(image_input)
    processed = process(image_profile, image_input, prompt, Path(job) / 'image-job')
    processed_path = processed['file']
    if padded:
        with Image.open(processed_path) as image:
            if image.size != padded_size:
                raise ValueError(f'Image workflow changed padded dimensions to {image.size}')
            image = image.crop((0, 0, source_width, source_height))
            processed_path = Path(job) / 'removed-background.png'
            image.save(processed_path)
    report['image_input_padding'] = [padded_size[0] - source_width, padded_size[1] - source_height]
    return finish(processed_path, report, output)


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
    parser.add_argument('--count', type=int, default=8)
    parser.add_argument('--start', type=int)
    parser.add_argument('--end', type=int)
    parser.add_argument('--motion-type', choices=('continuous','paused','once'))
    parser.add_argument('--seconds', type=float, required=True)
    parser.add_argument('--loop', action='store_true')
    args = parser.parse_args()
    try:
        result = finish_action(args.video, args.max_side, args.image_profile, args.prompt_file,
                               args.job, args.output, args.count, args.start, args.end,
                               args.seconds, args.loop, args.background_tolerance, args.scale, args.motion_type)
        print(json.dumps({key: result[key] for key in
                          ('frames', 'cell_width', 'cell_height', 'columns', 'rows', 'sheet', 'preview', 'verified')},
                         ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc), 'job': args.job}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
