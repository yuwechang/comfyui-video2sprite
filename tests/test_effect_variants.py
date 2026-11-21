import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import finish_animation as pipeline
import package_delivery as delivery
from spritesheet import prepare_frames


class EffectVariantTests(unittest.TestCase):
    def test_plan_finish_with_effects_runs_only_the_removal_pass(self):
        from workflow_ops import finish

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            frames, _ = self.fixture(root)
            paths = []
            for index, frame in enumerate(frames):
                path = root / f'frame-{index}.png'
                frame.save(path)
                paths.append(str(path))
            selection = root / 'selection.json'
            selection.write_text(json.dumps({
                'selected_frames': paths, 'sample_indices': [1, 3],
                'scale': 1, 'seconds': .2, 'motion_type': 'return_to_start',
                'sampling': {'frame_durations_ms': [80, 120]},
            }))
            submissions = []
            with patch.object(pipeline, 'process', self.processor(submissions)):
                result = finish(selection, root/'image.json', root/'remove.txt',
                                root/'job', root/'out', effects_present=True)
            self.assertEqual(list(result['variants']), ['clean'])
            self.assertEqual(len(submissions), len(frames))

    def fixture(self, root):
        frames = []
        for shift in (0, 1):
            im = Image.new('RGB', (32, 24), (128, 128, 128))
            draw = ImageDraw.Draw(im)
            draw.rectangle((10+shift, 6, 15+shift, 18), fill=(220, 30, 20))
            draw.rectangle((24, 3, 27, 7), fill=(40, 90, 240))
            frames.append(im)
        report = prepare_frames(frames, [1, 3], root/'shared', None, .2,
                                motion_type='return_to_start',
                                sampling={'frame_durations_ms': [80, 120]})
        (root/'image.json').write_text('{}')
        (root/'keep.txt').write_text('Refine, remove background and keep the effect.')
        (root/'remove.txt').write_text('Refine, remove background and remove the effect.')
        return frames, report

    def processor(self, submissions, fail_once=None):
        def process(profile, image, prompt, job):
            target = Path(job)/'result.png'
            if target.exists():
                return {'file': str(target)}
            if fail_once and fail_once[0] and 'without_effects' in Path(job).parts and Path(job).parent.name == '001':
                fail_once[0] = False
                raise RuntimeError('interrupted in second variant')
            source = Image.open(image).convert('RGB')
            frame = source.convert('RGBA')
            rgb = source.tobytes()
            pixels = [tuple(rgb[i:i+3]) for i in range(0, len(rgb), 3)]
            frame.putalpha(Image.frombytes('L', source.size, bytes(
                0 if p == (128,128,128) or ('remove the effect' in prompt and p[2] > 200) else 255
                for p in pixels)))
            target.parent.mkdir(parents=True, exist_ok=True)
            frame.save(target)
            submissions.append((Path(job), source.tobytes(), prompt))
            return {'file': str(target)}
        return process

    def run_pair(self, root, report):
        return pipeline.finish_prepared_variants(report, root/'image.json', root/'keep.txt',
                                                 root/'remove.txt', root/'job', root/'out')

    def test_changed_entry_inputs_rejected_before_preparation_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, prepared = self.fixture(root)
            (root/'source.mp4').write_bytes(b'video input')
            def run(scale):
                return pipeline.finish_variants(root/'source.mp4',None,root/'image.json',
                    root/'keep.txt',root/'remove.txt',root/'job',root/'out',2,1,3,.2,False,scale=scale)
            with patch.object(pipeline,'prepare',return_value=prepared), \
                 patch.object(pipeline,'process',side_effect=self.processor([])):
                run(1)
            original = Path(prepared['cropped_frames'][0]).read_bytes()
            with patch.object(pipeline,'prepare') as prepare:
                with self.assertRaisesRegex(ValueError,'inputs changed'):
                    run(.5)
            prepare.assert_not_called()
            self.assertEqual(Path(prepared['cropped_frames'][0]).read_bytes(),original)

    def test_identical_selected_inputs_timing_independent_crops_and_source_anchor(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, prepared = self.fixture(root)
            before = json.dumps(prepared)
            calls = []
            with patch.object(pipeline, 'process', side_effect=self.processor(calls)):
                paired = self.run_pair(root, prepared)
            keep, remove = [paired['variants'][name] for name in pipeline.EFFECT_VARIANTS]
            self.assertEqual(len(calls), 4)
            self.assertEqual([c[1] for c in calls[:2]], [c[1] for c in calls[2:]])
            self.assertEqual(json.dumps(prepared), before)
            for result in (keep, remove):
                self.assertEqual(result['sample_indices'], [1,3])
                self.assertEqual(result['frame_durations_ms'], [80,120])
                self.assertEqual(result['verified']['gif_duration_ms'], 200)
                self.assertEqual(result['anchor_type'], 'source_origin')
                with Image.open(result['final_frames'][0]) as im:
                    x, y = result['anchor_px']
                    self.assertEqual(im.getpixel((round(12+x), round(9+y)))[:3], (220,30,20))
                with Image.open(result['preview']) as gif:
                    self.assertEqual(gif.info['loop'], 0)
            self.assertNotEqual(keep['refined_crop']['crop_box'], remove['refined_crop']['crop_box'])
            self.assertNotEqual(keep['final_frames'], remove['final_frames'])
            self.assertEqual((root/'job/with_effects/refine-prompt.txt').read_text(), (root/'keep.txt').read_text())
            self.assertTrue((root/'out/variants.json').exists())

    def test_resume_after_second_variant_failure_and_reject_changed_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, prepared = self.fixture(root)
            calls, fail = [], [True]
            with patch.object(pipeline, 'process', side_effect=self.processor(calls, fail)):
                with self.assertRaisesRegex(RuntimeError, 'second variant'):
                    self.run_pair(root, prepared)
                self.assertTrue((root/'out/with_effects/animation.json').exists())
                self.assertFalse((root/'out/variants.json').exists())
                self.run_pair(root, prepared)
            self.assertEqual(len(calls), 4)
            changed = dict(prepared, sample_indices=[0,2])
            with patch.object(pipeline, 'process') as process:
                with self.assertRaisesRegex(ValueError, 'inputs changed'):
                    self.run_pair(root, changed)
                process.assert_not_called()

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_paired_zip_contains_separate_processed_frames_and_resolvable_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            frames, prepared = self.fixture(root)
            for i in range(4):
                frames[0 if i < 3 else 1].save(root/f'source-{i:03d}.png')
            subprocess.run(['ffmpeg','-v','error','-framerate','20','-i',str(root/'source-%03d.png'),
                            '-c:v','ffv1',str(root/'source.mkv')], check=True)
            with patch.object(pipeline, 'prepare', wraps=pipeline.prepare) as prepare, \
                 patch.object(pipeline, 'process', side_effect=self.processor([])):
                pipeline.finish_variants(root/'source.mkv', None, root/'image.json', root/'keep.txt',
                                         root/'remove.txt', root/'job', root/'out', 2, 1, 3, .2,
                                         False, motion_type='return_to_start')
            self.assertEqual(prepare.call_count, 1)
            manifest = {'video':'source.mkv',
                        'animations': {name:f'out/{name}/animation.json' for name in pipeline.EFFECT_VARIANTS},
                        'files': {'input/reference.png':'source-000.png', 'prompts/pose.txt':'keep.txt'}}
            (root/'assets.json').write_text(json.dumps(manifest))
            result = delivery.package(root/'assets.json', root/'delivery.zip')
            self.assertEqual(result['all_frames'], 4)
            with zipfile.ZipFile(result['zip']) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(len([n for n in archive.namelist() if n.startswith('frames/all/')]), 4)
                for name in pipeline.EFFECT_VARIANTS:
                    path = f'variants/{name}/animation.json'
                    report = json.loads(archive.read(path))
                    self.assertNotIn(str(root), json.dumps(report))
                    for field in ('sheet', 'preview', 'refinement_prompt'):
                        self.assertIn(f'variants/{name}/'+report[field], archive.namelist())
                    for p in report['final_frames']:
                        import posixpath
                        self.assertIn(posixpath.normpath(f'variants/{name}/'+p), archive.namelist())
                    self.assertIn(f'frames/{name}/final/000.png', archive.namelist())
                self.assertNotEqual(archive.read('frames/with_effects/final/000.png'),
                                    archive.read('frames/without_effects/final/000.png'))
            changed = root/'out/without_effects/animation.json'
            report = json.loads(changed.read_text())
            report['frame_durations_ms'] = [80,120] if report['frame_durations_ms'] == [100,100] else [100,100]
            changed.write_text(json.dumps(report))
            with patch.object(delivery.subprocess, 'run') as export:
                with self.assertRaisesRegex(ValueError, 'frame_durations_ms'):
                    delivery.package(root/'assets.json', root/'bad.zip')
                export.assert_not_called()


if __name__ == '__main__':
    unittest.main()
