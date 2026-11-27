import sys
from pathlib import Path
import unittest
import tempfile
import subprocess
import shutil
from unittest.mock import patch
from PIL import Image,ImageDraw

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from select_segment import locate,select


def pose(x):
    image=Image.new('L',(48,64))
    ImageDraw.Draw(image).rectangle((x,16,x+9,54),fill=220)
    return image


class SegmentTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_fast_loop_preserves_source_frame_phase_returns(self):
        # A six-frame cycle at 24 FPS loses alternate phases at 12 FPS.
        # Analysis must not merge cycles to satisfy its minimum sample count.
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            values=[4,10,18,26,18,10]*6+[4]
            for i,x in enumerate(values):
                pose(x).convert('RGB').save(root/f'{i:03d}.png')
            video=root/'fast.mkv'
            subprocess.run(['ffmpeg','-v','error','-framerate','24','-i',
                str(root/'%03d.png'),'-c:v','ffv1',str(video)],check=True)
            result=select(video,'loop')
            self.assertEqual(result['status'],'selected')
            self.assertEqual(result['analysis_stride'],1)
            self.assertEqual(result['matching_tail']-result['start'],6)
            self.assertEqual(result['complete_cycle_count'],6)

    def test_hold_keeps_multiple_substantial_phases_before_larger_final_phase(self):
        # Two substantial phases and several tiny disturbances; no action labels.
        values=[2]*4+[8,14,20,26]+[26]*3+[27]+[27]*3+[28]+[28]*5+[22,16,10,4,10,16,22,28,34]+[34]*5
        result=locate([pose(x) for x in values],'hold_end_pose',stable_threshold=.01)
        self.assertEqual(result['status'],'selected')
        self.assertEqual(result['start'],3)
        self.assertGreater(sum(row['retained_major_phase'] for row in result['activity_episodes']),1)
        self.assertFalse(result['lead_review_required'])
        self.assertEqual(result['lead_start'],result['start'])
    def test_settled_return_does_not_wait_for_later_exact_baseline_match(self):
        images=[pose(x) for x in [2,2,2,8,16,24,16,8]+[3]*5+[2]*4]
        result=locate(images,'return_to_start',stable_threshold=.01)
        self.assertEqual(result['status'],'selected')
        self.assertEqual(result['end'],8)

    def test_loop_excludes_matching_tail(self):
        images=[pose(x) for x in [4,4,4,8,12,16,20,16,12,8,4,8,12,16,20,16,12,8,4]]
        result=locate(images,'loop',count=6,stable_threshold=.01)
        self.assertEqual(result['status'],'selected')
        self.assertEqual(result['end'],result['matching_tail']-1)
        self.assertTrue(result['loop'])

    def test_return_to_start_includes_head_and_tail(self):
        images=[pose(x) for x in [2,2,2,8,8,8,12,18,24,18,12,8,8,8]]
        result=locate(images,'return_to_start',count=4,stable_threshold=.01)
        self.assertEqual((result['start'],result['end']),(5,11))
        self.assertFalse(result['loop'])
        self.assertEqual(result['seam_distance'],0)

    def test_hold_end_pose_uses_last_preparation_not_initial_standing(self):
        images=[pose(x) for x in [2,2,2,6,10,10,10,16,22,28,34,34,34]]
        result=locate(images,'hold_end_pose',count=4,stable_threshold=.01)
        self.assertEqual((result['start'],result['end']),(6,10))

    def test_hold_end_pose_keeps_main_action_before_late_settling(self):
        # Abstract pose change followed by a pause and a smaller finishing change.
        images=[pose(x) for x in [2,2,2,3,3,3,8,14,20,26,26,26,29,30,30,30]]
        result=locate(images,'hold_end_pose',stable_threshold=.01)
        self.assertEqual((result['start'],result['end']),(5,13))
        self.assertEqual(result['lead_candidate_range'],[0,5])

    def test_static_clip_is_not_a_loop(self):
        self.assertEqual(locate([pose(8)]*20,'loop')['status'],'needs_review')

    def test_loop_counts_complete_repetitions_before_ranking(self):
        for count in (1,2,3):
            values=[2,2,2]+[8,16,24,16,8,2]*count+[8,16]
            result=locate([pose(x) for x in values],'loop',stable_threshold=.01)
            self.assertEqual(result['complete_cycle_count'],count)
            self.assertEqual(len(result['cycle_candidates']),count)
            for a,b in zip(result['cycle_candidates'],result['cycle_candidates'][1:]):
                self.assertEqual(a['matching_tail'],b['start'])
            self.assertTrue(any(result['start']==c['start'] and result['end']==c['end']
                                for c in result['cycle_candidates']))

    def test_unfinished_movement_is_not_counted_as_complete_loop(self):
        result=locate([pose(x) for x in [2,2,2,6,10,14,18,22,26]],'loop',stable_threshold=.01)
        self.assertEqual(result['status'],'needs_review')

    def test_repeated_returns_rank_each_complete_performance(self):
        values=[2,2,2,8,16,24,16,8,3,3,3,9,17,25,17,9,3,3,3]
        result=locate([pose(x) for x in values],'return_to_start',stable_threshold=.01)
        self.assertEqual((result['start'],result['end']),(10,16))
        self.assertEqual(len(result['return_candidates']),2)
        self.assertGreater(result['return_candidates'][0]['score'],
                           result['return_candidates'][1]['score'])

    def test_repeated_equal_returns_prefer_earlier_without_merging(self):
        values=[2,2,2,8,16,24,16,8,2,2,2,8,16,24,16,8,2,2,2]
        result=locate([pose(x) for x in values],'return_to_start',stable_threshold=.01)
        self.assertEqual((result['start'],result['end']),(2,8))
        self.assertEqual([(c['start'],c['end']) for c in result['return_candidates']],[(2,8),(10,16)])

    def test_return_to_start_can_finish_before_a_later_transition(self):
        images=[pose(x) for x in [2,2,2,8,8,8,12,18,24,18,12,8,8,8,20,30]]
        result=locate(images,'return_to_start',count=4,stable_threshold=.01)
        self.assertEqual((result['start'],result['end']),(5,11))

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
    def test_loop_detection_excludes_horizontal_background_bands(self):
        from select_segment import select,features
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for i,extent in enumerate([0,0,0,3,6,9,6,3,0,3,6,9,6,3,0]):
                image=Image.new('RGB',(96,120),(170,)*3);draw=ImageDraw.Draw(image)
                draw.rectangle((0,90,95,119),fill=(60,)*3)
                draw.rectangle((44,20,51+extent,60),fill=(220,30,30))
                draw.rectangle((44,60,51,90),fill=(220,30,30))
                image.save(root/f'{i:03d}.png')
            subprocess.run(['ffmpeg','-v','error','-framerate','12','-i',str(root/'%03d.png'),
                '-c:v','ffv1',str(root/'source.mkv')],check=True)
            result=select(root/'source.mkv','loop')
            self.assertEqual(result['status'],'selected')
            self.assertGreaterEqual(result['complete_cycle_count'],1)
            images,_=features(root/'source.mkv',subject_only=True,horizontal_background=True)
            self.assertEqual(images[0].getpixel((47,0)),(0,0,0))
            class ModelMask:
                metadata={'device':'cuda','providers':['CUDAExecutionProvider']}
                def mask(self,image):
                    result=Image.new('L',image.size)
                    result.putdata([255 if r>g*2 else 0 for r,g,b in image.getdata()])
                    return result
            with patch('subject_mask.SubjectMask',return_value=ModelMask()), \
                    patch('select_segment.row_background_mask',side_effect=AssertionError('No color fallback')):
                images,_=features(root/'source.mkv',foreground={'model_dir':'models'},
                                  mask_output=root/'masks',horizontal_background=True)
                self.assertEqual(images[0].getpixel((47,0)),(0,0,0))
            import json
            report=json.loads((root/'masks'/'analysis.json').read_text())
            self.assertEqual(len(report['source_indices']),15)
            self.assertEqual(report['device'],'cuda')

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
    def test_real_video_auto_selection_without_frontend_metadata(self):
        import spritesheet
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            values=[12,12,12,16,20,24,28,24,20,16,12,16,20,24,28,24,20,16,12]
            for i,x in enumerate(values):
                image=Image.new('RGB',(64,64),(128,128,128))
                ImageDraw.Draw(image).rectangle((x,10,x+9,54),fill=(230,30,40))
                image.save(root/f'{i:03d}.png')
            subprocess.run(['ffmpeg','-v','error','-framerate','12','-i',str(root/'%03d.png'),
                            '-c:v','ffv1',str(root/'source.mkv')],check=True)
            with patch.object(Path,'read_text',side_effect=AssertionError('No frontend metadata')):
                result=spritesheet.prepare(root/'source.mkv',root/'out',None,6,None,None,
                                            .6,False,motion_type='loop')
            selected=result['automatic_selection']
            self.assertEqual(selected['end'],selected['matching_tail']-1)
            self.assertLess(max(result['sample_indices']),selected['matching_tail'])
            self.assertEqual(len(result['sample_indices']),6)


if __name__=='__main__':unittest.main()
