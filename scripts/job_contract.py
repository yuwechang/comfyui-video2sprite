"""Check immutable task inputs before writing preparation artifacts."""
import hashlib
import json
from pathlib import Path
from generate import save


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def guard_inputs(job, files, parameters, name="entry-inputs.json"):
    contract = {'files': {k: file_digest(v) for k, v in files.items() if v is not None},
                'parameters': parameters}
    contract = json.loads(json.dumps(contract, default=str))
    target = Path(job) / name
    if target.exists() and json.loads(target.read_text(encoding='utf-8')) != contract:
        raise ValueError('Task inputs changed; use a new job directory')
    save(target, contract)
