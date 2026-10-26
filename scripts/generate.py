"""Apply a local workflow profile, submit once, wait locally, and fetch video."""
import argparse
import copy
import json
import math
import mimetypes
from pathlib import Path
import subprocess
import time
import uuid
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def request(base, route, payload=None, headers=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(base.rstrip('/') + route, data=data,
                  headers=headers or ({'Content-Type': 'application/json'} if data else {}))
    try:
        with urlopen(req, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f'HTTP {exc.code}: {exc.read().decode(errors="replace")[:3000]}') from exc


def upload(base, path):
    path = Path(path)
    boundary = uuid.uuid4().hex
    name = uuid.uuid4().hex + path.suffix.lower()
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
            f'Content-Type: {mimetypes.guess_type(name)[0] or "application/octet-stream"}\r\n\r\n').encode()
    body += path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
    req = Request(base.rstrip('/') + '/upload/image', data=body,
                  headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    with urlopen(req, timeout=60) as response:
        result = json.load(response)
    return '/'.join(filter(None, [result.get('subfolder'), result['name']]))


def align_frames(seconds, rules):
    fps = rules['fps']
    minimum = max(rules['frame_min'], math.ceil(seconds * fps))
    count = rules['frame_offset'] + max(0, math.ceil(
        (minimum - rules['frame_offset']) / rules['frame_step'])) * rules['frame_step']
    if count > rules.get('frame_max', float('inf')):
        raise ValueError('Requested duration exceeds workflow frame limit')
    return count


def build_graph(profile, values, omit_second=False):
    graph = copy.deepcopy(profile['workflow'])
    if omit_second:
        mode = profile['image_2_mode']
        if not isinstance(mode, dict) or not mode.get('optional'):
            raise ValueError('This profile requires a second image')
        for target in mode['omit_inputs']:
            graph[str(target['node'])]['inputs'].pop(target['input'], None)
    for role, value in values.items():
        targets = profile['bindings'].get(role)
        if not targets:
            raise ValueError(f'No binding for {role}')
        for target in targets:
            inputs = graph[str(target['node'])]['inputs']
            if isinstance(inputs.get(target['input']), list) and target.get('mode') != 'replace_link':
                raise ValueError(f'{role}: replacing a link requires explicit profile mode')
            inputs[target['input']] = value
    # Submit only ancestors of the selected output; unrelated output nodes are not executed.
    reachable = set()
    def visit(node_id):
        if node_id in reachable:
            return
        reachable.add(node_id)
        for value in graph[node_id]['inputs'].values():
            if isinstance(value, list) and len(value) == 2 and str(value[0]) in graph:
                visit(str(value[0]))
    visit(str(profile['output_node']))
    return {key: node for key, node in graph.items() if key in reachable}


def history_result(base, prompt_id):
    item = request(base, '/history/' + prompt_id).get(prompt_id)
    if not item:
        return None
    status = item.get('status', {})
    if status.get('status_str') == 'error':
        errors = [data for kind, data in status.get('messages', [])
                  if kind in ('execution_error', 'execution_interrupted')]
        raise RuntimeError(json.dumps(errors, ensure_ascii=False)[:3000])
    return item if status.get('completed') else None


def wait_for_result(base, prompt_id, ws, timeout, state_path, state):
    import websocket
    deadline = time.monotonic() + timeout
    next_history = time.monotonic()  # Covers resumed tasks and lost completion events.
    while time.monotonic() < deadline:
        if time.monotonic() >= next_history:
            result = history_result(base, prompt_id)
            if result:
                return result
            next_history = time.monotonic() + (60 if ws else 15)
        if ws:
            try:
                ws.settimeout(min(10, max(.1, deadline - time.monotonic())))
                raw = ws.recv()
                if not raw:
                    ws.close()
                    ws = None
                    continue
                if not isinstance(raw, str):
                    continue
                message = json.loads(raw)
                data = message.get('data', {})
                if data.get('prompt_id') != prompt_id:
                    continue
                kind = message.get('type')
                if kind in ('execution_error', 'execution_interrupted'):
                    raise RuntimeError(json.dumps(data, ensure_ascii=False)[:3000])
                if kind == 'executing' and data.get('node') is not None:
                    state['current_node'] = data['node']
                    save(state_path, state)
                if kind == 'execution_success' or (kind == 'executing' and data.get('node') is None):
                    next_history = 0
            except websocket.WebSocketTimeoutException:
                pass
            except (websocket.WebSocketException, OSError):
                ws.close()
                ws = None
        else:
            time.sleep(min(5, max(0, deadline - time.monotonic())))
    raise TimeoutError('Wait timed out; resume with the same job directory. Task was not cancelled.')


def descriptors(value):
    if isinstance(value, dict):
        if isinstance(value.get('filename'), str):
            yield value
        else:
            for child in value.values():
                yield from descriptors(child)
    elif isinstance(value, list):
        for child in value:
            yield from descriptors(child)


def download(base, history, output_node, folder):
    videos, seen = [], set()
    for item in descriptors(history.get('outputs', {}).get(str(output_node), {})):
        if Path(item['filename']).suffix.lower() not in ('.mp4', '.webm', '.mov', '.mkv', '.avi'):
            continue
        query = {key: item.get(key, default) for key, default in
                 [('filename', ''), ('subfolder', ''), ('type', 'output')]}
        signature = json.dumps(query, sort_keys=True)
        if signature in seen:
            continue
        seen.add(signature)
        target = folder / f'video-{len(videos) + 1}{Path(item["filename"]).suffix.lower()}'
        with urlopen(base.rstrip('/') + '/view?' + urlencode(query), timeout=120) as source:
            with target.open('wb') as destination:
                while chunk := source.read(1024 * 1024):
                    destination.write(chunk)
        probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                '-show_entries', 'stream=width,height,avg_frame_rate,nb_frames:format=duration',
                                '-of', 'json', str(target)], capture_output=True, text=True, check=True)
        info = json.loads(probe.stdout)
        if not info.get('streams'):
            raise ValueError('Downloaded output has no video stream')
        videos.append({'path': str(target.resolve()), 'info': info})
    if not videos:
        raise ValueError('Selected output has no downloadable video descriptor; inspect history.json')
    return videos


