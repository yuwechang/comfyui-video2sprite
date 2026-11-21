import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from pose_sampling import combine
from source_clock import FrameClock
from task_inputs import missing_inputs
from workflow_ops import selection


class FormalPoseTests(unittest.TestCase):
    def test_pose_timing_preserves_independent_x_budget(self):
        clock=FrameClock([i/10 for i in range(10)],1)
        result={'source_indices':[2,5,9],'source_major_indices':[2,9],
                'source_added_indices':[5],'frame_durations_ms':[200,400,200]}
        indices,report=combine(clock,2,9,0,1,result,{'indices':[0,1],'ticks':[5,5]})
        self.assertEqual(indices,[0,1,2,5,9])
        self.assertEqual(sum(report['frame_durations_ms']),1000)
        self.assertEqual(report['phases']['x']['ticks'],[5,5])
        self.assertEqual(report['major_indices'],[2,9])
        self.assertIsNone(report['target_count'])

    def test_missing_inputs_allows_automatic_source_duration_but_requires_model(self):
        config={'tasks':[{'id':'a','steps':[{'id':'selection','operation':'selection','args':{
            'video':'source.mp4','output':'out','seconds':None,'motion_type':'return_to_start',
            'sampling_method':'pose','pose':{'model':'pose.task'}}}]}]}
        self.assertEqual(missing_inputs(config,{}),[])
        config['tasks'][0]['steps'][0]['args']['pose']=None
        self.assertEqual(missing_inputs(config,{})[0]['fields'],['pose.model'])

    def test_formal_selection_calls_pose_sampler_without_legacy_frame_selection(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as root:
            report={'strategy':'pose_transition','method':'pose','frame_durations_ms':[100,100]}
            with patch('pose_sampling.sample',return_value=([2,9],report,.2)) as pose, \
                 patch('frame_sampling.sample_video',side_effect=AssertionError('No implicit fallback')), \
                 patch('spritesheet.extract_frames',return_value=[Image.new('RGB',(10,10))]*2):
                result=selection('video.mp4',root,None,'return_to_start',start=2,end=9,
                    sampling_method='pose',pose={'model':'pose.task'},foreground={'profile':'alpha.json'})
            self.assertEqual(result['sample_indices'],[2,9]);self.assertEqual(result['seconds'],.2)
            pose.assert_called_once()

    def test_pose_failure_is_not_silently_replaced_by_another_algorithm(self):
        with tempfile.TemporaryDirectory() as root, \
             patch('pose_sampling.sample',side_effect=ValueError('evidence unavailable')), \
             patch('frame_sampling.sample_video',side_effect=AssertionError('No implicit fallback')):
            with self.assertRaisesRegex(ValueError,'evidence unavailable'):
                selection('video.mp4',root,None,'return_to_start',start=0,end=9,
                    sampling_method='pose',pose={'model':'pose.task'})


if __name__=='__main__':unittest.main()
