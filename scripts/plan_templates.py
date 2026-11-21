"""Build data-flow plans from the existing character task list; no generation."""
import secrets
from pathlib import Path


def ref(task, stage, key):
    return {'from':task+'.'+stage,'key':key}


def create(character, workspace, image_profile, video_profile, pose_provider='gpt_image', background_mode='plain'):
    if background_mode not in ('plain','preserve'):raise ValueError('Unknown background mode')
    tasks = []
    stances = list(character['stances'])
    first = stances[0]
    idle_ids = {t['stance']:t['id'] for t in character['tasks'] if t['entry_reference']=='stance_reference'}
    jump_ids = {t['stance']:t['id'] for t in character['tasks'] if t['pipeline']=='jump'}
    for stance in stances:
        identifier = stance+'-reference'
        root = 'work/character/references/'+stance
        steps = [{'id':'pose','operation':'image','args':{
            'profile':image_profile,'image':None,'prompt_file':None,'job':root+'/pose'}}]
        if pose_provider=='gpt_image':
            steps=[{'id':'pose','operation':'pose_reference','args':{'manifest':root+'/pose/manifest.json'}}]
        elif pose_provider!='comfyui':raise ValueError('Unknown pose provider')
        if stance == first and background_mode=='plain':
            steps.append({'id':'standing','operation':'geometry','args':{
                'image':ref(identifier,'pose','file'),'stage':'standing',
                'image_profile':image_profile,
                'job':root+'/standing-job','output':'outputs/character/references/'+stance}})
        tasks.append({'id':identifier,'kind':'reference','stance':stance,'effect_type':'none','steps':steps,
                      'available_reference':character['reference']})
    if any(item['entry_reference']=='prepared_stance' for item in character['tasks']):
        for stance in stances:
            identifier = stance+'-layout'
            root = 'work/character/references/'+stance
            standing = stance==first and background_mode=='plain'
            args = {'image':ref(stance+'-reference','standing' if standing else 'pose',
                               'standing' if standing else 'file'),
                    'side':character['side'], 'video_profile':video_profile,
                    'image_profile':image_profile, 'job':root+'/layout-job',
                    'output':'outputs/character/references/'+stance+'/input'}
            depends = [stance+'-reference']
            if background_mode=='plain':
                args['standing_reference'] = ref(first+'-reference','standing','metadata_file')
                if stance!=first:
                    depends.append(first+'-reference')
            else:
                args.update(background_mode='preserve',subject_box=None,ground_anchor=None,bottom_ratio=.15)
                if stance!=first:
                    depends.append(first+'-layout')
                    args['reference_geometry'] = ref(first+'-layout','layout','metadata_file')
            tasks.append({'id':identifier,'kind':'reference','stance':stance,'depends_on':depends,'effect_type':'none',
                          'steps':[{'id':'layout','operation':'geometry','args':args}]})
    for item in character['tasks']:
        identifier,stance = item['id'],item['stance']
        idle = item['action']=='idle'
        root,out = item['job'],item['output']
        steps = []
        depends = list(item['depends_on'])
        if item['entry_reference']=='stance_reference':
            depends = [stance+'-reference']
            if first != stance:
                depends.append(first+'-reference')
            standing = stance==first and background_mode=='plain'
            pose = ref(stance+'-reference','standing' if standing else 'pose',
                       'standing' if standing else 'file')
            steps.append({'id':'layout','operation':'geometry','args':{
                'image':pose,'standing_reference':ref(first+'-reference','standing','metadata_file'),
                'side':character['side'],'video_profile':video_profile,
                'image_profile':image_profile,
                'job':root+'/layout-job','output':out+'/input'}})
            if background_mode=='preserve':
                args=steps[-1]['args']
                args.pop('standing_reference')
                args.update(background_mode='preserve',subject_box=None,ground_anchor=None,bottom_ratio=.15)
                if stance!=first:
                    depends.append(idle_ids[first])
                    args['reference_geometry']=ref(idle_ids[first],'layout','metadata_file')
            input_image = ref(identifier,'layout','prepared')
            layout_task = identifier
        elif item['entry_reference']=='prepared_stance':
            layout_task = stance+'-layout'
            depends.append(layout_task)
            input_image = ref(layout_task,'layout','prepared')
        elif item['entry_reference']=='airborne':
            input_image = ref(jump_ids[stance],'finish','reference_image')
            jump_item = next(t for t in character['tasks'] if t['id']==jump_ids[stance])
            layout_task = stance+'-layout' if jump_item['entry_reference']=='prepared_stance' else idle_ids[stance]
        else:
            input_image = ref(idle_ids[stance],'anchor','files.0')
            layout_task = idle_ids[stance]
        steps.append({'id':'video','operation':'video','args':{
            'profile':video_profile,'image':input_image,'prompt_file':None,'job':root+'/video-job',
            'width':ref(layout_task,'layout','geometry.width'),
            'height':ref(layout_task,'layout','geometry.height'),
            'seconds':3,'seed':secrets.randbelow(2**48)}})
        steps.append({'id':'source','operation':'source','args':{
            'video':ref(identifier,'video','videos.0.path'),'output':root+'/source-review'}})
        select_args = {'video':ref(identifier,'video','videos.0.path'),'output':root+'/selection',
                       'scale':ref(layout_task,'layout','restore_scale'),
                       'source_overview':ref(identifier,'source','video'),
                       'source_checks':ref(identifier,'source','bounds')}
        jump = item['pipeline']=='jump'
        if jump:
            select_args.update(rise_start=None,apex=None,fall_end=None,roi=None,
                               rise_seconds=None,fall_seconds=None)
        else:
            select_args.update(seconds=None,motion_type=item['motion_type'],
                foreground={'profile':'.local/background-profile.json','job':root+'/analysis-alpha-jobs'})
            if item['pipeline']=='standard' and item['motion_type']=='return_to_start':
                select_args.update(seconds=1,playback_fps=25)
        steps.append({'id':'selection','operation':'jump_selection' if jump else 'selection','args':select_args})
        finish_args = {'selection_file':ref(identifier,'selection','selection_file'),
            'image_profile':image_profile,'prompt_file':None,'remove_effects_prompt_file':None,
            'background_profile':'.local/background-profile.json',
            'effects_present':ref(identifier,'selection','review.values.effects_present'),
            'refine_required':ref(identifier,'selection','review.values.refine_required'),
            'job':root+'/finish-job','output':out}
        if item['entry_reference']=='airborne':
            finish_args['reference_profile'] = ref(jump_ids[stance],'finish','airborne_reference')
        steps.append({'id':'finish','operation':'jump_finish' if jump else 'finish','args':finish_args})
        steps.append({'id':'package','operation':'package','args':{
            'summary':ref(identifier,'finish','result_file'),
            'video':ref(identifier,'video','videos.0.path'),'output':out+'/packages'}})
        if item['entry_reference']=='stance_reference':
            steps.append({'id':'anchor','operation':'frames','args':{
                'video':ref(identifier,'video','videos.0.path'),
                'indices':[ref(identifier,'selection','sample_indices.0')],'output':root+'/idle-anchor'}})
        tasks.append({'id':identifier,'kind':'animation','character_task':identifier,'stance':stance,
                      'is_idle':idle,'pipeline':item['pipeline'],'effect_type':'none',
                      'depends_on':depends,'description':item['description'],'steps':steps})
    return {'workspace':str(Path(workspace).resolve()),'pose_provider':pose_provider,'background_mode':background_mode,
            'assets':{'character_reference':character['reference']},'tasks':tasks}


