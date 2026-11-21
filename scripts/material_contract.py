"""Validate material roles against the completed data flow, not a directory scan."""
from pathlib import Path
from job_contract import file_digest

def requirements(plan, task_id, inventory, files):
    indexed={str(Path(item['path']).resolve()):item for item in inventory.values()}
    archived={str(Path(path).resolve()):name for name,path in files.items()}
    needed={}
    def add(role,path):
        path=str(Path(path).resolve())
        if path not in indexed or path not in archived:raise ValueError('Missing registered material role: '+role)
        digest=file_digest(path)
        if indexed[path]['sha256']!=digest:raise ValueError('Material changed: '+role)
        needed[role]={'path':archived[path],'sha256':digest}
    for name,path in plan.config.get('assets',{}).items():
        if isinstance(path,str):add('common/'+name,path)
    tasks={t['id']:t for t in plan.config['tasks']};visited=set()
    def visit(identifier):
        if identifier in visited:return
        visited.add(identifier);task=tasks[identifier]
        for role,path in task.get('assets',{}).items():add(identifier+'/declared/'+role,path)
        for parent in task.get('depends_on',[]):visit(parent)
        for step in task['steps']:
            record=plan.state['tasks'].get(identifier,{}).get('steps',{}).get(step['id'],{})
            if record.get('status')!='completed':continue
            args=plan.resolve(step['args'])
            for field in ('image','prompt_file','remove_effects_prompt_file','regions_file','reference_geometry','standing_reference','preparation','background_profile'):
                if args.get(field):add(identifier+'/'+step['id']+'/'+field,args[field])
            if args.get('foreground',{}).get('profile') and record.get('result',{}).get('sampling',{}).get('strategy')!='explicit':
                add(identifier+'/'+step['id']+'/foreground/profile',args['foreground']['profile'])
            if record.get('result',{}).get('analysis_metadata'):
                add(identifier+'/'+step['id']+'/analysis_metadata',record['result']['analysis_metadata'])
            normalized=record.get('result',{}).get('keyframe_background')
            if normalized:
                for field in ('background','report_file','profile'):
                    add(identifier+'/'+step['id']+'/keyframe_background/'+field,normalized[field])
                for field in ('images','source_images'):
                    for i,path in enumerate(normalized[field]):
                        add(identifier+'/'+step['id']+'/keyframe_background/'+field+'/'+str(i),path)
            sampling=record.get('result',{}).get('sampling',{})
            if sampling.get('method')=='pose':
                for field in ('pose_report','pose_landmarks','pose_transition_report','pose_contract'):
                    add(identifier+'/'+step['id']+'/'+field,sampling[field])
                add(identifier+'/'+step['id']+'/pose_evidence',sampling['pose_evidence']['path'])
            if step['operation']=='pose_reference':
                result=record['result']
                for i,entry in enumerate(result.get('lineage',[])+[result['record']]):
                    for field in ('reference','prompt_file','file'):
                        add(identifier+'/pose/'+str(i)+'/'+field,entry[field])
    visit(task_id)
    return needed
