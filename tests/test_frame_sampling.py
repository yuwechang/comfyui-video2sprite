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
from frame_sampling import adaptive_indices, sample_video, source_weights, weighted_timings
import spritesheet
import finish_animation
import airborne_pipeline


def pose(x):
    image = Image.new('L', (48, 64))
    ImageDraw.Draw(image).rectangle((x, 10, x+8, 54), fill=220)
    return image


class SamplingTests(unittest.TestCase):
    def test_brief_action_is_not_lost_between_uniform_samples(self):
        images = [pose(2)]*15 + [pose(x) for x in (9, 18, 30, 18, 9)] + [pose(2)]*15
        indices, _ = adaptive_indices(images, 8)
        uniform = spritesheet.sample_indices(0, 34, 8, False)
        self.assertNotIn(17, uniform)
        self.assertIn(17, indices)
        self.assertGreaterEqual(len([i for i in indices if 15 <= i <= 19]), 4)
        self.assertEqual((indices[0], indices[-1]), (0, 34))
        self.assertEqual(indices, sorted(set(indices)))

    def test_held_extreme_preserves_entry_exit_without_filling_plateau(self):
        images = [pose(2)]*8 + [pose(10), pose(20)] + [pose(30)]*20 + [pose(20), pose(10)] + [pose(2)]*8
        indices, _ = adaptive_indices(images, 8)
        self.assertIn(10, indices)
        self.assertIn(29, indices)
        self.assertLessEqual(len([i for i in indices if 10 <= i <= 29]), 2)
        self.assertTrue(any(8 <= i <= 9 for i in indices))
        self.assertTrue(any(30 <= i <= 31 for i in indices))

    def test_other_types_do_not_decode_or_change_uniform_sampling(self):
        for kind in ('loop', 'hold_end_pose', None):
            with patch('select_segment.features', side_effect=AssertionError('No adaptive analysis')):
                indices, report = sample_video('unused.mp4', 4, 43, 8, kind, kind=='loop')
            self.assertEqual(indices, spritesheet.sample_indices(4, 43, 8, kind=='loop'))
            self.assertEqual(report['strategy'], 'uniform')

    def test_source_timing_survives_pose_reduction(self):
        indices = [0, 10, 11, 12, 22]
        weights = source_weights(indices, 0, 22)
        self.assertEqual(sum(weights), 23)
        durations = weighted_timings(1.2, weights)
        self.assertEqual(sum(durations), 1200)
        self.assertGreater(durations[0], durations[2])
        self.assertTrue(all(d >= 10 and d % 10 == 0 for d in durations))
        self.assertEqual(sum(weighted_timings(.05, [1000, 1, 1, 1, 1000])), 50)
        with self.assertRaises(ValueError):
            weighted_timings(.04, weights)

    def test_air_action_shares_sampler_before_selected_frame_alignment(self):
        with patch.object(airborne_pipeline, 'load_reference', return_value=(pose(2), [0,0,12,12])), \
             patch.object(airborne_pipeline, 'sample_video', return_value=([2,7,10], {'strategy':'test'})) as select, \
             patch.object(airborne_pipeline, 'selected_finish', return_value={}) as finish:
            airborne_pipeline.action('source.mp4', 'ref.json', 2, 10, 3, 'job', 'out', 'image.json',
                                     'prompt.txt', .6, scale=1)
        select.assert_called_once_with('source.mp4', 2, 10, 3, 'return_to_start', False)
        self.assertEqual(finish.call_args.args[1], [2,7,10])
        self.assertEqual(finish.call_args.kwargs['sampling'], {'strategy':'test'})

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_full_rate_selection_refines_only_samples_and_exports_timing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            values = [2]*15 + [9,18,30,18,9] + [2]*15
            for i, x in enumerate(values):
                image = Image.new('RGB', (64,64), (128,128,128))
                ImageDraw.Draw(image).rectangle((x,10,x+8,54), fill=(220,30,40))
                image.save(root/f'{i:03d}.png')
            subprocess.run(['ffmpeg','-v','error','-framerate','60','-i',str(root/'%03d.png'),
                            '-c:v','ffv1',str(root/'source.mkv')], check=True)
            (root/'profile.json').write_text('{}')
            (root/'prompt.txt').write_text('preserve pose')
            calls = []
            def refine(profile, image, prompt, job):
                calls.append(image)
                with Image.open(image) as im:
                    frame = im.convert('RGBA')
                alpha = Image.new('L', frame.size)
                alpha.putdata([0 if frame.getpixel((x,y))[:3]==(128,128,128) else 255
                               for y in range(frame.height) for x in range(frame.width)])
                frame.putalpha(alpha)
                path = Path(job)/'refined.png'
                path.parent.mkdir(parents=True, exist_ok=True)
                frame.save(path)
                return {'file':str(path)}
            with patch.object(finish_animation, 'process', side_effect=refine):
                result = finish_animation.finish_action(root/'source.mkv', None, root/'profile.json',
                    root/'prompt.txt', root/'job', root/'out', 8, 0, 34, 1.2, False,
                    motion_type='return_to_start')
            self.assertEqual(len(calls), 8)
            self.assertIn(17, result['sample_indices'])
            self.assertEqual(result['sampling']['analysis_frames'], 35)
            self.assertGreater(len(set(result['frame_durations_ms'])), 1)
            self.assertEqual(sum(result['frame_durations_ms']), 1200)
            with Image.open(result['preview']) as gif:
                self.assertEqual(gif.info['loop'], 0)
                actual = []
                for i in range(gif.n_frames):
                    gif.seek(i)
                    actual.append(gif.info['duration'])
            self.assertEqual(sum(actual), 1200)
            # GIF encoders merge identical adjacent rendered poses; their times must add up.
            self.assertEqual(actual, [sum(result['frame_durations_ms'][:2])]+result['frame_durations_ms'][2:])
            saved = json.loads((root/'out'/'animation.json').read_text())
            self.assertEqual(saved['frame_durations_ms'], result['frame_durations_ms'])

    def test_invalid_per_frame_timing_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            frame = Image.new('RGBA', (20,20))
            ImageDraw.Draw(frame).rectangle((4,4,12,16), fill='red')
            image, columns, rows = spritesheet.pack([frame, frame])
            image.save(root/'sheet.png')
            for durations in ([100], [100,90], [95,105], [0,200]):
                with self.subTest(durations=durations), self.assertRaisesRegex(ValueError, 'Frame durations'):
                    spritesheet.finish(root/'sheet.png', dict(cell_width=20,cell_height=20,columns=columns,
                        rows=rows,frames=2,requested_seconds=.2,frame_durations_ms=durations),root/'out')


if __name__ == '__main__':
    unittest.main()