def run(args):
    import websocket
    folder = Path(args.job).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / 'job.json'
    ws = None
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state.get('status') == 'complete':
            return state
        if not state.get('prompt_id'):
            raise ValueError('Prior submission has no confirmed ID; inspect queue before retrying')
        base = state['url']
    else:
        profile = json.loads(Path(args.profile).read_text(encoding='utf-8'))
        base = profile['url']
        rules = profile['generation']
        if not args.image or not args.prompt_file:
            raise ValueError('A new job requires --image and --prompt-file')
        frames = align_frames(args.seconds, rules)
        values = {'positive_prompt': Path(args.prompt_file).read_text(encoding='utf-8'),
                  'width': math.ceil(args.width / rules['width_multiple']) * rules['width_multiple'],
                  'height': math.ceil(args.height / rules['height_multiple']) * rules['height_multiple'],
                  'length': frames if rules['length_unit'] == 'frames' else frames / rules['fps'],
                  'seed': args.seed}
        for dimension in ('width', 'height'):
            if not rules.get(dimension + '_min', 1) <= values[dimension] <= rules.get(dimension + '_max', float('inf')):
                raise ValueError(f'{dimension} outside profile limits')
        if 'fps' in profile['bindings']:
            values['fps'] = rules['fps']
        values['image_1'] = upload(base, args.image)
        if args.image2:
            values['image_2'] = upload(base, args.image2)
        graph = build_graph(profile, values, omit_second=not args.image2)
        save(folder / 'submitted-workflow.json', graph)
        client_id = uuid.uuid4().hex
        ws_url = ('wss' if base.startswith('https:') else 'ws') + base[base.index(':'):] + '/ws?' + urlencode({'clientId': client_id})
        try:
            ws = websocket.create_connection(ws_url, timeout=10)
        except (websocket.WebSocketException, OSError):
            ws = None
        state = {'url': base, 'client_id': client_id, 'status': 'submitting',
                 'output_node': str(profile['output_node']), 'width': values['width'],
                 'height': values['height'], 'frames': frames, 'fps': rules['fps'], 'seed': args.seed}
        save(state_path, state)
        # Never automatically repeat POST /prompt: a lost response may still mean acceptance.
        result = request(base, '/prompt', {'prompt': graph, 'client_id': client_id})
        if result.get('node_errors') or not result.get('prompt_id'):
            raise ValueError(json.dumps(result, ensure_ascii=False)[:3000])
        state.update({'prompt_id': result['prompt_id'], 'status': 'waiting'})
        save(state_path, state)
    try:
        result = wait_for_result(base, state['prompt_id'], ws, args.timeout, state_path, state)
        save(folder / 'history.json', result)
        videos = download(base, result, state['output_node'], folder)
        state.update({'status': 'complete', 'videos': videos})
        save(state_path, state)
        return state
    finally:
        if ws:
            ws.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='.local/profile.json')
    parser.add_argument('--job', required=True)
    parser.add_argument('--image')
    parser.add_argument('--image2')
    parser.add_argument('--prompt-file')
    parser.add_argument('--width', type=int, default=768)
    parser.add_argument('--height', type=int, default=768)
    parser.add_argument('--seconds', type=float, default=2.4)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--timeout', type=float, default=3600)
    args = parser.parse_args()
    if min(args.width, args.height, args.seconds, args.timeout) <= 0:
        parser.error('dimensions, duration and timeout must be positive')
    try:
        print(json.dumps(run(args), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc), 'job': args.job}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
