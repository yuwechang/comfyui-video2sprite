"""Explicit data-flow adapters; leaves remain independently usable."""
import argparse
import json
from pathlib import Path
from generate import save


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def pose_reference(manifest):
    from pose_reference import load_manifest
    return load_manifest(manifest)


def camera_alignment(selection_file,regions_file,output,max_shift=32,max_disagreement=3):
    from camera_alignment import align
    return align(selection_file,regions_file,output,max_shift,max_disagreement)


def image(profile, image, prompt_file, job, flatten_alpha=True):
    from PIL import Image
    from process_image import process
    source = Path(image)
    if flatten_alpha:
        with Image.open(source) as original:
            if 'A' in original.getbands() and original.getchannel('A').getextrema()[0] < 255:
                canvas = Image.new('RGBA', original.size, (128,128,128,255))
                canvas.alpha_composite(original.convert('RGBA'))
                source = Path(job)/'editing-input.png'
                source.parent.mkdir(parents=True, exist_ok=True)
                canvas.convert('RGB').save(source)
    result = process(profile, source, Path(prompt_file).read_text(encoding='utf-8'), job)
    return {**result, 'editing_input': str(source.resolve())}


def geometry(image, job, output, stage='layout', side=None, standing_reference=None,
             video_profile='.local/profile.json', image_profile='.local/image-profile.json',
             preparation=None, expand_horizontal=None, expand_top=None, expand_bottom=None,
             bottom_ratio=None,background_mode=None,subject_box=None,ground_anchor=None,
             reference_geometry=None,source_coordinate_scale=None):
    values = locals().copy()
    import prepare_character as p
    args = argparse.Namespace(**values, multiple_x=32, multiple_y=32)
    result = p.standing_reference(args) if stage == 'standing' else p.prepare(args)
    result['metadata_file'] = str((Path(output)/('standing.json' if stage=='standing' else 'preparation.json')).resolve())
    from review_metrics import geometry_check
    result['geometry_verification']=geometry_check(values,result)
    return result


def video(profile, image, prompt_file, job, width, height, seconds, seed, image2=None, timeout=3600,extra_images=None,
          keyframe_background=None):
    values = locals().copy()
    values.pop('keyframe_background');normalization=None
    if keyframe_background:
        from keyframe_background import normalize
        normalization=normalize([image]+([image2] if image2 else [])+(extra_images or []),**keyframe_background)
        paths=normalization['images'];values['image']=paths[0]
        if image2:values['image2']=paths[1]
        if extra_images:values['extra_images']=paths[2:]
    from generate import run
    result=run(argparse.Namespace(**values))
    if normalization:result['keyframe_background']=normalization
    return result


def source(video, output):
    from source_clock import FrameClock
    from check_video_bounds import check
    clock = FrameClock.read(video)
    bounds = check(video)
    save(Path(output)/'bounds.json', bounds)
    return {'bounds':bounds, 'bounds_file':str((Path(output)/'bounds.json').resolve()),
            'video':str(Path(video).resolve()), 'source_frames':len(clock.pts)}


