import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
import airborne
import airborne_pipeline as pipeline
import finish_animation


def reference():
    im = Image.new('RGB', (128,128), (128,128,128))
    d = ImageDraw.Draw(im)
    d.rectangle((48,34,79,91), fill=(190,30,40))
    d.rectangle((50,49,77,77), fill=(240,210,80))
    d.line((51,52,75,72), fill=(20,40,150), width=4)
    d.rectangle((53,80,62,105), fill='white')
    return im


class AirborneTests(unittest.TestCase):
    def test_cli_air_route_errors_cleanly_before_processing_without_reference(self):
        script = Path(__file__).parents[1]/'scripts/airborne_pipeline.py'
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable,str(script),'action','source.mp4',
                '--reference-profile',str(Path(folder)/'missing.json'),'--start','0','--end','8',
                '--seconds','.8','--job',str(Path(folder)/'job'),'--output',str(Path(folder)/'out'),
                '--image-profile','image.json','--prompt-file','prompt.txt'],capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            self.assertIn('error',json.loads(result.stdout))
            self.assertNotIn('Traceback',result.stderr)
            self.assertFalse((Path(folder)/'out').exists())

    def test_rotation_and_translation_track_same_waist(self):
        ref = reference()
        rotated = ref.rotate(-90, center=(64,64), fillcolor=(128,128,128))
        moved = Image.new('RGB', ref.size, (128,128,128))
        moved.paste(rotated, (0,10))
        result = airborne.match_waist(moved, ref, [48,48,80,80])
        self.assertAlmostEqual(result['y'], 74, delta=1)
        self.assertAlmostEqual(result['x'], 64, delta=1)
        self.assertAlmostEqual(result['angle'], 90, delta=5)

    def test_reference_profile_is_portable_and_checks_dimensions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = airborne.create_reference(reference(), [48,48,80,80], folder)
            image, roi = airborne.load_reference(path)
            self.assertEqual(image.size, (128,128))
            config = json.loads(path.read_text())
            self.assertEqual(config['reference_image'], 'reference.png')
            config['frame_size'] = [64,64]
            path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, 'dimensions'):
                airborne.load_reference(path)

    def test_overrides_apply_only_to_selected_frames_and_preserve_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            ref = reference()
            shifted = Image.new('RGB', ref.size, (128,128,128))
            shifted.paste(ref, (0,10))
            with patch.object(airborne, 'match_waist', side_effect=AssertionError('Explicit coordinates')):
                frames, report = airborne.align_selected([ref, shifted], [4,9], ref, [48,48,80,80], folder,
                                                          {'4':[64,64], '9':[64,74]})
            self.assertEqual([r['dy'] for r in report['matches']], [0,-10])
            self.assertEqual(frames[0].crop((0,10,128,138)).convert('RGB').tobytes(), ref.tobytes())
            self.assertEqual(frames[1].getpixel((55,64)), ref.getpixel((55,54))+(255,))
            with self.assertRaisesRegex(ValueError, 'selected'):
                airborne.align_selected([ref], [4], ref, [48,48,80,80], folder, {'5':[64,64]})

    def test_low_confidence_stops_with_review_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(airborne, 'match_waist', return_value={'x':64,'y':64,'angle':0,'error':.9}):
                with self.assertRaisesRegex(ValueError, 'needs review'):
                    airborne.align_selected([reference()], [7], reference(), [48,48,80,80], folder)
            report = json.loads((Path(folder)/'alignment.json').read_text())
            self.assertEqual(report['needs_review'], [7])
            self.assertTrue((Path(folder)/'alignment-preview.png').exists())

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_joint_jump_refines_unique_samples_once_and_reuses_apex(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            base = reference()
            for i, dy in enumerate((0,-5,-10,-15,-20,-15,-10,-5,0)):
                im = Image.new('RGB', base.size, (128,128,128));im.paste(base,(0,dy));im.save(root/f'{i:03d}.png')
            subprocess.run(['ffmpeg','-v','error','-framerate','12','-i',str(root/'%03d.png'),
                            '-c:v','ffv1',str(root/'source.mkv')], check=True)
            (root/'image.json').write_text('{}');(root/'prompt.txt').write_text('preserve pose')
            calls=[]
            def refine(profile, image, prompt, job):
                calls.append(str(image))
                # Independent cutout fixture: exact uniform background is transparent.
                rgb = Image.open(image).convert('RGB');alpha=Image.new('L',rgb.size)
                alpha.putdata([0 if rgb.getpixel((x,y))==(128,128,128) else 255
                               for y in range(rgb.height) for x in range(rgb.width)])
                im=rgb.convert('RGBA');im.putalpha(alpha)
                path=Path(job)/'result.png';path.parent.mkdir(parents=True,exist_ok=True);im.save(path)
                return {'file':str(path)}
            with patch.object(finish_animation, 'process', side_effect=refine):
                result = pipeline.jump(root/'source.mkv',0,4,8,[48,28,80,60],3,3,root/'job',root/'out',
                                       root/'image.json',root/'prompt.txt',.3,.4)
            self.assertEqual(len(calls), 5)
            rise,fall=result['rise'],result['fall']
            self.assertEqual(rise['sample_indices'], [0,2,4]);self.assertEqual(fall['sample_indices'], [4,6,8])
            self.assertEqual(rise['duration_ms'], 300);self.assertEqual(fall['duration_ms'], 400)
            self.assertEqual(rise['anchor_px'], fall['anchor_px'])
            self.assertEqual(Path(rise['final_frames'][-1]).read_bytes(),Path(fall['final_frames'][0]).read_bytes())
            self.assertEqual(rise['refinement'][-1]['refined'],fall['refinement'][0]['refined'])
            ref,roi=airborne.load_reference(result['airborne_reference'])
            self.assertEqual(ref.size,base.size)


if __name__ == '__main__':unittest.main()
