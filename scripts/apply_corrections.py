"""Adopt reviewed frame replacements and rebuild delivery without image generation."""
import argparse
import copy
import json
from pathlib import Path
from PIL import Image
from finish_animation import finish_refined, variant_summary
from airborne_pipeline import split_jump
from generate import save


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def apply(summary_path, corrections_path, job, output):
    summary_path, corrections_path = Path(summary_path).resolve(), Path(corrections_path).resolve()
    summary, corrections = read(summary_path), read(corrections_path)
    jump = 'split' in summary
    paired = read(summary['joint_summary']) if jump else summary
    variants = copy.deepcopy(paired['variants'])
    if not corrections or set(corrections) - set(variants):
        raise ValueError('Corrections must name existing effect variants')
    job, output = Path(job).resolve(), Path(output).resolve()
    if job.exists() or output.exists():
        raise ValueError('Use new correction job and output directories')
    replacements = []
    # Validate every replacement before writing any delivery files.
    for variant, entries in corrections.items():
        if not entries:
            raise ValueError('Correction entries must not be empty')
        report = variants[variant]
        for index, item in entries.items():
            if str(int(index)) != index or int(index) not in report['sample_indices']:
                raise ValueError('Correction index must identify a selected source frame')
            order = report['sample_indices'].index(int(index))
            record = report['refinement'][order]
            image_path, prompt_path = [Path(item[k]) for k in ('image', 'prompt')]
            image_path = image_path if image_path.is_absolute() else corrections_path.parent/image_path
            prompt_path = prompt_path if prompt_path.is_absolute() else corrections_path.parent/prompt_path
            prompt = prompt_path.read_text(encoding='utf-8-sig')
            if not prompt.strip():
                raise ValueError('Correction prompt must not be empty')
            with Image.open(record['input']) as original, Image.open(image_path) as candidate:
                if candidate.size != original.size or 'A' not in candidate.getbands():
                    raise ValueError('Correction must match original padded input dimensions and contain alpha')
                frame = candidate.convert('RGBA')
                padding = record['padding']
                frame = frame.crop((0, 0, frame.width-padding[0], frame.height-padding[1]))
                low, high = frame.getchannel('A').getextrema()
                if low != 0 or high < 128:
                    raise ValueError('Correction is opaque or empty')
            background_record={}
            for field in ('before_background_removal','background_job'):
                if field in item:
                    value=Path(item[field]);value=value if value.is_absolute() else corrections_path.parent/value
                    if not value.is_file():raise ValueError('Missing correction material: '+field)
                    background_record[field]=str(value.resolve())
            replacements.append((variant, order, frame, prompt,background_record))
    for variant, order, frame, prompt,background_record in replacements:
        folder = job/variant/'accepted'/str(order)
        folder.mkdir(parents=True)
        frame.save(folder/'refined.png')
        (folder/'prompt.txt').write_text(prompt, encoding='utf-8')
        record = variants[variant]['refinement'][order]
        record.update(refined=str(folder/'refined.png'), correction_prompt=str(folder/'prompt.txt'))
        for field in ('before_background_removal','background_job'):
            record.pop(field,None)
        record.update(background_record)
    results = {}
    for variant, report in variants.items():
        # Regenerate only deterministic assembly; no ComfyUI calls.
        results[variant] = finish_refined(report, report['refinement'], job/variant,
                                         output/variant if not jump else job/'joint-result'/variant,
                                         report.get('target_max_side'), report['refined_crop']['alpha_cutoff'])
    paired = variant_summary(results, output if not jump else job/'joint-result')
    if jump:
        return split_jump(paired, job=job, output=output, profile=summary['airborne_reference'],
                          joint_summary=job/'joint-result'/'variants.json', **summary['split'])
    return paired


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('summary', 'corrections', 'job', 'output'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    try:
        result = apply(args.summary, args.corrections, args.job, args.output)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, str(exc)+'\n')


if __name__ == '__main__':
    main()