def selection(video, output, seconds, motion_type, scale=1, start=None, end=None,
              count=None, lead_start=None, quality='compact', lead_refresh_ms=160, source_overview=None,
              indices=None, frame_durations_ms=None, source_checks=None,foreground=None,sampling_method='novelty',
              source_timing=False,pose=None,playback_fps=None):
    from spritesheet import extract_frames
    from frame_sampling import sample_video
    candidate=None
    if source_timing and not indices:raise ValueError('Source timing requires explicit nonempty indices')
    if indices is not None:
        if source_timing:
            if frame_durations_ms is not None or motion_type=='hold_end_pose':
                raise ValueError('Source midpoint timing requires no explicit durations and no X/Y hold phases')
            from source_clock import FrameClock,y_weights,allocate_ticks,total_ticks,QUANTUM_MS
            clock=FrameClock.read(video)
            frame_durations_ms=[tick*QUANTUM_MS for tick in allocate_ticks(
                y_weights(clock,indices,indices[0],indices[-1]),total_ticks(seconds))]
        if frame_durations_ms is None:
            raise ValueError('Explicit indices need frame_durations_ms')
        sampling = {'strategy':'explicit','frame_durations_ms':frame_durations_ms}
        if source_timing:sampling['timing_assignment']={'method':'source_timestamp_midpoints'}
        if motion_type == 'hold_end_pose':
            from source_clock import FrameClock, phase_budget
            if any(v is None for v in (lead_start,start,end)):
                raise ValueError('Explicit hold_end_pose indices require lead_start A, start B, end D')
            if (len(indices)!=len(frame_durations_ms) or start not in indices
                    or indices[-1]!=end or indices[0]<lead_start):
                raise ValueError('Explicit hold_end_pose indices must cover B..D and stay within A..D')
            budget=phase_budget(FrameClock.read(video),lead_start,start,end,seconds)
            x=[i for i in indices if i<start]
            if (sum(t for i,t in zip(indices,frame_durations_ms) if i<start)!=budget['x_ms']
                    or sum(frame_durations_ms)!=budget['actual_total_ms']):
                raise ValueError('Explicit X/Y durations must match the source-proportional phase budget')
            sampling.update(phases={'a':lead_start,'b':start,'d':end,
                'x':{'indices':x},'y':{'indices':[i for i in indices if i>=start]}},
                budget=budget,lead_review_required=False)
    elif start is None and end is None:
        from select_segment import select
        candidate = select(video,motion_type,count,foreground=foreground,
                           mask_output=Path(output)/'analysis-masks' if foreground else None)
        save(Path(output)/'candidate.json',candidate)
        if candidate['status'] != 'selected':
            raise ValueError('No clear interval; inspect original source '+str(Path(video).resolve()))
        start,end = candidate['start'],candidate['end']
        if motion_type=='hold_end_pose' and lead_start is None and candidate.get('lead_start') is not None:
            lead_start=candidate['lead_start']
    if indices is None:
        if sampling_method=='pose':
            if count is not None:raise ValueError('Pose sampling computes its own frame count')
            from pose_sampling import sample
            indices,sampling,seconds=sample(video,start,end,output,seconds,motion_type,pose,foreground,
                lead_start,lead_refresh_ms)
        else:
            indices,sampling = sample_video(video,start,end,count,motion_type,motion_type=='loop',
                seconds=seconds,quality=quality,lead_start=lead_start,lead_refresh_ms=lead_refresh_ms,foreground=foreground,
                sampling_method=sampling_method,playback_fps=playback_fps)
        if playback_fps is not None and motion_type == 'return_to_start' and sampling_method=='pose':
            from frame_sampling import fixed_playback
            from select_segment import features
            from source_clock import FrameClock
            start, end = indices[0], indices[-1]
            analysis, _ = features(video,start,end,full_rate=True,subject_only=True,foreground=foreground)
            if len(indices) > 1:
                indices,seconds = fixed_playback(analysis,indices,FrameClock.read(video),
                                                 start,end,seconds,playback_fps,sampling)
        if 'playback' in sampling:
            seconds = len(sampling['playback']['sequence']) / sampling['playback']['fps']
    images = extract_frames(video,indices,output)
    paths = []
    for index,image in zip(indices,images):
        path = Path(output)/f'selected-{index}.png'
        image.save(path)
        paths.append(str(path.resolve()))
    from spritesheet import playback_timings
    result = {'video':str(Path(video).resolve()),'selected_frames':paths,'sample_indices':indices,
              'sampling':sampling,'frame_durations_ms':playback_timings(seconds,len(paths),sampling),
              'source_overview':source_overview or str(Path(video).resolve()),'source_checks':source_checks,
              'seconds':seconds,'scale':scale,'motion_type':motion_type}
    if candidate:
        result.update({key:candidate[key] for key in ('analysis_metadata','analysis_masks') if key in candidate})
    save(Path(output)/'selection.json',result)
    return {**result,'selection_file':str((Path(output)/'selection.json').resolve())}


def jump_selection(video, output, rise_start, apex, fall_end, roi, rise_seconds, fall_seconds,
                   rise_count=8, fall_count=8, scale=1, source_overview=None, source_checks=None):
    from spritesheet import sample_indices,extract_frames
    from airborne import validate_roi
    rise = sample_indices(rise_start,apex,rise_count,False)
    fall = sample_indices(apex,fall_end,fall_count,False)
    if not rise_start < apex < fall_end:
        raise ValueError('Require rise_start < apex < fall_end')
    indices = sorted(set(rise+fall))
    images = extract_frames(video,indices,output)
    validate_roi(images[indices.index(apex)],roi)
    paths = []
    for index,image in zip(indices,images):
        path = Path(output)/f'selected-{index}.png';image.save(path);paths.append(str(path.resolve()))
    result = dict(video=str(Path(video).resolve()),selected_frames=paths,sample_indices=indices,
        rise=rise,fall=fall,apex=apex,roi=roi,rise_seconds=rise_seconds,fall_seconds=fall_seconds,scale=scale,
        source_overview=source_overview,source_checks=source_checks)
    save(Path(output)/'selection.json',result)
    return {**result,'selection_file':str((Path(output)/'selection.json').resolve())}


