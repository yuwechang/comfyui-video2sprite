"""Persist one character's stance/action plan; never submits generation jobs."""
import argparse
import json
from pathlib import Path
import re

STANCES = ('normal', 'combat')
ACTIONS = {'idle': 'loop', 'walk': 'loop', 'run': 'loop',
           'jump': 'hold_end_pose', 'death': 'hold_end_pose'}
ENVIRONMENTS = ('ground', 'air')
MOTION_TYPES = ('loop', 'return_to_start', 'hold_end_pose')


def plan_path(workspace):
    return Path(workspace).resolve() / 'work/character/plan.json'


def load(workspace):
    return json.loads(plan_path(workspace).read_text(encoding='utf-8'))


def save(workspace, plan):
    path = plan_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix('.tmp')
    pending.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    pending.replace(path)
    return plan


def choices(values, allowed):
    if not values or any(v not in allowed for v in values):
        raise ValueError('Choose from: ' + ', '.join(allowed))
    return list(dict.fromkeys(values))


def file_path(value):
    path = Path(value).resolve()
    if not path.is_file():
        raise ValueError(f'Missing file: {path}')
    return str(path)


def task(stance, action, description, motion_type, environment='ground', pipeline='standard'):
    identifier = f'{stance}-{action}'
    dependency = f'{stance}-jump' if environment == 'air' and pipeline != 'jump' else f'{stance}-idle'
    return {'id': identifier, 'stance': stance, 'action': action, 'description': description,
            'environment': environment, 'pipeline': pipeline,
            'entry_reference': 'stance_reference' if action == 'idle' else
                               ('airborne' if environment == 'air' and pipeline != 'jump' else 'idle'),
            'vertical_alignment': 'waist' if environment == 'air' else 'none',
            'motion_type': motion_type, 'status': 'pending',
            'depends_on': [] if action == 'idle' else [dependency],
            'job': f'work/character/tasks/{identifier}',
            'output': f'outputs/character/{identifier}', 'artifacts': {}}


def initialize(workspace, reference, stances, actions=(), side=256):
    if plan_path(workspace).exists():
        raise ValueError('This workspace already has a character; reuse it. Use a new chat/workspace for another character.')
    stances = choices(stances, STANCES)
    if any(action not in ACTIONS or action == 'idle' for action in actions):
        raise ValueError('Additional actions: walk, run, jump, death; Idle is automatic')
    if type(side) is not int or side <= 0:
        raise ValueError('Character side must be a positive integer')
    selected = ['idle'] + list(dict.fromkeys(actions))
    plan = {'reference': file_path(reference), 'facing': 'right', 'side': side,
            'stances': {stance: {'reference': None, 'preparation': None, 'idle_frame': None}
                        for stance in stances},
            'airborne': {stance: None for stance in stances},
            'tasks': [task(stance, action, action, ACTIONS[action],
                           'air' if action == 'jump' else 'ground',
                           'jump' if action == 'jump' else 'standard')
                      for action in selected for stance in stances]}
    return save(workspace, plan)


def add_action(workspace, stances, description, motion_type, environment):
    plan = load(workspace)
    stances = choices(stances, STANCES)
    if not description.strip() or motion_type not in MOTION_TYPES or environment not in ENVIRONMENTS:
        raise ValueError('A description, valid motion type and explicit ground/air environment are required')
    # A newly selected stance gets its own Idle before any added action.
    for stance in stances:
        if stance not in plan['stances']:
            plan['stances'][stance] = {'reference': None, 'preparation': None, 'idle_frame': None}
            plan['airborne'][stance] = None
            plan['tasks'].append(task(stance, 'idle', 'idle', 'loop'))
        if environment == 'air' and not any(t['id'] == f'{stance}-jump' for t in plan['tasks']):
            plan['tasks'].append(task(stance, 'jump', 'jump', 'hold_end_pose', 'air', 'jump'))
    number = 1
    while any(t['action'] == f'custom-{number:03d}' for t in plan['tasks']):
        number += 1
    for stance in stances:
        plan['tasks'].append(task(stance, f'custom-{number:03d}', description.strip(), motion_type,
                                  environment, 'airborne' if environment == 'air' else 'standard'))
    return save(workspace, plan)