def from_video(video, workspace, image_profile):
    identifier = 'provided-animation'
    root = 'work/animations/'+identifier
    output = 'outputs/animations/'+identifier
    return {'workspace':str(Path(workspace).resolve()),'assets':{},'tasks':[{
        'id':identifier,'kind':'animation','effect_type':'none','steps':[
            {'id':'source','operation':'source','args':{'video':str(Path(video).resolve()),'output':root+'/source-review'}},
            {'id':'selection','operation':'selection','args':{'video':str(Path(video).resolve()),
                'output':root+'/selection','seconds':None,'motion_type':None,
                'foreground':{'profile':'.local/background-profile.json','job':root+'/analysis-alpha-jobs'},
                'source_overview':ref(identifier,'source','video'),
                'source_checks':ref(identifier,'source','bounds')}},
            {'id':'finish','operation':'finish','args':{
                'selection_file':ref(identifier,'selection','selection_file'),'image_profile':image_profile,
                'prompt_file':None,'remove_effects_prompt_file':None,
                'background_profile':'.local/background-profile.json',
                'effects_present':ref(identifier,'selection','review.values.effects_present'),
                'refine_required':ref(identifier,'selection','review.values.refine_required'),
                'job':root+'/finish-job','output':output}},
            {'id':'package','operation':'package','args':{'video':str(Path(video).resolve()),
                'summary':ref(identifier,'finish','result_file'),'output':output+'/packages'}}]}]}
