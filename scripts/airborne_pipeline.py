"""Finish selected airborne frames or split a jump; no frontend plan dependency."""
import argparse
import json
import hashlib
from pathlib import Path
from PIL import Image
from airborne import align_selected, load_reference, create_reference
from spritesheet import extract_frames, prepare_frames, sample_indices, pack, finish, timings
from finish_animation import finish_prepared, finish_prepared_variants, variant_summary
from generate import save
from frame_sampling import sample_video
from job_contract import guard_inputs


def selected_finish(video, indices, reference, roi, job, output, image_profile, prompt_file,
                    seconds, scale=1, max_side=None, motion_type='return_to_start',
                    overrides=None, max_error=.25, alpha_cutoff=8, crop_margin=8, selected_frames=None,
                    sampling=None, remove_effects_prompt_file=None,background_profile=None,refine_required=True):
    guard_inputs(job, {'video': video, 'profile': image_profile, 'prompt': prompt_file,
                       'remove': remove_effects_prompt_file,'background_profile':background_profile},
                 dict(indices=indices, reference=hashlib.sha256(reference.tobytes()).hexdigest(),
                      roi=roi, seconds=seconds, scale=scale, motion_type=motion_type,
                      overrides=overrides, max_error=max_error, crop_margin=crop_margin, sampling=sampling,
                      refine_required=refine_required))
    job = Path(job)
    frames = selected_frames if selected_frames is not None else extract_frames(video, indices, job)
    original_size = list(frames[0].size)
    aligned, alignment = align_selected(frames, indices, reference, roi, job, overrides, max_error)
    prepared = prepare_frames(aligned, indices, job, None, seconds, motion_type=='loop',
                              scale=scale, motion_type=motion_type, crop_margin=crop_margin, sampling=sampling)
    prepared.update(vertical_alignment=alignment, environment='air', original_video_frame_size=original_size)
    if remove_effects_prompt_file:
        return finish_prepared_variants(prepared, image_profile, prompt_file, remove_effects_prompt_file,
                                         job, output, max_side, alpha_cutoff,background_profile,refine_required)
    return finish_prepared(prepared, image_profile, prompt_file, job, output, max_side, alpha_cutoff,background_profile,refine_required)


def action(video, reference_profile, start, end, count, job, output, image_profile, prompt_file,
           seconds, motion_type='return_to_start', lead_start=None, quality='compact',
           lead_refresh_ms=160, **options):
    if motion_type not in ('loop', 'return_to_start', 'hold_end_pose'):
        raise ValueError('Unknown motion type')
    reference, roi = load_reference(reference_profile)
    if options.get('scale') is None:
        options['scale'] = json.loads(Path(reference_profile).read_text(encoding='utf-8-sig'))['frame_scale']
    indices, sampling = sample_video(video, start, end, count, motion_type, motion_type=='loop',
                                     seconds=seconds, quality=quality, lead_start=lead_start,
                                     lead_refresh_ms=lead_refresh_ms)
    return selected_finish(video, indices, reference, roi, job, output, image_profile, prompt_file,
                           seconds, motion_type=motion_type, sampling=sampling, **options)


def jump(video, rise_start, apex, fall_end, roi, rise_count, fall_count, job, output,
         image_profile, prompt_file, rise_seconds, fall_seconds, **options):
    if not 0 <= rise_start < apex < fall_end:
        raise ValueError('Jump requires rise_start < apex < fall_end')
    guard_inputs(job, {'video': video, 'profile': image_profile, 'prompt': prompt_file,
                       'remove': options.get('remove_effects_prompt_file')},
                 dict(rise_start=rise_start, apex=apex, fall_end=fall_end, roi=roi,
                      rise_count=rise_count, fall_count=fall_count, rise_seconds=rise_seconds,
                      fall_seconds=fall_seconds, options={k:v for k,v in options.items()
                      if k not in ('max_side', 'alpha_cutoff', 'remove_effects_prompt_file')}), name='jump-inputs.json')
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
    joint_summary = job/'joint-result'/'variants.json' if 'variants' in result else job/'joint-result'/'animation.json'
    return split_jump(result, rise, fall, apex, job, output, rise_seconds, fall_seconds, profile, joint_summary)


def split_jump(result, rise, fall, apex, job, output, rise_seconds, fall_seconds, profile, joint_summary):
    """Reuse joint processed pixels for both phases, including corrected shared cut points."""
    job, output = Path(job), Path(output)
    indices = result['sample_indices']
    paired = 'variants' in result
    joint_variants = result['variants'] if paired else {None: result}
    results = {}
    for name, selected, seconds in (('rise', rise, rise_seconds), ('fall', fall, fall_seconds)):
        orders = [indices.index(i) for i in selected]
        phase_variants = {}
        for variant, joint in joint_variants.items():
            images = []
            for order in orders:
                with Image.open(joint['final_frames'][order]) as im:
                    images.append(im.convert('RGBA'))
            sheet, columns, rows = pack(images)
            stage = job / variant if variant else job
            stage.mkdir(parents=True, exist_ok=True)
            sheet_path = stage/(name+'-sheet.png')
            sheet.save(sheet_path)
            report = dict(joint)
            report.update(frames=len(selected), sample_indices=selected, requested_seconds=seconds,
                      duration_ms=sum(timings(seconds, len(selected))),
                      frame_durations_ms=timings(seconds, len(selected)),
                      columns=columns, rows=rows, loop=False, motion_type='hold_end_pose',
                      shared_apex_source_index=apex, shared_crop_source_indices=indices,
                      sampling={'strategy': 'uniform', 'phase': name})
            for field in ('cropped_frames', 'final_frames', 'refinement'):
                report[field] = [joint[field][i] for i in orders]
            # Within each variant, both phases share the same processed cut point.
            report['vertical_alignment'] = dict(joint['vertical_alignment'])
            report['vertical_alignment']['matches'] = [joint['vertical_alignment']['matches'][i] for i in orders]
            destination = output / name / variant if variant else output / name
            phase_variants[variant] = finish(sheet_path, report, destination)
        results[name] = variant_summary(phase_variants, output / name) if paired else phase_variants[None]
    summary = {'rise': results['rise'], 'fall': results['fall'], 'airborne_reference': str(Path(profile).resolve()),
               'joint_summary': str(Path(joint_summary).resolve()),
               'split': dict(rise=rise, fall=fall, apex=apex, rise_seconds=rise_seconds, fall_seconds=fall_seconds)}
    reference = Path(json.loads(Path(profile).read_text(encoding='utf-8-sig'))['reference_image'])
    summary['reference_image'] = str((reference if reference.is_absolute() else Path(profile).parent/reference).resolve())
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
        cmd.add_argument('--remove-effects-prompt-file',
                         help='Produce with_effects and without_effects using the same selected frames')
        cmd.add_argument('--background-profile',default='.local/background-profile.json')
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
            cmd.add_argument('--count', type=int)
            cmd.add_argument('--quality', choices=('compact', 'balanced', 'smooth'), default='compact')
            cmd.add_argument('--lead-start', type=int)
            cmd.add_argument('--lead-refresh-ms', type=float, default=160)
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