def jump_finish(selection_file, image_profile, prompt_file, job, output, effects_present,
                remove_effects_prompt_file=None, max_side=None, alpha_cutoff=8,background_profile=None,refine_required=True):
    from PIL import Image
    from airborne import create_reference
    from airborne_pipeline import selected_finish,split_jump
    if type(effects_present) is not bool:
        raise ValueError('Provide reviewed effects flag')
    if effects_present and remove_effects_prompt_file:
        prompt_file = remove_effects_prompt_file
    data = read(selection_file);images = []
    for path in data['selected_frames']:
        with Image.open(path) as image:images.append(image.convert('RGBA'))
    reference = images[data['sample_indices'].index(data['apex'])]
    profile = create_reference(reference,data['roi'],Path(output)/'airborne-reference',data['scale'])
    joint_output = Path(job)/'joint-result'
    result = selected_finish(data['video'],data['sample_indices'],reference.convert('RGB'),data['roi'],
        job,joint_output,image_profile,prompt_file,data['rise_seconds']+data['fall_seconds'],
        scale=data['scale'],max_side=max_side,motion_type='hold_end_pose',selected_frames=images,
        alpha_cutoff=alpha_cutoff,remove_effects_prompt_file=None,
        background_profile=background_profile,refine_required=refine_required)
    result = clean(result,joint_output)
    result = split_jump(result,data['rise'],data['fall'],data['apex'],job,output,data['rise_seconds'],
                       data['fall_seconds'],profile,joint_output/'variants.json')
    result['reference_image'] = str((Path(output)/'airborne-reference/reference.png').resolve())
    save(Path(output)/'jump.json',result)
    return result


def clean(report, output):
    from finish_animation import variant_summary
    report['effect_variant'] = 'clean'
    save(Path(output)/'animation.json',report)
    return variant_summary({'clean':report},output)


def finish(selection_file, image_profile, prompt_file, job, output, effects_present,
           remove_effects_prompt_file=None, max_side=None, alpha_cutoff=8, reference_profile=None,
           overrides=None,background_profile=None,refine_required=True):
    from PIL import Image
    from finish_animation import finish_prepared_variants
    from spritesheet import prepare_frames
    if type(effects_present) is not bool:
        raise ValueError('effects_present must be the reviewed selected-frame boolean')
    if effects_present and remove_effects_prompt_file:
        prompt_file = remove_effects_prompt_file
    data = read(selection_file)
    images = []
    for path in data['selected_frames']:
        with Image.open(path) as image:
            images.append(image.convert('RGBA'))
    if reference_profile:
        if data.get('camera_alignment'):
            raise ValueError('Do not combine background camera registration with waist alignment')
        from airborne import load_reference
        from airborne_pipeline import selected_finish
        reference,roi = load_reference(reference_profile)
        result = selected_finish(data['video'],data['sample_indices'],reference,roi,job,output,
            image_profile,prompt_file,data['seconds'],scale=data['scale'],max_side=max_side,
            motion_type=data['motion_type'],overrides=overrides,selected_frames=images,
            sampling=data['sampling'],alpha_cutoff=alpha_cutoff,
            remove_effects_prompt_file=None,
            background_profile=background_profile,refine_required=refine_required)
        return clean(result,output)
    prepared = prepare_frames(images,data['sample_indices'],Path(job)/'shared',None,
        data['seconds'],data['motion_type']=='loop',scale=data['scale'],motion_type=data['motion_type'],
        sampling=data['sampling'])
    if data.get('camera_alignment'):prepared['camera_alignment']=data['camera_alignment']
    return finish_prepared_variants(prepared,image_profile,prompt_file,
             None,job,output,max_side,alpha_cutoff,background_profile,refine_required)


def corrections(summary, corrections, job, output):
    from apply_corrections import apply
    return apply(summary, corrections, job, output)


def frames(video, indices, output):
    from spritesheet import extract_frames
    folder = Path(output)
    images = extract_frames(video, indices, folder)
    paths = []
    for index, image in zip(indices, images):
        path = folder/f'frame-{index}.png'
        image.save(path)
        paths.append(str(path.resolve()))
    return {'files': paths}


OPERATIONS = {'camera_alignment':camera_alignment, 'pose_reference':pose_reference, 'image': image, 'geometry': geometry, 'video': video, 'selection': selection,
              'source': source, 'jump_selection': jump_selection, 'jump_finish': jump_finish, 'finish': finish, 'corrections': corrections, 'frames': frames}

REVIEWS = {'jump_selection':['coverage','timing','effects','body_scale'],
           'camera_alignment':['alignment','coverage','body_scale'],
           'pose_reference':['pose','identity','body_scale','background'],
           'jump_finish':['motion','alignment','identity','body_scale','background','effects'],
           'image': ['pose', 'identity', 'body_scale', 'background'],
           'geometry': ['body_scale', 'placement'],
           'selection': ['coverage', 'timing', 'effects', 'body_scale'],
           'finish': ['motion', 'identity', 'body_scale', 'background', 'effects'],
           'corrections': ['correction', 'identity', 'body_scale', 'background']}
