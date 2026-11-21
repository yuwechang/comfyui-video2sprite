"""Compile semantic inputs into immutable prompt files and typed stage parameters."""
import hashlib
import inspect
from pathlib import Path
from string import Template
from workflow_ops import OPERATIONS

TEMPLATES={
 'pose':Template('$target。保留$preserve。完整全身、貼近人物構圖且只留小邊距。$background。'),
 'video_i2v':Template('For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\nintegrated_multimodal_description: [Shot 1] $description\n\noverall_soundscape: $soundscape\n\nnon_diegetic_music: $music'),
 'refine':Template('清理這張角色動畫影格，修復動態模糊，保持$preserve。保留當前動作姿勢、角色尺度、畫布內位置與畫布尺寸，保持原背景。$effects。')}

def render(value):
    if not isinstance(value,dict):raise ValueError('Prompt must be an object')
    if set(value)=={'text'}:
        text=value['text']
    elif set(value)=={'template','values'} and value['template'] in TEMPLATES:
        fields=value['values']
        if not isinstance(fields,dict) or any(not isinstance(x,str) or not x.strip() for x in fields.values()):
            raise ValueError('Prompt values must be nonempty semantic strings')
        template=TEMPLATES[value['template']]
        required={m.group('named') or m.group('braced') for m in template.pattern.finditer(template.template)
                  if m.group('named') or m.group('braced')}
        if set(fields)!=required:raise ValueError('Prompt requires exactly: '+', '.join(sorted(required)))
        text=template.substitute(fields)
    else:raise ValueError('Provide prompt text, or a known template and its values')
    if not isinstance(text,str) or not text.strip():raise ValueError('Prompt is empty')
    return text

def compile_request(config,state,request,workspace):
    """Validate the entire request before writing any prompts; no graph surgery."""
    import copy
    result=copy.deepcopy(config);pending=[]
    if not isinstance(request,dict) or set(request)!={'tasks'} or not isinstance(request['tasks'],dict) or not request['tasks']:
        raise ValueError('Provide nonempty tasks mapping')
    for task_id,stages in request['tasks'].items():
        task=next((t for t in result['tasks'] if t['id']==task_id),None)
        if task is None:raise ValueError('Unknown task: '+task_id)
        if not isinstance(stages,dict):raise ValueError('Task stages must be an object')
        for stage_id,values in stages.items():
            if not isinstance(values,dict):raise ValueError('Stage settings must be an object')
            step=next((s for s in task['steps'] if s['id']==stage_id),None)
            if step is None:raise ValueError('Unknown stage: '+stage_id)
            record=state.get('tasks',{}).get(task_id,{}).get('steps',{}).get(stage_id,{})
            if record.get('status') not in (None,'pending','needs_configuration') or record.get('result') or record.get('fingerprint'):
                raise ValueError('Request only configures unexecuted stages; use configure for reviewed changes')
            if set(values)-{'parameters','prompts'}:raise ValueError('Use parameters and prompts')
            parameters=values.get('parameters',{})
            if not isinstance(parameters,dict) or not isinstance(values.get('prompts',{}),dict):raise ValueError('parameters and prompts must be objects')
            if step['operation']=='package':allowed={'summary','video','output'}
            else:allowed=set(inspect.signature(OPERATIONS[step['operation']]).parameters)
            if set(parameters)-allowed:raise ValueError('Unknown stage parameters')
            step['args'].update(parameters)
            for field,prompt in values.get('prompts',{}).items():
                if field not in allowed or field not in ('prompt_file','remove_effects_prompt_file'):
                    raise ValueError('Stage does not accept this prompt field')
                text=render(prompt);digest=hashlib.sha256(text.encode()).hexdigest()
                target=Path(workspace)/'work/prompts'/task_id/stage_id/(field+'-'+digest+'.txt')
                step['args'][field]=str(target.resolve());pending.append((target,text))
    for path,text in pending:
        if path.exists() and path.read_text(encoding='utf-8')!=text:raise ValueError('Immutable prompt changed')
    for path,text in pending:
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():path.write_text(text,encoding='utf-8')
    return result

def missing_inputs(config,state):
    missing=[]
    for task in config['tasks']:
        for step in task['steps']:
            record=state.get('tasks',{}).get(task['id'],{}).get('steps',{}).get(step['id'],{})
            if record.get('status')=='completed':continue
            required=({'summary','video','output'} if step['operation']=='package' else
                {name for name,p in inspect.signature(OPERATIONS[step['operation']]).parameters.items()
                 if p.default is inspect.Parameter.empty})
            if step['operation']=='geometry' and step.get('args',{}).get('stage','layout')=='layout':
                required.add('side')
                if step['args'].get('background_mode')=='preserve':required.update(('subject_box','ground_anchor'))
            if step['operation']=='selection' and step.get('args',{}).get('sampling_method')=='pose':
                if step['args'].get('indices') is None:required.discard('seconds')
                if not (step['args'].get('pose') or {}).get('model'):required.add('pose.model')
            fields=sorted(k for k in required if step.get('args',{}).get(k) is None)
            if fields:missing.append({'task':task['id'],'stage':step['id'],'fields':fields})
    return missing

def prepare_pose(config,task_id,values,workspace):
    from pose_reference import prepare
    task=next((t for t in config['tasks'] if t['id']==task_id and t.get('kind')=='reference'),None)
    if task is None:raise ValueError('Select a reference task')
    step=next(s for s in task['steps'] if s['operation']=='pose_reference')
    text=render(values['prompt']);job=Path(workspace)/Path(step['args']['manifest']).parent
    prompt=Path(workspace)/'work/prompts'/task_id/'pose-request.txt'
    if job.exists() and any(job.iterdir()):raise ValueError('Pose request already exists; use its recorded inputs')
    prompt.parent.mkdir(parents=True,exist_ok=True);prompt.write_text(text,encoding='utf-8')
    return {**prepare(values['reference'],prompt,job),'prompt_text':text}