def record_stance(workspace, stance, reference, preparation, idle_frame):
    plan = load(workspace)
    if stance not in plan['stances']:
        raise ValueError('Stance is not in this character plan')
    plan['stances'][stance] = {key: file_path(value) for key, value in
                              [('reference', reference), ('preparation', preparation), ('idle_frame', idle_frame)]}
    return save(workspace, plan)


def record_airborne(workspace, stance, profile):
    plan = load(workspace)
    if stance not in plan['stances']:
        raise ValueError('Stance is not in this character plan')
    plan['airborne'][stance] = file_path(profile)
    return save(workspace, plan)


def update_task(workspace, identifier, status, artifacts=None):
    plan = load(workspace)
    current = next((t for t in plan['tasks'] if t['id'] == identifier), None)
    if current is None or status not in ('pending', 'running', 'needs_review', 'completed'):
        raise ValueError('Unknown task or status')
    if status in ('running', 'completed'):
        completed = {t['id'] for t in plan['tasks'] if t['status'] == 'completed'}
        if any(dep not in completed for dep in current['depends_on']):
            raise ValueError('Complete the corresponding Idle or jump dependency first')
        if current['entry_reference'] == 'airborne':
            profile = plan['airborne'][current['stance']]
            if not profile:
                raise ValueError('Record the corresponding airborne reference first')
            file_path(profile)
        elif current['depends_on'] and not all(plan['stances'][current['stance']].values()):
            raise ValueError('Record the stance reference, preparation and usable Idle frame first')
    assets = dict(current['artifacts'])
    for key, value in (artifacts or {}).items():
        if not re.fullmatch(r'[a-z][a-z0-9_]*', key):
            raise ValueError('Artifact keys must be lowercase identifiers')
        assets[key] = file_path(value)
    required = ('source_video', 'rise_animation', 'fall_animation', 'airborne_profile') if current['pipeline'] == 'jump' else ('source_video', 'animation')
    if status == 'completed' and not all(key in assets for key in required):
        raise ValueError('Completed tasks require ' + ', '.join(required) + ' artifacts')
    current.update(status=status, artifacts=assets)
    return save(workspace, plan)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', default='.')
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--reference', required=True)
    init.add_argument('--stances', nargs='+', choices=STANCES, required=True)
    init.add_argument('--actions', nargs='*', choices=tuple(k for k in ACTIONS if k != 'idle'), default=[])
    init.add_argument('--side', type=int, default=256)
    add = commands.add_parser('add')
    add.add_argument('--stances', nargs='+', choices=STANCES, required=True)
    add.add_argument('--description', required=True)
    add.add_argument('--motion-type', choices=MOTION_TYPES, required=True)
    add.add_argument('--environment', choices=ENVIRONMENTS, required=True)
    airborne = commands.add_parser('record-airborne')
    airborne.add_argument('--stance', choices=STANCES, required=True)
    airborne.add_argument('--profile', required=True)
    record = commands.add_parser('record-stance')
    record.add_argument('--stance', choices=STANCES, required=True)
    for key in ('reference', 'preparation', 'idle-frame'):
        record.add_argument('--'+key, required=True)
    mark = commands.add_parser('mark')
    mark.add_argument('--task', required=True)
    mark.add_argument('--status', choices=('pending', 'running', 'needs_review', 'completed'), required=True)
    mark.add_argument('--artifacts', help='JSON file mapping artifact names to existing file paths')
    commands.add_parser('show')
    args = parser.parse_args()
    try:
        if args.command == 'init':
            result = initialize(args.workspace, args.reference, args.stances, args.actions, args.side)
        elif args.command == 'add':
            result = add_action(args.workspace, args.stances, args.description, args.motion_type, args.environment)
        elif args.command == 'record-airborne':
            result = record_airborne(args.workspace, args.stance, args.profile)
        elif args.command == 'record-stance':
            result = record_stance(args.workspace, args.stance, args.reference, args.preparation, args.idle_frame)
        elif args.command == 'mark':
            artifacts = json.loads(Path(args.artifacts).read_text(encoding='utf-8-sig')) if args.artifacts else None
            result = update_task(args.workspace, args.task, args.status, artifacts)
        else:
            result = load(args.workspace)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
