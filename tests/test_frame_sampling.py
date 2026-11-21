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
from frame_sampling import adaptive_indices, sample_video, source_weights, weighted_timings,pose_timing
from source_clock import FrameClock
import spritesheet
import finish_animation
import airborne_pipeline


def pose(x):
    image = Image.new('L', (48, 64))
    ImageDraw.Draw(image).rectangle((x, 10, x+8, 54), fill=220)
    return image


class SamplingTests(unittest.TestCase):
    def test_fixed_playback_fills_motion_with_source_frames_and_holds_static_pose(self):
        from frame_sampling import fixed_playback
        clock = FrameClock(range(7), 7)
        for positions, expected in [([2, 7, 12, 17, 22, 27, 32], list(range(7))),
                                    ([2] * 7, [0, 3, 6])]:
            timing = {}
            indices, seconds = fixed_playback([pose(x) for x in positions], [0, 3, 6],
                                              clock, 0, 6, 1, 25, timing)
            self.assertEqual(indices, expected)
            self.assertEqual(seconds, 1)
            self.assertEqual(timing['playback']['primary_source_indices'], [0, 3, 6])
            sequence = timing['playback']['sequence']
            self.assertEqual(len(sequence), 25)
            self.assertEqual(sequence, sorted(sequence))
            self.assertEqual(timing['frame_durations_ms'],
                             [sequence.count(cell) * 40 for cell in range(len(expected))])

    def test_rgb_lead_static_detection_is_independent_of_y_scoring(self):
        from frame_sampling import lead_samples
        images=[Image.new('RGB',(48,64),(40,50,60)) for _ in range(4)]
        result=lead_samples(images,FrameClock(range(5),5),0,4,20,160)
        self.assertTrue(result['static'])
        self.assertEqual(len(result['indices']),1)

    def test_curve_pruning_preserves_anchors_and_checks_every_merged_span(self):
        from frame_sampling import CurveScorer
        images=[pose(x) for x in (2,3,8,16,26,30,26,16,8,3,2)]
        scorer=CurveScorer(images,'cubic',range(len(images)))
        result=scorer.select(.75,anchors=[5])
        self.assertTrue({0,5,10}.issubset(result['indices']))
        for a,b in zip(result['indices'],result['indices'][1:]):
            if b>a+1:self.assertLessEqual(scorer.candidate(a,b)[0][0],.75)
        for p,index in enumerate(result['indices'][1:-1],1):
            if index!=5:self.assertGreater(scorer.candidate(result['indices'][p-1],result['indices'][p+1])[0][0],.75)
        self.assertEqual(scorer.select(.75,count=7)['count'],7)

    def test_curve_methods_recognize_constant_and_turning_features(self):
        from frame_sampling import CurveScorer
        constant=[Image.new('L',(48,64),40) for _ in range(7)]
        for method in ('linear','cubic'):
            self.assertEqual(CurveScorer(constant,method,range(7)).select(.75)['indices'],[0,6])
            turning=[Image.new('L',(48,64),v) for v in (20,30,80,160,80,30,20)]
            scorer=CurveScorer(turning,method,range(7))
            selected=scorer.select(.75)['indices']
            self.assertGreater(len(selected),2)
            for a,b in zip(selected,selected[1:]):
                if b>a+1:self.assertLessEqual(scorer.candidate(a,b)[0][0],.75)

    def test_smooth_feature_ramp_still_needs_displayed_intermediate_frames(self):
        from frame_sampling import CurveScorer
        images=[Image.new('L',(48,64),v) for v in (20,40,60,80,100)]
        for method in ('linear','cubic'):
            self.assertEqual(CurveScorer(images,method,range(5)).select(.01)['indices'],list(range(5)))

    def test_local_motion_is_not_diluted_by_large_moving_region(self):
        from frame_sampling import AdaptiveScorer,LeadScorer,CurveScorer
        images=[]
        for step in range(3):
            image=Image.new('L',(48,64))
            draw=ImageDraw.Draw(image)
            draw.rectangle((0,0,47,45),fill=(100,110,0)[step])
            draw.rectangle((step*12,48,step*12+8,63),fill=220)
            images.append(image)
        self.assertGreater(LeadScorer(images).distance(0,1),.75)
        global_score=AdaptiveScorer(images).distance(0,1)
        self.assertLess(global_score,.75)
        self.assertEqual(CurveScorer(images,'cubic',range(3)).distance(0,1),global_score)

    def test_masked_background_colour_cannot_create_motion(self):
        from select_segment import appearance_feature
        mask=Image.new('L',(48,64))
        ImageDraw.Draw(mask).rectangle((16,8,30,56),fill=255)
        images=[]
        for colour in ((20,20,20),(240,40,160)):
            image=Image.new('RGB',mask.size,colour)
            ImageDraw.Draw(image).rectangle((16,8,30,56),fill=(70,60,50))
            images.append(appearance_feature(image,mask))
        from frame_sampling import AdaptiveScorer
        self.assertEqual(AdaptiveScorer(images).distance(0,1),0)

    def test_internal_dark_colour_change_with_fixed_outline_is_sampled(self):
        from select_segment import appearance_feature
        mask=Image.new('L',(48,64),255)
        images=[]
        for x in (8,8,20,32,32):
            image=Image.new('RGB',mask.size,(30,30,30))
            ImageDraw.Draw(image).rectangle((x,12,x+8,52),fill=(100,15,15))
            images.append(appearance_feature(image,mask))
        result=adaptive_indices(images)
        self.assertIn(2,result[0])

    def test_sustained_pose_time_does_not_migrate_to_short_transition(self):
        values=[2]*3+[10]+[30]*20+[10]+[2]*6
        images=[pose(x) for x in values];indices=[0,3,4,24,30]
        weights,report=pose_timing(images,indices,FrameClock(range(31),31),0,30)
        self.assertEqual(weights[2],20)
        self.assertEqual(weights[3],1)
        self.assertEqual(sum(weights),31)
        self.assertEqual(report['source_bins'][2],[4,24])

    def test_deliberate_hold_at_an_intermediate_pose_is_preserved(self):
        values=[2]*2+[30]+[10]*12+[2]*2
        images=[pose(x) for x in values];indices=[0,2,3,16]
        weights,_=pose_timing(images,indices,FrameClock(range(17),17),0,16)
        self.assertEqual(weights[2],12)
        self.assertGreater(weights[2],weights[1])

    def test_visual_time_assignment_respects_variable_source_durations(self):
        images=[pose(x) for x in [2,30,30,10,2]]
        clock=FrameClock([0,.1,.4,1.4,1.5],1.7)
        weights,_=pose_timing(images,[0,1,3,4],clock,0,4)
        self.assertAlmostEqual(float(weights[1]),1.3)
        self.assertAlmostEqual(float(weights[2]),.1)
        self.assertAlmostEqual(float(sum(weights)),1.7)

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
        for kind in ('loop', None):
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
        self.assertEqual(sum(weighted_timings(.11, [1000, 1, 1, 1, 1000])), 100)
        with self.assertRaises(ValueError):
            weighted_timings(.04, weights)

    def test_air_action_shares_sampler_before_selected_frame_alignment(self):
        with patch.object(airborne_pipeline, 'load_reference', return_value=(pose(2), [0,0,12,12])), \
             patch.object(airborne_pipeline, 'sample_video', return_value=([2,7,10], {'strategy':'test'})) as select, \
             patch.object(airborne_pipeline, 'selected_finish', return_value={}) as finish:
            airborne_pipeline.action('source.mp4', 'ref.json', 2, 10, 3, 'job', 'out', 'image.json',
                                     'prompt.txt', .6, scale=1)
        select.assert_called_once_with('source.mp4', 2, 10, 3, 'return_to_start', False,
                                      seconds=.6, quality='compact', lead_start=None, lead_refresh_ms=160)
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
