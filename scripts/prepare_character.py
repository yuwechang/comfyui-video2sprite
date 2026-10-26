"""Prepare a fixed-scale character canvas before video generation."""
import argparse
from collections import deque
import json
import math
from pathlib import Path
from statistics import median
from PIL import Image, ImageFilter, ImageChops, ImageDraw, ImageFont
from process_image import process
from generate import save


def pixel_values(image):
    modern = getattr(image, 'get_flattened_data', None)
    return modern() if modern else image.getdata()


def layout(side, multiple_x=32, multiple_y=32, expand_horizontal=0, expand_top=0):
    if min(side, multiple_x, multiple_y) <= 0:
        raise ValueError('Base side and alignment must be positive')
    if any(not isinstance(level, int) or level < 0 for level in (expand_horizontal, expand_top)):
        raise ValueError('Expansion levels must be nonnegative integers')
    bottom = math.ceil(side * .07)
    width = math.ceil((2 * side + 2 * expand_horizontal * side / 4) / multiple_x) * multiple_x
    height = math.ceil((1.5 * side + bottom + expand_top * side / 4) / multiple_y) * multiple_y
    left = (width - side) // 2
    top = height - bottom - side
    return {'side': side, 'width': width, 'height': height,
            'expand_horizontal': expand_horizontal, 'expand_top': expand_top,
            'box': [left, top, left + side, top + side],
            'margins': {'left': left, 'right': width - left - side,
                        'top': top, 'bottom': bottom}}


def generation_layout(target_side, source_side, multiple_x=32, multiple_y=32,
                      expand_horizontal=0, expand_top=0, max_pixels=1_000_000):
    if not math.isfinite(max_pixels) or max_pixels <= 0:
        raise ValueError('Maximum generation pixels must be positive')
    logical = layout(target_side, 1, 1, expand_horizontal, expand_top)
    ideal = max(target_side, source_side) / target_side
    scale = min(ideal, math.sqrt(max_pixels / (logical['width'] * logical['height'])))
    # Quantise the character frame once; alignment padding does not change its scale.
    side = max(1, math.floor(target_side * scale + 1e-9))
    scale = side / target_side
    raw_width = max(1, math.floor(logical['width'] * scale + 1e-9))
    raw_height = max(1, math.floor(logical['height'] * scale + 1e-9))
    width = math.ceil(raw_width / multiple_x) * multiple_x
    height = math.ceil(raw_height / multiple_y) * multiple_y
    bottom = math.ceil(logical['margins']['bottom'] * scale - 1e-9)
    left, top = (width-side)//2, height-bottom-side
    return {'side': side, 'target_side': target_side, 'source_side': source_side,
            'width': width, 'height': height, 'box': [left, top, left+side, top+side],
            'margins': {'left': left, 'right': width-left-side, 'top': top, 'bottom': bottom},
            'expand_horizontal': expand_horizontal, 'expand_top': expand_top,
            'generation_scale': scale, 'restore_scale': target_side/side,
            'max_pixels': max_pixels, 'unaligned_size': [raw_width, raw_height]}


def visible_mask(image):
    # Small alpha noise from image decoders is not part of the visible silhouette.
    return image.convert('RGBA').getchannel('A').point(lambda a: 255 if a >= 16 else 0)


def transparent_subject(image):
    alpha = image.convert('RGBA').getchannel('A')
    histogram = alpha.histogram()
    return sum(histogram[:16]) > image.width * image.height * .005 and visible_mask(image).getbbox() is not None


def background_scan(image, geometry, max_size, tolerance):
    original_width, original_height = image.size
    small = image.convert('RGB').copy()
    small.thumbnail((max_size, max_size), Image.Resampling.NEAREST)
    width, height = small.size
    pixels = list(pixel_values(small))
    edge = list(dict.fromkeys([x for x in range(width)] +
                             [(height - 1) * width + x for x in range(width)] +
                             [y * width for y in range(height)] +
                             [y * width + width - 1 for y in range(height)]))
    bg = tuple(round(median(pixels[i][c] for i in edge)) for c in range(3))
    compatible = bytearray(max(abs(pixel[c] - bg[c]) for c in range(3)) <= tolerance for pixel in pixels)
    reached = bytearray(width * height)
    queue = deque()
    for index in edge:
        if compatible[index]:
            reached[index] = 1
            queue.append(index)
    while queue:
        index = queue.popleft()
        x, y = index % width, index // width
        neighbours = []
        if x:
            neighbours.append(index - 1)
        if x + 1 < width:
            neighbours.append(index + 1)
        if y:
            neighbours.append(index - width)
        if y + 1 < height:
            neighbours.append(index + width)
        for neighbour in neighbours:
            if compatible[neighbour] and not reached[neighbour]:
                reached[neighbour] = 1
                queue.append(neighbour)
    x0, y0, x1, y1 = geometry['box']
    outside = errors = inside = content = 0
    for y in range(height):
        oy = (y + .5) * original_height / height
        for x in range(width):
            ox = (x + .5) * original_width / width
            if x0 <= ox < x1 and y0 <= oy < y1:
                inside += 1
                content += not reached[y * width + x]
            else:
                outside += 1
                errors += not reached[y * width + x]
    return {'background': list(bg), 'outside_error_fraction': errors / max(1, outside),
            'inside_content_fraction': content / max(1, inside), 'scan_size': list(small.size)}


