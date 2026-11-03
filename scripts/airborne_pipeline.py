"""Finish selected airborne frames or split a jump; no frontend plan dependency."""
import argparse
import json
from pathlib import Path
from PIL import Image
from airborne import align_selected, load_reference, create_reference
from spritesheet import extract_frames, prepare_frames, sample_indices, pack, finish, timings
from finish_animation import finish_prepared
from generate import save


def selected_finish(video, indices, reference, roi, job, output, image_profile, prompt_file,
                    seconds, scale=1, max_side=None, motion_type='return_to_start',
                    overrides=None, max_error=.25, alpha_cutoff=8, crop_margin=8, selected_frames=None):
    job = Path(job)
    frames = selected_frames if selected_frames is not None else extract_frames(video, indices, job)
    original_size = list(frames[0].size)
    aligned, alignment = align_selected(frames, indices, reference, roi, job, overrides, max_error)
    prepared = prepare_frames(aligned, indices, job, None, seconds, motion_type=='loop',
                              scale=scale, motion_type=motion_type, crop_margin=crop_margin)
    prepared.update(vertical_alignment=alignment, environment='air', original_video_frame_size=original_size)
    result = finish_prepared(prepared, image_profile, prompt_file, job, output, max_side, alpha_cutoff)
    first, second = result['first_crop'], result['refined_crop']
    point = alignment['reference_point_aligned']
    result['anchor_px'] = [((point[a]*scale-first['crop_box'][a])*first['scale']
                           -second['crop_box'][a])*second['scale'] for a in (0, 1)]
    result['anchor_type'] = 'waist'
    save(Path(output)/'animation.json', result)
    return result


def action(video, reference_profile, start, end, count, job, output, image_profile, prompt_file,
           seconds, motion_type='return_to_start', **options):
    if motion_type not in ('loop', 'return_to_start', 'hold_end_pose'):
        raise ValueError('Unknown motion type')
    reference, roi = load_reference(reference_profile)
    if options.get('scale') is None:
        options['scale'] = json.loads(Path(reference_profile).read_text(encoding='utf-8-sig'))['frame_scale']
    indices = sample_indices(start, end, count, motion_type=='loop')
    return selected_finish(video, indices, reference, roi, job, output, image_profile, prompt_file,
                           seconds, motion_type=motion_type, **options)


def jump(video, rise_start, apex, fall_end, roi, rise_count, fall_count, job, output,
         image_profile, prompt_file, rise_seconds, fall_seconds, **options):
    if not 0 <= rise_start < apex < fall_end:
        raise ValueError('Jump requires rise_start < apex < fall_end')
    rise = sample_indices(rise_start, apex, rise_count, False)
    fall = sample_indices(apex, fall_end, fall_count, False)
    indices = sorted(set(rise+fall))
    job, output = Path(job), Path(output)
    frames = extract_frames(video, indices, job)
    reference = frames[indices.index(apex)]
    # Reference profile remains in original video coordinates, before crop or translation.
    profile = create_reference(reference, roi, output/'airborne-reference', options.get('scale', 1))
    result = selected_finish(video, indices, reference.convert('RGB'), roi, job, job/'joint-result',
                             image_profile, prompt_file, rise_seconds+fall_seconds,
                             motion_type='hold_end_pose', selected_frames=frames, **options)
    results = {}
    for name, selected, seconds in (('rise', rise, rise_seconds), ('fall', fall, fall_seconds)):
        orders = [indices.index(i) for i in selected]
        images = []
        for order in orders:
            with Image.open(result['final_frames'][order]) as im:
                images.append(im.convert('RGBA'))
        sheet, columns, rows = pack(images)
        sheet_path = job/(name+'-sheet.png')
        sheet.save(sheet_path)
        report = dict(result)
        report.update(frames=len(selected), sample_indices=selected, requested_seconds=seconds,
                      duration_ms=sum(timings(seconds, len(selected))),
                      columns=columns, rows=rows, loop=False, motion_type='hold_end_pose',
                      shared_apex_source_index=apex, shared_crop_source_indices=indices)
        for field in ('cropped_frames', 'final_frames', 'refinement'):
            report[field] = [result[field][i] for i in orders]
        # Keep shared transform/crop metadata: both phases use the identical cut-point pixels.
        report['vertical_alignment'] = dict(result['vertical_alignment'])
        report['vertical_alignment']['matches'] = [result['vertical_alignment']['matches'][i] for i in orders]
        results[name] = finish(sheet_path, report, output/name)
    summary = {'rise': results['rise'], 'fall': results['fall'], 'airborne_reference': str(profile.resolve())}
    save(output/'jump.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    for name in ('action', 'jump'):
        cmd = sub.add_parser(name)
        cmd.add_argument('video')
        for key in ('job', 'output', 'image-profile', 'prompt-file'):
            cmd.add_argument('--'+key, required=True)
        cmd.add_argument('--scale', type=float, help='Override reference scale; jump defaults to 1')
        cmd.add_argument('--max-side', type=int)
        cmd.add_argument('--alpha-cutoff', type=int, default=8)
        cmd.add_argument('--crop-margin', type=int, default=8)
        cmd.add_argument('--max-match-error', type=float, default=.25)
        cmd.add_argument('--waist-overrides', help='JSON mapping selected source index to [x,y]')
        if name == 'action':
            cmd.add_argument('--reference-profile', required=True)
            cmd.add_argument('--start', type=int, required=True)
            cmd.add_argument('--end', type=int, required=True)
            cmd.add_argument('--count', type=int, default=8)
            cmd.add_argument('--seconds', type=float, required=True)
            cmd.add_argument('--motion-type', choices=('loop','return_to_start','hold_end_pose'), default='return_to_start')
        else:
            for key in ('rise-start', 'apex', 'fall-end'):
                cmd.add_argument('--'+key, type=int, required=True)
            cmd.add_argument('--waist-roi', nargs=4, type=int, required=True)
            cmd.add_argument('--rise-count', type=int, default=8)
            cmd.add_argument('--fall-count', type=int, default=8)
            cmd.add_argument('--rise-seconds', type=float, required=True)
            cmd.add_argument('--fall-seconds', type=float, required=True)
    args = vars(parser.parse_args())
    mode = args.pop('mode')
    args['max_error'] = args.pop('max_match_error')
    override_file = args.pop('waist_overrides')
    if mode == 'jump':
        args['roi'] = args.pop('waist_roi')
        if args['scale'] is None:
            args['scale'] = 1
    try:
        args['overrides'] = json.loads(Path(override_file).read_text(encoding='utf-8-sig')) if override_file else None
        result = {'action': action, 'jump': jump}[mode](**args)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({'error': str(exc), 'job': args['job']}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
