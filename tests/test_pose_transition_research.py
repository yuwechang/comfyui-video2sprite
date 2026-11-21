import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from pose_transition_research import refine,input_quality,selection_parameters


class TransitionTests(unittest.TestCase):
    def test_complete_interval_hold_keeps_semantics_and_derives_boundaries(self):
        result=selection_parameters([10,15,20],[100,200,100],.4,'hold_end_pose',10,20)
        self.assertEqual((result['lead_start'],result['start'],result['end']),(10,10,20))
        self.assertEqual(result['motion_type'],'hold_end_pose')
        self.assertNotIn('start',selection_parameters([10,20],[200,200],.4,'return_to_start',10,20))
        with self.assertRaisesRegex(ValueError,'endpoints'):
            selection_parameters([11,20],[200,200],.4,'hold_end_pose',10,20)
    def test_partial_occlusion_keeps_source_indices_without_substitution(self):
        positions=np.zeros((4,16,2));visibility=np.ones((4,16));visibility[2,3]=.2
        report=input_quality(positions,visibility,10,13,np.zeros((4,8)))
        self.assertTrue(report['passed'])
        self.assertEqual(report['affected_frames'][0]['frame'],12)
        self.assertEqual(report['affected_frames'][0]['joints'],[14])
        self.assertTrue(input_quality(positions,np.ones((4,16)),10,13)['passed'])
    def test_whole_limb_missing_uses_image_evidence_instead_of_regional_stop(self):
        positions=np.zeros((4,16,2));visibility=np.ones((4,16))
        visibility[2,[0,2,4]]=0
        report=input_quality(positions,visibility,10,13,np.zeros((4,8)))
        self.assertTrue(report['passed'])
        self.assertFalse(input_quality(positions,visibility,10,13)['passed'])

    def test_reliable_transition_results_remain_exactly_unchanged(self):
        poses=np.zeros((20,16,2));poses[:,0,0]=np.sin(np.linspace(0,np.pi,20))
        plain=refine(poses,np.arange(20),[0,10,19],np.ones(20))
        weighted=refine(poses,np.arange(20),[0,10,19],np.ones(20),np.ones((20,16)))
        self.assertEqual(plain,weighted)
    def test_static_sequence_does_not_add_frames(self):
        result=refine(np.zeros((12,4,2)),np.arange(12),[0,6,11],np.ones(12))
        self.assertEqual(result['indices'],[0,6,11])
        self.assertEqual(sum(result['source_weights']),12)

    def test_major_poses_stay_fixed_and_error_decreases_without_target_count(self):
        poses=np.zeros((30,4,2));poses[:,0,0]=np.sin(np.linspace(0,np.pi,30))
        result=refine(poses,np.arange(30),[0,14,29],np.ones(30))
        self.assertTrue(set([0,14,29]).issubset(result['indices']))
        self.assertGreater(len(result['added_indices']),0)
        self.assertLess(len(result['indices']),30)
        self.assertLess(result['selected_error'],result['initial_error'])
        self.assertEqual(sum(result['source_weights']),30)
        self.assertTrue(all(b['error']<a['error'] for a,b in zip(result['states'],result['states'][1:])))

    def test_variable_source_durations_are_preserved(self):
        poses=np.zeros((7,2,2));poses[:,0,0]=[0,0,1,2,2,1,0]
        durations=np.asarray([.1,.1,.2,.4,.3,.1,.2])
        times=np.r_[0,np.cumsum(durations)[:-1]]
        result=refine(poses,times,[0,3,6],durations)
        self.assertAlmostEqual(sum(result['source_weights']),durations.sum())
        self.assertAlmostEqual(sum(result['major_source_weights']),durations.sum())


if __name__=='__main__':unittest.main()