def detect_prepared(image, geometry, tolerance=12):
    if image.size != (geometry['width'], geometry['height']):
        return {'prepared': False, 'reason': 'dimensions'}
    if image.convert('RGBA').getchannel('A').getextrema()[0] != 255:
        return {'prepared': False, 'reason': 'not_opaque_canvas'}
    scan = background_scan(image, geometry, 128, tolerance)
    error = scan['outside_error_fraction']
    if .002 <= error <= .02 or .005 <= scan['inside_content_fraction'] <= .02:
        scan = background_scan(image, geometry, max(image.size), tolerance)
    passed = scan['outside_error_fraction'] <= .005 and scan['inside_content_fraction'] >= .01
    return {'prepared': passed, 'reason': 'background_layout' if passed else 'content_layout', **scan}


def choose_background(subject):
    small = subject.copy()
    small.thumbnail((128, 128), Image.Resampling.NEAREST)
    mask = visible_mask(small)
    edge = ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(3)))
    points = [pixel[:3] for pixel, flag in zip(pixel_values(small), pixel_values(edge)) if flag]
    if not points:
        raise ValueError('Cannot sample character outline')
    # Median resists small bright/dark accessories; RGB brightness stays in display space.
    brightness = median((.2126*r + .7152*g + .0722*b) / 255 for r, g, b in points)
    # Neutral outlines use middle gray; predominantly dark/light outlines shift smoothly.
    offset = max(0, abs(brightness - .5) - .1) * (.25 / .4)
    gray = .5 + (offset if brightness < .5 else -offset)
    value = max(64, min(191, round(gray * 255)))
    return (value, value, value)


def flatten(subject, background):
    canvas = Image.new('RGBA', subject.size, tuple(background) + (255,))
    canvas.alpha_composite(subject)
    return canvas.convert('RGB')


def expand_canvas(canvas, source_geometry, target_geometry, background):
    scale = target_geometry['side'] / source_geometry['side']
    if scale != 1:
        canvas = canvas.resize((max(1, round(canvas.width*scale)), max(1, round(canvas.height*scale))),
                               Image.Resampling.LANCZOS)
    dx = target_geometry['box'][0] - round(source_geometry['box'][0]*scale)
    dy = target_geometry['box'][3] - round(source_geometry['box'][3]*scale)
    result = Image.new('RGB', (target_geometry['width'], target_geometry['height']), tuple(background))
    result.paste(canvas, (dx, dy))
    return result


def load_cutout(args):
    with Image.open(args.image) as source:
        image = source.convert('RGBA')
    if not transparent_subject(image):
        result = process(args.image_profile, args.image,
                         'Remove the background, and output a PNG image', Path(args.job) / 'extract')
        with Image.open(result['file']) as source:
            image = source.convert('RGBA')
    if not transparent_subject(image):
        raise ValueError('A transparent character is required')
    return image


def inset_box(size):
    width, height = size
    padding = math.ceil(min(size) * .03)
    if min(size) <= 2*padding:
        raise ValueError('Character canvas is too small for inset')
    return padding, [padding, padding, width-padding, height-padding]


def standing_anchor(image):
    mask = visible_mask(image)
    bbox = mask.getbbox()
    if bbox is None:
        raise ValueError('No visible standing character')
    band = max(1, math.ceil((bbox[3]-bbox[1])*.05))
    lower = mask.crop((0,bbox[3]-band,image.width,bbox[3])).getbbox()
    return [(lower[0]+lower[2])/2, bbox[3]]


