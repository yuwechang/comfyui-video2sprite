"""Run one or many animation tasks through persisted, reviewed data-flow stages."""
import argparse
import copy
import hashlib
from graphlib import TopologicalSorter, CycleError
import inspect
import json
import os
from pathlib import Path
import re
import sys
from contextlib import contextmanager
from functools import wraps
from diagnostics import inspect_result
from generate import save
from job_contract import file_digest
from workflow_ops import OPERATIONS, REVIEWS, read


@contextmanager
def workspace_lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'.lock').open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError('An execution is already running; wait for that process') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def exclusive(function):
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        with workspace_lock(self.workspace/'work/execution-plan'):
            self.__init__(self.path)
            previous = Path.cwd()
            os.chdir(self.workspace)
            try:
                return function(self, *args, **kwargs)
            finally:
                os.chdir(previous)
    return wrapped


class Plan:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.config = read(self.path)
        self.workspace = (self.path.parent/self.config.get('workspace', '.')).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.folder = self.workspace/'work/execution-plan'/self.path.stem
        self.state_path = self.folder/'state.json'
        self.state = read(self.state_path) if self.state_path.exists() else {'tasks': {}, 'documents': {}}
        tasks = self.config.get('tasks', [])
        if not tasks or len({t['id'] for t in tasks}) != len(tasks):
            raise ValueError('Provide a nonempty list of uniquely identified animation tasks')
        for task in tasks:
            self.identifier(task['id'])
            if task.get('effect_type') not in ('none', 'impact', 'trail'):
                raise ValueError('Each task needs explicit effect_type: none, impact, or trail')
            steps = task.get('steps', [])
            if not steps or len({s['id'] for s in steps}) != len(steps):
                raise ValueError('Each task needs uniquely identified stages')
            for step in steps:
                self.identifier(step['id'])
                if step.get('operation') not in OPERATIONS and step.get('operation') != 'package':
                    raise ValueError('Invalid plan operation: '+str(step.get('operation')))
        ids = {t['id'] for t in tasks}
        if any(set(t.get('depends_on', [])) - ids for t in tasks):
            raise ValueError('Unknown task dependency')
        try:
            order = list(TopologicalSorter({t['id']:set(t.get('depends_on', [])) for t in tasks}).static_order())
        except CycleError as exc:
            raise ValueError('Task dependency cycle') from exc
        by_id = {t['id']:t for t in tasks}
        self.config['tasks'] = [by_id[k] for k in order]
        self.requests = []

    @staticmethod
    def identifier(value):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', value):
            raise ValueError('Task and stage identifiers use letters, numbers, underscores and hyphens')

    def persist(self):
        save(self.state_path, self.state)
        self.sync_character()

    def sync_character(self):
        path = self.config.get('character_plan')
        if not path:
            return
        character = read(path)
        character['execution_plan'] = str(self.path)
        character['execution_state'] = str(self.state_path)
        for config in self.config['tasks']:
            state = self.state['tasks'].get(config['id'],{})
            steps = state.get('steps',{})
            stance = config.get('stance')
            if config.get('kind')=='reference' and state.get('status')=='completed':
                if 'layout' in steps:
                    layout = steps['layout']['result']
                    character['stances'][stance]['preparation'] = layout['metadata_file']
                    character['stances'][stance]['idle_frame'] = layout['prepared']
                else:
                    record = steps.get('standing',steps.get('pose',{}))['result']
                    character['stances'][stance]['reference'] = record.get('standing',record.get('file'))
            identifier = config.get('character_task')
            if not identifier:
                continue
            task = next(t for t in character['tasks'] if t['id']==identifier)
            task['status'] = ('completed' if state.get('status')=='completed' else
                              'running' if state.get('status')=='running' else
                              'needs_review' if state.get('status') == 'needs_attention' else 'pending')
            if config.get('is_idle'):
                if steps.get('layout',{}).get('status')=='completed':
                    character['stances'][stance]['preparation'] = steps['layout']['result']['metadata_file']
                if steps.get('anchor',{}).get('status')=='completed':
                    character['stances'][stance]['idle_frame'] = steps['anchor']['result']['files'][0]
            if state.get('status')=='completed':
                result = steps['finish']['result']
                assets = {'source_video':steps['video']['result']['videos'][0]['path'],
                          'review':steps['finish']['review_file']}
                if config.get('pipeline')=='jump':
                    assets.update(airborne_profile=result['airborne_reference'],
                        rise_zip=steps['package']['result']['rise']['zip'],
                        fall_zip=steps['package']['result']['fall']['zip'],
                        rise_animation=str(Path(result['rise']['variants'][next(iter(result['rise']['variants']))]['sheet']).parents[1]/'variants.json'),
                        fall_animation=str(Path(result['fall']['variants'][next(iter(result['fall']['variants']))]['sheet']).parents[1]/'variants.json'))
                    character['airborne'][stance] = result['airborne_reference']
                else:
                    assets['animation'] = result['result_file']
                    assets['zip'] = steps['package']['result']['action']['zip']
                task['artifacts'].update(assets)
        save(path,character)

    def resolve(self, value):
        if isinstance(value, dict) and set(value) == {'from', 'key'}:
            task, stage = value['from'].split('.', 1)
            record = self.state['tasks'].get(task, {}).get('steps', {}).get(stage, {})
            if record.get('status') != 'completed':
                raise ValueError(f'Input not ready: {task}.{stage}')
            result = record['result']
            for key in value['key'].split('.'):
                result = result[int(key)] if isinstance(result, list) else result[key]
            return result
        if isinstance(value, dict):
            return {key: self.resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.resolve(item) for item in value]
        return value

    def fingerprint(self, value):
        def describe(item):
            if isinstance(item, str) and len(item) < 4096:
                try:
                    path = Path(item)
                    if path.is_file():
                        return {'path': str(path.resolve()), 'sha256': file_digest(path)}
                except OSError:
                    pass
            if isinstance(item, dict):
                return {key: describe(v) for key, v in item.items()}
            if isinstance(item, list):
                return [describe(v) for v in item]
            return item
        return hashlib.sha256(json.dumps(describe(value), sort_keys=True).encode()).hexdigest()

    def collect(self, task, role, value):
        """Register assets at creation/use time; packaging never scans directories."""
        inventory = self.state['tasks'][task].setdefault('assets', {})
        if isinstance(value, dict):
            for key, item in value.items():
                self.collect(task, role+'/'+key, item)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self.collect(task, role+'/'+str(index), item)
        elif isinstance(value, str) and len(value) < 4096:
            try:
                path = Path(value)
                json_role=(role.rsplit('/',1)[-1] in
                    ('alignment_report','regions_file','reference_geometry','standing_reference','preparation','background_profile','background_job','analysis_metadata',
                     'pose_report','pose_landmarks','pose_transition_report','pose_contract')
                    or role.endswith('/foreground/profile') or role.startswith(('declared/','common/'))
                    or ('/keyframe_background/' in role and role.rsplit('/',1)[-1] in ('profile','report_file')))
                if path.is_file() and (path.suffix.lower() in ('.png','.jpg','.jpeg','.webp','.txt','.mp4','.webm','.wav')
                                      or (path.suffix.lower()=='.json' and json_role)
                                      or (path.suffix.lower()=='.npz' and '/pose_evidence/' in role)):
                    inventory[role+path.suffix.lower()] = {'path': str(path.resolve()),
                         'sha256': file_digest(path), 'bytes': path.stat().st_size}
            except OSError:
                pass

    @staticmethod
    def is_delivery_material(role):
        return ('/inputs/' in role
                or role.endswith(('/alignment_report.json', '/analysis_metadata.json'))
                or '/keyframe_background/' in role
                or '/sampling/pose_' in role
                or role.startswith(('common/', 'declared/', 'dependency/')))

    def package(self, task, arguments, stage_folder):
        from package_delivery import package
        summary = read(arguments['summary'])
        from material_contract import requirements
        assets = self.state['tasks'][task]['assets']
        files = {'materials/'+name: item['path'] for name,item in assets.items()
                 if self.is_delivery_material(name)
                 and '/analysis_masks/' not in name and '/source_masks/' not in name}
        required = requirements(self,task,assets,files)
        if 'airborne_reference' in summary:
            profile = Path(summary['airborne_reference'])
            files.update({'alignment/airborne-reference.json': str(profile),
                          'alignment/reference.png': str(profile.parent/'reference.png')})
        phases = {phase: summary[phase] for phase in ('rise', 'fall')} if 'rise' in summary else {'action': summary}
        result = {}
        for phase, data in phases.items():
            manifest = {'video': arguments['video'], 'files': files, 'required_materials': required,
                        'animations': {name: str(Path(report['sheet']).parent/'animation.json')
                                       for name,report in data['variants'].items()}}
            path = stage_folder/(phase+'-assets.json')
            save(path, manifest)
            result[phase] = package(path, Path(arguments['output'])/(phase+'.zip'))
        return result

    @exclusive
    def run(self):
        previous = Path.cwd()
        os.chdir(self.workspace)
        try:
            return self._run()
        finally:
            os.chdir(previous)

    def _run(self):
        tasks = self.config['tasks']
        for task in tasks:
            task_id = task['id']
            state = self.state['tasks'].setdefault(task_id, {'status': 'pending', 'steps': {}, 'assets': {}})
            if any(self.state['tasks'].get(dep, {}).get('status') != 'completed'
                   for dep in task.get('depends_on', [])):
                state['status'] = 'waiting_dependencies'
                continue
            # Resolve declared shared materials before processing; never reconstruct them at delivery.
            try:
                self.collect(task_id, 'common', self.resolve(self.config.get('assets', {})))
                self.collect(task_id, 'declared', self.resolve(task.get('assets', {})))
                for dep in task.get('depends_on', []):
                    reference_dep=next(t for t in tasks if t['id']==dep).get('kind')=='reference'
                    for role,item in self.state['tasks'][dep].get('assets',{}).items():
                        if reference_dep or self.is_delivery_material(role):
                            state['assets']['dependency/'+dep+'/'+role] = dict(item)
            except (ValueError, KeyError) as exc:
                self.requests.append({'task':task_id, 'status':'needs_configuration', 'reason':str(exc)})
                continue
            for step in task['steps']:
                step_id, operation = step['id'], step['operation']
                record = state['steps'].setdefault(step_id, {'status': 'pending'})
                folder = self.folder/task_id/step_id
                folder.mkdir(parents=True, exist_ok=True)
                try:
                    arguments = self.resolve(step.get('args', {}))
                    function = OPERATIONS.get(operation)
                    if function:
                        signature = inspect.signature(function)
                        signature.bind(**arguments)
                        missing = [k for k,p in signature.parameters.items()
                                   if p.default is inspect.Parameter.empty and p.kind not in
                                   (inspect.Parameter.VAR_KEYWORD,inspect.Parameter.VAR_POSITIONAL)
                                   and arguments.get(k) is None]
                        if (operation=='selection' and arguments.get('sampling_method')=='pose'
                                and arguments.get('indices') is None and 'seconds' in missing):
                            missing.remove('seconds')
                        if operation in ('finish', 'jump_finish') and 'prompt_file' in missing:
                            if arguments.get('refine_required') is False or (arguments.get('effects_present') and arguments.get('remove_effects_prompt_file')):
                                missing.remove('prompt_file')
                        if missing:
                            raise ValueError('Fill required stage arguments: '+', '.join(missing))
                    fingerprint = self.fingerprint({'operation': operation, 'args': arguments})
                    if record.get('fingerprint') and record['fingerprint'] != fingerprint:
                        raise ValueError('Stage inputs changed; use a new stage/task ID')
                    record['fingerprint'] = fingerprint
                    if record['status'] == 'completed':
                        if record.get('result_fingerprint') != self.fingerprint(record['result']):
                            raise ValueError('Recorded output changed or is missing')
                        continue
                    if record['status'] in ('needs_review', 'review_failed', 'repairing'):
                        self.requests.append({'task':task_id, 'stage':step_id, 'status':record['status'],
                                              'request':record['review_request'], 'repair':record.get('repair')})
                        break
                    if operation == 'finish':
                        # This branch is a reviewed fact, not a deduction from an action name.
                        present = arguments.get('effects_present')
                        if type(present) is not bool:
                            raise ValueError('Provide reviewed effects_present boolean')
                    self.collect(task_id, step_id+'/inputs', arguments)
                    record['status'] = 'running'
                    state['status'] = 'running'
                    self.persist()
                    result = (self.package(task_id, arguments, folder) if operation == 'package'
                              else function(**arguments))
                    save(folder/'result.json', result)
                    result['result_file'] = str((folder/'result.json').resolve())
                    record.update(result=result, result_fingerprint=self.fingerprint(result),
                                  effects_present=arguments.get('effects_present'))
                    self.collect(task_id, step_id+'/outputs', result)
                    required = REVIEWS.get(operation, [])
                    # A proven deterministic transform does not regenerate pose or
                    # identity. Record numeric evidence instead of inventing a visual pass.
                    source_ref=step.get('args',{}).get('image')
                    approved_source=False
                    if isinstance(source_ref,dict) and 'from' in source_ref:
                        source_task,source_stage=source_ref['from'].split('.',1)
                        source_record=self.state['tasks'][source_task]['steps'][source_stage]
                        source_result=source_record.get('result',{})
                        approved_source=(source_result.get('review',{}).get('items',{}).get('pose',{}).get('status')=='pass'
                                         or bool(source_record.get('automatic_check')))
                    if operation=='geometry' and approved_source and result.get('geometry_verification',{}).get('passed'):
                        save(folder/'geometry-check.json',result['geometry_verification'])
                        record['automatic_check']=str((folder/'geometry-check.json').resolve())
                        required=[]
                    if required:
                        diagnostic = inspect_result(result, folder/'inspection')
                        request = {'required_items': required, 'diagnostic': diagnostic,
                                   'result_file': str((folder/'result.json').resolve()),
                                   'instruction': 'Inspect the listed artifacts. Submit item status, evidence path and reason; no automatic visual pass.'}
                        save(folder/'review-request.json', request)
                        record.update(status='needs_review', review_request=str((folder/'review-request.json').resolve()))
                        self.requests.append({'task':task_id,'stage':step_id,'status':'needs_review',
                                              'request':record['review_request'], 'repair':record.get('repair')})
                        break
                    record['status'] = 'completed'
                    self.persist()
                except (TypeError, ValueError, KeyError, OSError) as exc:
                    record.update(status='needs_configuration', reason=str(exc))
                    self.requests.append({'task':task_id,'stage':step_id,'status':record['status'], 'reason':str(exc)})
                    break
                except Exception as exc:
                    record.update(status='failed', reason=str(exc))
                    self.requests.append({'task':task_id,'stage':step_id,'status':'failed','reason':str(exc)})
                    break
            state['status'] = ('completed' if all(s.get('status') == 'completed' for s in state['steps'].values())
                               and len(state['steps']) == len(task['steps']) else 'needs_attention')
            self.persist()
        complete = all(self.state['tasks'].get(t['id'], {}).get('status') == 'completed' for t in tasks)
        return {'status':'completed' if complete else 'needs_attention', 'state':str(self.state_path),
                'requests':self.requests,'deliveries':self.deliveries() if complete else []}

    def deliveries(self):
        return [{'task':task['id'],'stage':step['id'],'packages':
                 self.state['tasks'].get(task['id'],{}).get('steps',{}).get(step['id'],{}).get('result',{})}
                for task in self.config['tasks'] for step in task['steps']
                if step['operation']=='package' and
                self.state['tasks'].get(task['id'],{}).get('steps',{}).get(step['id'],{}).get('status')=='completed']

    def export_materials(self, tasks, output):
        files={}
        for identifier in tasks:
            task=next((t for t in self.config['tasks'] if t['id']==identifier),None)
            record=self.state['tasks'].get(identifier,{})
            if not task or record.get('status')!='completed':raise ValueError('Export materials only from completed tasks')
            for role,item in record.get('assets',{}).items():
                if (task.get('kind')=='reference' or '/inputs/' in role or
                        role.startswith(('common/','declared/','dependency/'))):
                    if file_digest(item['path'])!=item['sha256']:raise ValueError('Registered material changed: '+role)
                    files[identifier+'/'+role]={'path':item['path'],'sha256':item['sha256']}
        save(output,{'files':files})
        return {'status':'exported','materials_file':str(Path(output).resolve()),'files':len(files)}

    @exclusive
    def review(self, task, stage, decision_path):
        record = self.state['tasks'][task]['steps'][stage]
        if record['status'] not in ('needs_review','review_failed'):
            raise ValueError('Stage is not awaiting review')
        if record['result_fingerprint'] != self.fingerprint(record['result']):
            raise ValueError('Review artifacts changed')
        decision = read(decision_path)
        if record['result'].get('sampling',{}).get('lead_review_required'):
            raise ValueError('Confirm X/Y with an explicit lead_start (A, or B for no X) before review')
        required = read(record['review_request'])['required_items']
        items = decision.get('items', {})
        if set(items) != set(required):
            raise ValueError('Provide a decision for every required item')
        for name,item in items.items():
            if item.get('status') not in ('pass','fail','pending','n/a') or not item.get('reason','').strip():
                raise ValueError('Every item needs a status and specific reason')
            if item['status'] != 'n/a':
                evidence = Path(item.get('evidence',''))
                if not evidence.is_absolute():
                    evidence = Path(decision_path).resolve().parent/evidence
                if not evidence.is_file():
                    raise ValueError('Every applicable decision needs an existing evidence file')
                item['evidence'] = str(evidence.resolve())
        if any(item['status'] == 'n/a' for item in items.values()):
            raise ValueError('Required visual checks cannot be skipped as n/a')
        passed = all(item['status'] == 'pass' for item in items.values())
        if 'effects' in required and record.get('effects_present') is not None:
            decision.setdefault('values', {}).setdefault('effects_present', record['effects_present'])
        if 'effects' in required and passed and type(decision.get('values',{}).get('effects_present')) is not bool:
            raise ValueError('Effects review must record actual selected-frame effects_present')
        review_path = Path(record['review_request']).parent/'visual-review.json'
        save(review_path,decision)
        record['review_file'] = str(review_path.resolve())
        record['result']['review'] = decision
        record['result_fingerprint'] = self.fingerprint(record['result'])
        record['status'] = 'completed' if passed else 'review_failed'
        self.persist()
        return {'status':record['status'], 'task':task, 'stage':stage}

    @exclusive
    def configure(self, task, stage, arguments):
        config = next(t for t in self.config['tasks'] if t['id']==task)
        step = next(s for s in config['steps'] if s['id']==stage)
        record = self.state['tasks'].get(task,{}).get('steps',{}).get(stage,{})
        if record.get('status') in ('completed','running','repairing'):
            raise ValueError('Cannot change a completed or running stage; use a new task/stage')
        if record.get('result') or record.get('fingerprint'):
            old = self.resolve(step.get('args',{}))
            for name in ('job','output'):
                if name in old and arguments.get(name)==old[name]:
                    raise ValueError('Changed stage inputs require a new '+name+' directory')
        step['args'] = arguments
        if record:
            record.clear();record['status']='pending'
        inventory = self.state['tasks'].get(task,{}).get('assets',{})
        for name in list(inventory):
            if name.startswith(stage+'/'):
                del inventory[name]
        self.config['tasks'] = [config if t['id']==task else t for t in self.config['tasks']]
        save(self.path,self.config)
        self.persist()
        return {'status':'configured','task':task,'stage':stage}

    @exclusive
    def request(self, values):
        from task_inputs import compile_request,missing_inputs
        config=compile_request(self.config,self.state,values,self.workspace)
        save(self.path,config)
        return {'status':'configured','tasks':list(values['tasks']),'pending_inputs':missing_inputs(config,self.state)}

    @exclusive
    def prepare_pose(self, task, values):
        from task_inputs import prepare_pose
        if self.state['tasks'].get(task,{}).get('steps',{}):raise ValueError('Prepare pose before executing reference task')
        return prepare_pose(self.config,task,values,self.workspace)

    @exclusive
    def enable_camera(self, task, regions_file):
        config=next((t for t in self.config['tasks'] if t['id']==task),None)
        if not config or config.get('pipeline') in ('airborne','jump'):raise ValueError('Background compensation requires a ground selection/finish task')
        selection=next((s for s in config['steps'] if s['operation']=='selection'),None)
        finish=next((s for s in config['steps'] if s['operation']=='finish'),None)
        if not selection or not finish:raise ValueError('Background compensation requires selection and finish stages')
        record=self.state['tasks'].get(task,{}).get('steps',{}).get(finish['id'],{})
        if record.get('status') not in (None,'pending','needs_configuration') or record.get('result') or record.get('fingerprint'):
            raise ValueError('Enable compensation before finish executes')
        if any(s['operation']=='camera_alignment' for s in config['steps']):raise ValueError('Compensation already enabled')
        region=Path(regions_file).resolve();read(region)
        identifier='camera-alignment'
        if any(s['id']==identifier for s in config['steps']):raise ValueError('Stage identifier already used')
        step={'id':identifier,'operation':'camera_alignment','args':{
            'selection_file':{'from':task+'.'+selection['id'],'key':'selection_file'},
            'regions_file':str(region),'output':str(self.workspace/'work/camera-aligned'/task)}}
        config['steps'].insert(config['steps'].index(finish),step)
        finish['args']['selection_file']={'from':task+'.'+identifier,'key':'selection_file'}
        save(self.path,self.config)
        return {'status':'configured','task':task,'stage':identifier}

    @exclusive
    def repair(self, task, stage, specification, attempt):
        from process_image import process
        from apply_corrections import apply
        self.identifier(attempt)
        record = self.state['tasks'][task]['steps'][stage]
        if record['status'] not in ('review_failed','repairing'):
            raise ValueError('Repair requires a failed visual review')
        spec_path = Path(specification).resolve()
        spec = read(spec_path)
        current = record['result']
        joint = read(current['joint_summary']) if 'joint_summary' in current else current
        failed = current.get('review',{}).get('failed_frames',{})
        if not failed:
            raise ValueError('Failed review must identify failed_frames by variant/source index')
        for variant,entries in spec.items():
            if variant not in joint['variants'] or not entries:
                raise ValueError('Repair variant is not in the delivery')
            if any(int(index) not in failed.get(variant,[]) for index in entries):
                raise ValueError('Repair only the frames identified by the failed review')
        config = next(t for t in self.config['tasks'] if t['id']==task)
        step = next(s for s in config['steps'] if s['id']==stage)
        arguments = self.resolve(step['args'])
        signature = self.fingerprint(spec)
        folder = self.folder/task/stage/'repairs'/attempt
        pending = record.get('repair')
        if record['status']=='repairing' and pending != {'attempt':attempt,'fingerprint':signature}:
            raise ValueError('Resume the recorded repair before changing its inputs')
        if record['status']!='repairing' and folder.exists():
            raise ValueError('Use a new repair attempt name')
        record.update(status='repairing',repair={'attempt':attempt,'fingerprint':signature})
        self.persist()
        adopted = {}
        for variant,entries in spec.items():
            report = joint['variants'][variant]
            for index,item in entries.items():
                source_index = int(index)
                order = report['sample_indices'].index(source_index)
                source = report['refinement'][order]['input']
                prompt = Path(item['prompt_file'])
                prompt = prompt if prompt.is_absolute() else spec_path.parent/prompt
                self.collect(task,stage+'/repair/inputs/'+variant+'/'+index,
                             {'input':source,'prompt':str(prompt)})
                self.persist()
                result = process(arguments['image_profile'],source,prompt.read_text(encoding='utf-8'),
                                 folder/variant/index/'image-job')
                background_record={}
                if arguments.get('background_profile'):
                    from background_removal import remove_background
                    background_record={'before_background_removal':result['file'],
                        'background_job':str((folder/variant/index/'background-job/job.json').resolve())}
                    result=remove_background(arguments['background_profile'],result['file'],
                                             folder/variant/index/'background-job')
                adopted.setdefault(variant,{})[index] = {'image':result['file'],'prompt':str(prompt.resolve()),**background_record}
        manifest = folder/'replacements.json';save(manifest,adopted)
        summary_path = Path(current['result_file'])
        result = apply(summary_path,manifest,folder/'assembly',folder/'candidate')
        save(folder/'result.json',result)
        result['result_file'] = str((folder/'result.json').resolve())
        diagnostic = inspect_result(result,folder/'inspection')
        required = read(record['review_request'])['required_items']
        request = {'required_items':required,'diagnostic':diagnostic,
                   'result_file':result['result_file'],'repaired_frames':{v:list(e) for v,e in spec.items()},
                   'instruction':'Review repaired results; other accepted frames were not regenerated.'}
        save(folder/'review-request.json',request)
        record.update(result=result,result_fingerprint=self.fingerprint(result),status='needs_review',
                      review_request=str((folder/'review-request.json').resolve()))
        self.collect(task,stage+'/outputs',result)
        self.persist()
        return {'status':'needs_review','request':record['review_request']}

    def documents(self, paths):
        result = []
        for name in paths:
            path = Path(name).resolve()
            digest = file_digest(path)
            if self.state['documents'].get(str(path)) != digest:
                result.append({'path':str(path),'status':'new_or_changed'})
            else:
                result.append({'path':str(path),'status':'already_recorded'})
        return result

    @exclusive
    def record_documents(self, paths):
        result = self.documents(paths)
        for name in paths:
            path = Path(name).resolve()
            self.state['documents'][str(path)] = file_digest(path)
        self.persist()
        return result

    @exclusive
    def read_documents(self, paths, section=None, refresh=False, max_chars=10000):
        """Emit only unseen requested content; record exactly the emitted section."""
        if max_chars<1:raise ValueError('max_chars must be positive')
        result=[];updates={};total=0
        for name in paths:
            path=Path(name).resolve();content=path.read_text(encoding='utf-8-sig')
            if section:
                lines=content.splitlines(keepends=True)
                found=[i for i,line in enumerate(lines) if line.lstrip('#').strip()==section and line.startswith('#')]
                if len(found)!=1:raise ValueError('Provide one exact unique heading: '+section)
                start=found[0];level=len(lines[start])-len(lines[start].lstrip('#'));stop=len(lines)
                for i in range(start+1,len(lines)):
                    if lines[i].startswith('#') and len(lines[i])-len(lines[i].lstrip('#'))<=level:
                        stop=i;break
                content=''.join(lines[start:stop])
            key=str(path)+('#'+section if section else '')
            digest=hashlib.sha256(content.encode('utf-8')).hexdigest()
            if not refresh and self.state['documents'].get(key)==digest:
                result.append({'path':str(path),'section':section,'status':'already_read'});continue
            total+=len(content)
            if total>max_chars:raise ValueError('Guide exceeds output budget; request a specific heading or smaller set of files')
            result.append({'path':str(path),'section':section,'status':'read','content':content})
            updates[key]=digest
        self.state['documents'].update(updates);self.persist()
        return result

    @exclusive
    def preview_selection(self,task,stage,output):
        """Explicit diagnostic export; never approves or advances a review."""
        from PIL import Image
        record=self.state['tasks'][task]['steps'][stage]
        result=record['result']
        if record['result_fingerprint']!=self.fingerprint(result):
            raise ValueError('Selection artifacts changed')
        paths=result['selected_frames'];durations=result['frame_durations_ms']
        if not paths or len(paths)!=len(durations) or any(d<=0 or d%20 for d in durations):
            raise ValueError('Need existing selected frames and GIF-compatible timing')
        target=Path(output).resolve()
        if target.exists():raise ValueError('Use a new diagnostic output path')
        frames=[]
        for path in paths:
            with Image.open(path) as image:frames.append(image.convert('RGB'))
        if any(frame.size!=frames[0].size for frame in frames):
            raise ValueError('Selection canvas sizes differ')
        target.parent.mkdir(parents=True,exist_ok=True)
        frames[0].save(target,format='GIF',save_all=True,append_images=frames[1:],
                       duration=durations,loop=0,disposal=2,optimize=False)
        return {'preview':str(target),'frames':len(frames),'duration_ms':sum(durations),
                'diagnostic_only':True,'source_background_retained':True,'review_status':record['status']}

    @exclusive
    def display(self, output):
        from display_previews import render
        entries=[]
        for task in self.config['tasks']:
            if task.get('kind')=='reference':continue
            state=self.state['tasks'].get(task['id'],{})
            if state.get('status')!='completed':
                raise ValueError('Display requires completed tasks: '+task['id'])
            for step in task['steps']:
                if step['operation'] not in ('finish','jump_finish'):continue
                result=state['steps'][step['id']]['result']
                source_video=None
                for source_step in task['steps']:
                    source_result=state['steps'].get(source_step['id'],{}).get('result',{})
                    if source_step['operation']=='video' and source_result.get('videos'):
                        source_video=source_result['videos'][0]['path'];break
                    if source_step['operation']=='source':source_video=source_result.get('video')
                if 'rise' in result:
                    for phase in ('rise','fall'):
                        report=next(iter(result[phase]['variants'].values()))
                        entries.append({'id':task['id']+'-'+phase,
                            'summary':str(Path(report['sheet']).parents[1]/'variants.json'),'source_video':source_video})
                else:
                    entries.append({'id':task['id'],'summary':result['result_file'],'source_video':source_video})
        result=render(entries,output)
        self.state['display']=result
        self.persist()
        return {k:v for k,v in result.items() if k!='previews'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create')
    create.add_argument('--character-plan', required=True)
    create.add_argument('--workspace', default='.')
    create.add_argument('--image-profile', default='.local/image-profile.json')
    create.add_argument('--video-profile', default='.local/profile.json')
    create.add_argument('--pose-provider',choices=('gpt_image','comfyui'),default='gpt_image')
    create.add_argument('--background-mode',choices=('plain','preserve'),default='plain')
    provided = sub.add_parser('create-video')
    provided.add_argument('--video', required=True)
    provided.add_argument('--workspace', default='.')
    provided.add_argument('--image-profile', default='.local/image-profile.json')
    provided.add_argument('--materials-file',nargs='*',default=[])
    extend = sub.add_parser('extend')
    extend.add_argument('--character-plan', required=True)
    sub.add_parser('run')
    sub.add_parser('status')
    sub.add_parser('delivery')
    video_profile=sub.add_parser('set-video-profile');video_profile.add_argument('--file',required=True)
    materials=sub.add_parser('declare-materials');materials.add_argument('--task',required=True);materials.add_argument('--file',required=True)
    export=sub.add_parser('export-materials');export.add_argument('--task',nargs='+',required=True);export.add_argument('--output',required=True)
    request=sub.add_parser('request');request.add_argument('--file',required=True)
    pose=sub.add_parser('prepare-pose');pose.add_argument('--task',required=True);pose.add_argument('--file',required=True)
    camera=sub.add_parser('enable-camera');camera.add_argument('--task',required=True);camera.add_argument('--regions-file',required=True)
    display=sub.add_parser('display')
    display.add_argument('--output',required=True)
    preview=sub.add_parser('preview-selection')
    for name in ('task','stage','output'):preview.add_argument('--'+name,required=True)
    review = sub.add_parser('review')
    for name in ('task','stage','decision'):
        review.add_argument('--'+name, required=True)
    configure = sub.add_parser('configure')
    repair = sub.add_parser('repair')
    for command in (configure, repair):
        command.add_argument('--task', required=True)
        command.add_argument('--stage', required=True)
        command.add_argument('--file', required=True)
    repair.add_argument('--attempt', required=True)
    docs = sub.add_parser('documents')
    docs.add_argument('paths', nargs='+')
    docs.add_argument('--record-read', action='store_true')
    docs.add_argument('--show',action='store_true')
    docs.add_argument('--section')
    docs.add_argument('--refresh',action='store_true')
    docs.add_argument('--max-chars',type=int,default=10000)
    args = parser.parse_args()
    try:
        if args.command == 'create-video':
            from plan_templates import from_video
            if Path(args.plan).exists():
                raise ValueError('Plan exists; resume it')
            config=from_video(args.video,args.workspace,args.image_profile)
            from package_delivery import archive_name,source_file
            for manifest in args.materials_file:
                for role,item in read(manifest)['files'].items():
                    name=archive_name(role)
                    if name in config['assets']:raise ValueError('Duplicate imported material role')
                    source=source_file(item['path'],Path(manifest).resolve().parent)
                    if file_digest(source)!=item['sha256']:raise ValueError('Imported material changed: '+name)
                    config['assets'][name]=str(source)
            save(args.plan,config)
            print(json.dumps({'status':'created','plan':str(Path(args.plan).resolve())}))
            return
        if args.command == 'create':
            from plan_templates import create
            if Path(args.plan).exists():
                raise ValueError('Plan exists; resume it')
            character = read(args.character_plan)
            if any(t['status']=='completed' for t in character['tasks']):
                raise ValueError('Existing work needs its saved execution plan, not a fresh run')
            config = create(character,args.workspace,args.image_profile,args.video_profile,args.pose_provider,args.background_mode)
            config['character_plan'] = str(Path(args.character_plan).resolve())
            save(args.plan,config)
            print(json.dumps({'status':'created','plan':str(Path(args.plan).resolve()),
                              'next':'Fill prompt/reference/duration parameters, then run'}))
            return
        plan = Plan(args.plan)
        if args.command=='declare-materials':
            values=read(args.file)
            with workspace_lock(plan.workspace/'work/execution-plan'):
                plan=Plan(args.plan)
                task=next(t for t in plan.config['tasks'] if t['id']==args.task)
                if plan.state['tasks'].get(args.task,{}).get('status')=='completed':
                    raise ValueError('Do not change materials of a completed task')
                assets=dict(task.get('assets',{}))
                for role,value in values.items():
                    path=Path(value).resolve()
                    if not path.is_file() or (role in assets and assets[role]!=str(path)):
                        raise ValueError('Missing material or conflicting role: '+role)
                    assets[role]=str(path)
                task['assets']=assets;save(plan.path,plan.config)
            print(json.dumps({'task':args.task,'declared_materials':len(values)}))
            return
        if args.command=='set-video-profile':
            profile=Path(args.file).resolve();data=read(profile)
            if data.get('kind')!='video' or not data.get('bindings') or not data.get('generation'):
                raise ValueError('Provide a validated video profile')
            with workspace_lock(plan.workspace/'work/execution-plan'):
                plan=Plan(args.plan)
                plan.config['video_profile']=str(profile)
                save(plan.path,plan.config)
            print(json.dumps({'video_profile':str(profile),'scope':'future_tasks','existing_tasks_changed':False}))
            return
        if args.command == 'extend':
            from plan_templates import create
            with workspace_lock(plan.workspace/'work/execution-plan'):
                plan = Plan(args.plan)
                first = next(t for t in plan.config['tasks'] if t.get('character_task'))
                video = plan.config.get('video_profile') or next(s for s in first['steps'] if s['operation']=='video')['args']['profile']
                image = next(s for s in first['steps'] if s['operation'] in ('finish','jump_finish'))['args']['image_profile']
                generated = create(read(args.character_plan),plan.workspace,image,video,
                                   plan.config.get('pose_provider','gpt_image'),plan.config.get('background_mode','plain'))
                existing = {t['id'] for t in plan.config['tasks']}
                plan.config['tasks'].extend(t for t in generated['tasks'] if t['id'] not in existing)
                save(plan.path,plan.config)
            result = {'status':'extended','plan':str(plan.path)}
        elif args.command == 'configure':
            result = plan.configure(args.task,args.stage,read(args.file))
        elif args.command == 'request':
            result = plan.request(read(args.file))
        elif args.command == 'prepare-pose':
            result = plan.prepare_pose(args.task,read(args.file))
        elif args.command == 'enable-camera':
            result = plan.enable_camera(args.task,args.regions_file)
        elif args.command == 'repair':
            result = plan.repair(args.task,args.stage,args.file,args.attempt)
        elif args.command == 'run':
            result = plan.run()
        elif args.command == 'display':
            result = plan.display(args.output)
        elif args.command == 'preview-selection':
            result=plan.preview_selection(args.task,args.stage,args.output)
        elif args.command == 'delivery':
            result = {'deliveries':plan.deliveries()}
        elif args.command == 'export-materials':
            result=plan.export_materials(args.task,args.output)
        elif args.command == 'review':
            result = plan.review(args.task,args.stage,args.decision)
        elif args.command == 'documents':
            if args.show and args.record_read:raise ValueError('show records emitted content; do not combine with record-read')
            result = (plan.read_documents(args.paths,args.section,args.refresh,args.max_chars) if args.show else
                      plan.record_documents(args.paths) if args.record_read else plan.documents(args.paths))
        else:
            result = {'state':str(plan.state_path), 'tasks':{k:{'status':v['status'],
                      'stages':{s:r['status'] for s,r in v['steps'].items()}}
                      for k,v in plan.state['tasks'].items()}}
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, str(exc)+'\n')


if __name__ == '__main__':
    main()
