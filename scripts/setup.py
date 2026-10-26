"""Local environment checks and ComfyUI API workflow inspection (Python 3.10+)."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import urlopen
from urllib.parse import urlparse, quote


def fetch(base, route):
    if urlparse(base).scheme not in ('http', 'https'):
        raise ValueError('ComfyUI URL must use http or https')
    with urlopen(base.rstrip('/') + route, timeout=8) as response:
        return json.load(response)


def executable(name):
    path = shutil.which(name)
    if not path:
        return {'available': False}
    try:
        result = subprocess.run([path, '-version'], capture_output=True,
                                text=True, timeout=10)
        return {'available': result.returncode == 0, 'path': path,
                'version': result.stdout.splitlines()[0] if result.stdout else ''}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'available': False, 'error': str(exc)}


def check(url):
    report = {'python': {'available': sys.version_info >= (3, 10),
                         'path': sys.executable, 'version': sys.version.split()[0]},
              'ffmpeg': executable('ffmpeg'), 'ffprobe': executable('ffprobe'),
              'packages': {name: importlib.util.find_spec(module) is not None
                           for name, module in [('Pillow', 'PIL'),
                                                ('websocket-client', 'websocket')]}}
    try:
        info = fetch(url, '/system_stats')
        if not isinstance(info, dict) or 'system' not in info:
            raise ValueError('Endpoint did not return ComfyUI system statistics')
        report['comfyui'] = {'available': True, 'url': url}
    except Exception as exc:
        report['comfyui'] = {'available': False, 'url': url, 'error': str(exc)}
    return report


def read_workflow(path):
    graph = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(graph, dict) or not graph or 'nodes' in graph:
        raise ValueError('Provide an API-format workflow, not the UI graph export')
    for node_id, node in graph.items():
        if not isinstance(node, dict) or not isinstance(node.get('inputs'), dict) or not isinstance(node.get('class_type'), str):
            raise ValueError(f'Invalid API node: {node_id}')
    return graph


def inspect(path, url, output):
    graph = read_workflow(path)
    # Query only classes in this workflow; never print the full server catalogue.
    classes = {}
    for cls in sorted({node['class_type'] for node in graph.values()}):
        classes.update(fetch(url, '/object_info/' + quote(cls, safe='')))
    nodes, missing = [], []
    for node_id, node in graph.items():
        cls = node['class_type']
        schema = classes.get(cls)
        if schema is None:
            missing.append(cls)
        definitions = (schema or {}).get('input', {})
        fields = {}
        for name, value in node['inputs'].items():
            definition = definitions.get('required', {}).get(name,
                         definitions.get('optional', {}).get(name))
            fields[name] = {'value': value, 'schema': definition}
        nodes.append({'id': node_id, 'class_type': cls,
                      'title': node.get('_meta', {}).get('title'),
                      'output_node': (schema or {}).get('output_node', False),
                      'inputs': fields})
    report = {'workflow': str(Path(path).resolve()), 'nodes': nodes,
              'missing_node_classes': sorted(set(missing))}
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'node_count': len(nodes), 'missing_node_classes': report['missing_node_classes'],
            'inspection_file': str(Path(output).resolve())}


def bind(workflow, mapping, url, output, kind='video'):
    graph = read_workflow(workflow)
    config = json.loads(Path(mapping).read_text(encoding='utf-8-sig'))
    required = ({'image_1', 'image_2', 'positive_prompt', 'width', 'height', 'length', 'seed'}
                if kind == 'video' else {'image_1', 'positive_prompt'})
    bindings = config['bindings']
    if not required.issubset(bindings):
        raise ValueError('Missing bindings: ' + ', '.join(sorted(required - bindings.keys())))
    schemas = {}
    for role, targets in bindings.items():
        if not isinstance(targets, list) or not targets:
            raise ValueError(f'{role}: provide a nonempty list of node/input targets')
        for target in targets:
            node_id, field = str(target['node']), target['input']
            if node_id not in graph or field not in graph[node_id]['inputs']:
                raise ValueError(f'{role}: unknown field {node_id}.{field}')
            value = graph[node_id]['inputs'][field]
            if isinstance(value, list) and target.get('mode') != 'replace_link':
                raise ValueError(f'{role}: map the upstream literal input, not a linked socket')
            cls = graph[node_id]['class_type']
            if cls not in schemas:
                schemas.update(fetch(url, '/object_info/' + quote(cls, safe='')))
            schema = schemas.get(cls, {}).get('input', {})
            if field not in schema.get('required', {}) and field not in schema.get('optional', {}):
                raise ValueError(f'{role}: field absent from installed node schema')
    output_id = str(config['output_node'])
    if output_id not in graph:
        raise ValueError('Unknown output node')
    cls = graph[output_id]['class_type']
    output_schema = fetch(url, '/object_info/' + quote(cls, safe='')).get(cls, {})
    if not output_schema.get('output_node'):
        raise ValueError('Selected node is not an output node')
    if kind == 'video':
        rules = config['generation']
        rules.setdefault('max_pixels', 1_000_000)
        if type(rules['max_pixels']) is not int or rules['max_pixels'] <= 0:
            raise ValueError('generation.max_pixels must be a positive integer')
        for name in ('width_multiple', 'height_multiple', 'frame_step', 'frame_min'):
            if type(rules[name]) is not int or rules[name] <= 0:
                raise ValueError(f'generation.{name} must be a positive integer')
        if type(rules['frame_offset']) is not int or rules['length_unit'] not in ('frames', 'seconds'):
            raise ValueError('Invalid frame_offset or length_unit')
        if not isinstance(rules['fps'], (float, int)) or rules['fps'] <= 0:
            raise ValueError('generation.fps must be positive')
    config.update({'kind': kind, 'url': url, 'workflow': graph,
                   'workflow_sha256': hashlib.sha256(Path(workflow).read_bytes()).hexdigest(),
                   'verification': 'bindings_checked_generation_not_tested'})
    destination = Path(output)
    if destination.exists():
        raise ValueError('Output exists; choose a new filename to preserve existing settings')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'profile': str(destination.resolve()), 'verification': config['verification']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8188')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('check')
    scan = sub.add_parser('inspect')
    scan.add_argument('workflow')
    scan.add_argument('--output', required=True)
    save = sub.add_parser('bind')
    save.add_argument('workflow')
    save.add_argument('mapping')
    save.add_argument('--output', required=True)
    save.add_argument('--kind', choices=['video', 'image'], default='video')
    args = parser.parse_args()
    try:
        if args.command == 'check':
            report = check(args.url)
        elif args.command == 'inspect':
            report = inspect(args.workflow, args.url, args.output)
        else:
            report = bind(args.workflow, args.mapping, args.url, args.output, args.kind)
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