def reference_with_inset(image):
    padding, box = inset_box(image.size)
    bbox = visible_mask(image).getbbox()
    if bbox is None:
        raise ValueError('No visible standing character')
    anchor = standing_anchor(image)
    radius = max(anchor[0]-bbox[0], bbox[2]-anchor[0])
    factor = min((box[2]-box[0]-2)/(2*radius), (box[3]-box[1])/(bbox[3]-bbox[1]))
    subject=image.crop(bbox)
    size=(max(1,math.floor(subject.width*factor)),max(1,math.floor(subject.height*factor)))
    scaled=subject.resize(size,Image.Resampling.LANCZOS) if size!=subject.size else subject
    ax=(anchor[0]-bbox[0])*size[0]/subject.width
    ay=size[1]
    dx,dy=round(image.width/2-ax),box[3]-size[1]
    result=Image.new('RGBA',image.size)
    result.paste(scaled,(dx,dy))
    return result, {'padding':padding,'inner_box':box,'factor':factor,
                    'source_bbox':list(bbox),'source_anchor':anchor,
                    'anchor':[ax+dx,ay+dy], 'offset':[dx,dy],
                    'placed_bbox':list(visible_mask(result).getbbox())}


def save_preview(image, output):
    actual = image.convert('RGBA').copy()
    actual.thumbnail((512,720), Image.Resampling.LANCZOS)
    width, height = actual.size
    gap, header = 24, 36
    preview = Image.new('RGBA', (width*2+gap,height+header), (255,255,255,255))
    # Preserve alpha in the left panel; the right panel alone is presentation artwork.
    preview.paste(actual, (0,header))
    review = flatten(actual, (128,128,128)).convert('RGBA')
    _, box = inset_box(image.size)
    sx, sy = width/image.width, height/image.height
    frame = [round(box[0]*sx),round(box[1]*sy),round(box[2]*sx)-1,round(box[3]*sy)-1]
    ImageDraw.Draw(review).rectangle(frame, outline=(255,190,0,255), width=2)
    preview.paste(review, (width+gap,header))
    try:
        font = ImageFont.truetype('msjh.ttc',18)
        labels = ('實際使用：透明 PNG','確認用：灰底與內距框')
    except OSError:
        font = ImageFont.load_default()
        labels = ('Actual: transparent PNG','Review: gray + inset')
    draw = ImageDraw.Draw(preview)
    for x,label in zip((8,width+gap+8),labels):
        draw.text((x,7), label, font=font, fill=(35,35,35,255))
    target = output / 'preview.png'
    preview.save(target)
    return str(target.resolve())


