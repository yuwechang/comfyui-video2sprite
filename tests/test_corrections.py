import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw
import test_effect_variants as fixtures
import apply_corrections
import finish_animation as pipeline
import package_delivery as delivery


class CorrectionTests(unittest.TestCase):
    def test_ground_and_air_correction_rebuild_and_zip_without_resubmission(self):
        for air in (False, True):
            with self.subTest(air=air), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                helper = fixtures.EffectVariantTests()
                frames, prepared = helper.fixture(root)
                if air:
                    prepared['vertical_alignment'] = {'reference_point_aligned':[16,12]}
                with patch.object(pipeline, 'process', side_effect=helper.processor([])):
                    before = helper.run_pair(root, prepared)
                old = copy.deepcopy(before)
                record = before['variants']['without_effects']['refinement'][0]
                with Image.open(record['refined']) as image:
                    fixed = image.convert('RGBA')
                ImageDraw.Draw(fixed).rectangle((1,1,3,3), fill=(230,30,20,255))
                fixed.save(root/'replacement.png')
                (root/'precise.txt').write_text('Remove the identified residual; preserve physical content.')
                config = {'without_effects': {'1': {'image':'replacement.png','prompt':'precise.txt'}}}
                (root/'corrections.json').write_text(json.dumps(config))
                with patch.object(pipeline, 'process') as process:
                    result = apply_corrections.apply(root/'out/variants.json', root/'corrections.json',
                                                     root/'correct-job',root/'correct-out')
                process.assert_not_called()
                for variant, report in result['variants'].items():
                    self.assertEqual(report['sample_indices'],[1,3])
                    self.assertEqual(report['frame_durations_ms'],[80,120])
                    delivery.verify_animation(report, root)
                report = result['variants']['without_effects']
                self.assertNotEqual(report['anchor_px'], old['variants']['without_effects']['anchor_px'])
                self.assertEqual(report['anchor_type'], 'waist' if air else 'source_origin')
                self.assertEqual(Path(report['refinement'][1]['refined']).read_bytes(),
                                 Path(old['variants']['without_effects']['refinement'][1]['refined']).read_bytes())
                self.assertEqual(json.loads((root/'out/variants.json').read_text()),old)
                for i in range(4): frames[i%2].save(root/f'source-{i:03d}.png')
                subprocess.run(['ffmpeg','-v','error','-framerate','20','-i',str(root/'source-%03d.png'),
                                '-c:v','ffv1',str(root/'source.mkv')],check=True)
                manifest = {'video':'source.mkv','animations':{n:f'correct-out/{n}/animation.json'
                            for n in pipeline.EFFECT_VARIANTS}}
                (root/'assets.json').write_text(json.dumps(manifest))
                packaged = delivery.package(root/'assets.json',root/'delivery.zip')
                import zipfile
                with zipfile.ZipFile(packaged['zip']) as archive:
                    portable = json.loads(archive.read('variants/without_effects/animation.json'))
                    self.assertEqual(portable['refinement'][0]['correction_prompt'],'corrections/000-prompt.txt')
                    self.assertIn('variants/without_effects/corrections/000-prompt.txt',archive.namelist())
                    self.assertNotIn(str(root),json.dumps(portable))
                # A modified sheet is rejected before exporting source frames.
                with Image.open(report['sheet']) as image:
                    changed = image.convert('RGBA')
                changed.putpixel((0,0),(1,2,3,255));changed.save(report['sheet'])
                with self.assertRaisesRegex(ValueError,'cell differs'):
                    delivery.package(root/'assets.json',root/'bad.zip')

    def test_gif_timing_and_frame_content_mismatch_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);helper = fixtures.EffectVariantTests()
            _, prepared = helper.fixture(root)
            with patch.object(pipeline,'process',side_effect=helper.processor([])):
                paired = helper.run_pair(root,prepared)
            report = paired['variants']['without_effects']
            delivery.verify_animation(report,root)
            wrong = copy.deepcopy(report)
            wrong['frame_durations_ms'] = [100,100]
            with self.assertRaisesRegex(ValueError,'pixels or frame order'):
                delivery.verify_animation(wrong,root)
            wrong = copy.deepcopy(report)
            wrong['refinement'][0]['source_frame_index'] = 999
            with self.assertRaisesRegex(ValueError,'source indices'):
                delivery.verify_animation(wrong,root)
            with Image.open(report['preview']) as image:
                first = image.convert('RGBA')
            first.info.clear()
            first.save(root/'once.gif')
            wrong = dict(report,preview=str(root/'once.gif'))
            with self.assertRaisesRegex(ValueError,'repeat setting'):
                delivery.verify_animation(wrong,root)

    def test_invalid_replacement_does_not_write_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);helper = fixtures.EffectVariantTests()
            _, report = helper.fixture(root)
            with patch.object(pipeline,'process',side_effect=helper.processor([])):
                helper.run_pair(root,report)
            Image.new('RGBA',(1,1)).save(root/'bad.png');(root/'prompt.txt').write_text('fix')
            (root/'corrections.json').write_text(json.dumps({'without_effects':{'1':{'image':'bad.png','prompt':'prompt.txt'}}}))
            with self.assertRaisesRegex(ValueError,'dimensions'):
                apply_corrections.apply(root/'out/variants.json',root/'corrections.json',root/'job-new',root/'out-new')
            self.assertFalse((root/'job-new').exists())
            self.assertFalse((root/'out-new').exists())
