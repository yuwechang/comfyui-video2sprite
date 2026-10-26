"""Execute a configured image workflow; job folders resume without resubmission."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
import uuid
from PIL import Image
import generate as g


def process(profile_path, image_path, prompt, job, timeout=1800):
    import websocket
    folder = Path(job).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / 'job.json'
    profile = json.loads(Path(profile_path).read_text(encoding='utf-8'))
    fingerprint = hashlib.sha256(Path(profile_path).read_bytes() + Path(image_path).read_bytes()
                                 + prompt.encode('utf-8')).hexdigest()
    ws = None
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state.get('fingerprint') != fingerprint:
            raise ValueError('Job inputs changed; use a new job directory')
        if state.get('status') == 'complete' and Path(state['file']).exists():
            return state
        if not state.get('prompt_id'):
            raise ValueError('Submission has no confirmed ID; inspect queue before retrying')
    else:
        graph = g.build_graph(profile, {'image_1': g.upload(profile['url'], image_path),
                                      'positive_prompt': prompt})
        g.save(folder / 'submitted-workflow.json', graph)
        client_id = uuid.uuid4().hex
        base = profile['url'].rstrip('/')
        ws_url = ('wss' if base.startswith('https:') else 'ws') + base[base.index(':'):] + '/ws?' + urlencode({'clientId': client_id})
        try:
            ws = websocket.create_connection(ws_url, timeout=10)
        except (websocket.WebSocketException, OSError):
            pass
        state = {'url': base, 'fingerprint': fingerprint, 'status': 'submitting',
                 'client_id': client_id, 'output_node': str(profile['output_node'])}
        g.save(state_path, state)
        result = g.request(base, '/prompt', {'prompt': graph, 'client_id': client_id})
        if not result.get('prompt_id') or result.get('node_errors'):
            raise ValueError(json.dumps(result, ensure_ascii=False)[:3000])
        state.update({'prompt_id': result['prompt_id'], 'status': 'waiting'})
        g.save(state_path, state)
    try:
        history = g.wait_for_result(state['url'], state['prompt_id'], ws, timeout, state_path, state)
        g.save(folder / 'history.json', history)
        candidates = {}
        for item in g.descriptors(history.get('outputs', {}).get(state['output_node'], {})):
            if Path(item['filename']).suffix.lower() in ('.png', '.webp', '.jpg', '.jpeg'):
                query = {key: item.get(key, default) for key, default in
                         [('filename', ''), ('subfolder', ''), ('type', 'output')]}
                candidates[json.dumps(query, sort_keys=True)] = query
        if len(candidates) != 1:
            raise ValueError(f'Expected one output image, found {len(candidates)}; inspect history.json')
        query = next(iter(candidates.values()))
        target = folder / ('result' + Path(query['filename']).suffix.lower())
        with urlopen(state['url'] + '/view?' + urlencode(query), timeout=120) as source:
            with target.open('wb') as destination:
                while chunk := source.read(1024 * 1024):
                    destination.write(chunk)
        with Image.open(target) as image:
            image.load()
            details = {'width': image.width, 'height': image.height, 'mode': image.mode,
                       'alpha_extrema': image.getchannel('A').getextrema() if 'A' in image.getbands() else None}
        state.update({'status': 'complete', 'file': str(target), 'image': details})
        g.save(state_path, state)
        return state
    finally:
        if ws:
            ws.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--prompt-file', required=True)
    parser.add_argument('--job', required=True)
    parser.add_argument('--timeout', type=float, default=1800)
    args = parser.parse_args()
    try:
        state = process(args.profile, args.image, Path(args.prompt_file).read_text(encoding='utf-8'), args.job, args.timeout)
        print(json.dumps({key: state[key] for key in ('status', 'file', 'image')}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