def standing_reference(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    image, alignment = reference_with_inset(load_cutout(args))
    target = output / 'standing.png'
    image.save(target)
    report = {'standing': str(target.resolve()), 'canvas_size': list(image.size),
              'scale_side': max(image.size), 'anchor': alignment['anchor'], 'alignment': alignment,
              'preview': save_preview(image, output)}
    save(output / 'standing.json', report)
    return report


def place_at_scale(image, geometry, scale_side, anchor=None):
    factor = geometry['side'] / scale_side
    anchor = anchor or standing_anchor(image)
    size = tuple(max(1,round(value*factor)) for value in image.size)
    scaled = image.resize(size,Image.Resampling.LANCZOS) if image.size!=size else image.copy()
    dx = round(geometry['width']/2-anchor[0]*size[0]/image.width)
    dy = round(geometry['box'][3]-anchor[1]*size[1]/image.height)
    bbox = visible_mask(scaled).getbbox()
    placed = [bbox[0]+dx,bbox[1]+dy,bbox[2]+dx,bbox[3]+dy]
    if min(placed[:2])<0 or placed[2]>geometry['width'] or placed[3]>geometry['height']:
        raise ValueError('Standing character exceeds performance canvas; increase padding')
    result = Image.new('RGBA',(geometry['width'],geometry['height']))
    result.paste(scaled,(dx,dy))
    return result, {'factor':factor,'scale_side':scale_side,'source_anchor':anchor,
                    'scaled_canvas_size':list(size),'offset':[dx,dy],'placed_bbox':placed,
                    'anchor':[anchor[0]*size[0]/image.width+dx,anchor[1]*size[1]/image.height+dy]}


def prepare(args):
    prior_path = getattr(args, 'preparation', None)
    if not prior_path:
        sidecar = Path(args.image).parent / 'preparation.json'
        if sidecar.exists():
            prior_path = sidecar
    prior = json.loads(Path(prior_path).read_text(encoding='utf-8')) if prior_path else None
    previous_geometry = prior['geometry'] if prior else None
    if previous_geometry and previous_geometry.get('target_side', previous_geometry['side']) != args.side:
        raise ValueError('Base side must match the previous preparation')
    levels = {}
    for name in ('expand_horizontal', 'expand_top'):
        value = getattr(args, name, None)
        levels[name] = value if value is not None else (previous_geometry or {}).get(name, 0)
    profile_path = getattr(args, 'video_profile', None)
    rules = json.loads(Path(profile_path).read_text(encoding='utf-8'))['generation'] if profile_path else {}
    multiple_x = rules.get('width_multiple', args.multiple_x)
    multiple_y = rules.get('height_multiple', args.multiple_y)
    max_pixels = rules.get('max_pixels', 1_000_000)
    output, job = Path(args.output), Path(args.job)
    output.mkdir(parents=True, exist_ok=True)
    job.mkdir(parents=True, exist_ok=True)
    with Image.open(args.image) as source:
        image = source.convert('RGBA')
    source_geometry = previous_geometry or layout(args.side, multiple_x, multiple_y, **levels)
    scan_geometry = source_geometry
    if prior and prior.get('placement'):
        box = prior['placement']['placed_bbox']
        base = source_geometry['box']
        scan_geometry = {**source_geometry, 'box': [min(base[0], box[0]), min(base[1], box[1]),
                                                  max(base[2], box[2]), max(base[3], box[3])]}
    detection = detect_prepared(image, scan_geometry)
    if not detection['prepared'] and not prior:
        source_geometry = layout(args.side, multiple_x, multiple_y)
        detection = detect_prepared(image, source_geometry)
    if prior and not detection['prepared']:
        raise ValueError('Image does not match the supplied preparation layout')
    standing_path = getattr(args, 'standing_reference', None)
    placement = None
    if detection['prepared']:
        source_side = source_geometry.get('source_side', source_geometry['side'])
        geometry = generation_layout(args.side, source_side, multiple_x, multiple_y,
                                     max_pixels=max_pixels, **levels)
        canvas = image.convert('RGB')
        background = tuple(detection['background'])
        canvas = expand_canvas(canvas, source_geometry, geometry, background)
        if prior and prior.get('placement'):
            placement = dict(prior['placement'])
            ratio = geometry['side'] / source_geometry['side']
            dx = geometry['box'][0] - round(source_geometry['box'][0]*ratio)
            dy = geometry['box'][3] - round(source_geometry['box'][3]*ratio)
            old = placement['placed_bbox']
            placement['placed_bbox'] = [math.floor(old[0]*ratio)+dx, math.floor(old[1]*ratio)+dy,
                                        math.ceil(old[2]*ratio)+dx, math.ceil(old[3]*ratio)+dy]
            placement['factor'] *= ratio
        if prior:
            standing_path = standing_path or prior.get('standing_reference')
    else:
        image = load_cutout(args)
        if standing_path:
            standing = json.loads(Path(standing_path).read_text(encoding='utf-8'))
            source_side = standing['scale_side']
            expected_size = standing['canvas_size']
            if list(image.size) != expected_size:
                raise ValueError('Standing image canvas does not match its reference')
        else:
            # A directly supplied standing image also uses its full canvas as scale reference.
            source_side = max(image.size)
        geometry = generation_layout(args.side, source_side, multiple_x, multiple_y,
                                     max_pixels=max_pixels, **levels)
        anchor = standing.get('anchor') if standing_path else None
        subject, placement = place_at_scale(image, geometry, source_side, anchor)
        background = choose_background(subject)
        canvas = flatten(subject, background)
    target = output / 'prepared.png'
    canvas.save(target)
    report = {'geometry': geometry, 'restore_scale': geometry['restore_scale'],
              'background_rgb': list(background), 'detection': detection, 'placement': placement,
              'standing_reference': str(Path(standing_path).resolve()) if standing_path else None,
              'prepared': str(target.resolve())}
    save(output / 'preparation.json', report)
    return {key: report[key] for key in ('geometry', 'restore_scale', 'background_rgb', 'prepared')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('standing', 'layout'), default='layout')
    parser.add_argument('--image')
    parser.add_argument('--side', type=int)
    parser.add_argument('--image-profile', default='.local/image-profile.json')
    parser.add_argument('--job')
    parser.add_argument('--output', required=True)
    parser.add_argument('--standing-reference')
    parser.add_argument('--multiple-x', type=int, default=32)
    parser.add_argument('--multiple-y', type=int, default=32)
    parser.add_argument('--expand-horizontal', type=int, help='Total extra S/4 levels on each side')
    parser.add_argument('--expand-top', type=int, help='Total extra S/4 levels above')
    parser.add_argument('--preparation', help='Previous frontend preparation.json for an existing canvas')
    parser.add_argument('--video-profile', default='.local/profile.json')
    args = parser.parse_args()
    if not args.image or not args.job:
        parser.error('--image and --job are required for standing/layout')
    if args.stage == 'layout' and not args.side:
        parser.error('--side is required for layout')
    try:
        action = {'standing': standing_reference, 'layout': prepare}[args.stage]
        print(json.dumps(action(args), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc), 'stage': args.stage}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
