import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from pose_reliability import JOINTS,input_quality,confidence_weights,weighted_smooth,distance,EvidenceMetric
from benchmark_pose_methods import smooth,recursive_knee


class ReliabilityTests(unittest.TestCase):
    def test_unobserved_wrist_spike_does_not_create_a_major_pose(self):
        poses=np.zeros((21,16,2));poses[:,JOINTS.index(27),0]=np.sin(np.linspace(0,np.pi,21))
        visibility=np.ones((21,16));visibility[5,JOINTS.index(15)]=0
        distorted=poses.copy();distorted[5,JOINTS.index(15),0]=10000
        weights=confidence_weights(visibility)
        a=weighted_smooth(poses,weights);b=weighted_smooth(distorted,weights)
        np.testing.assert_array_equal(a,b)
        appearance=np.zeros((21,4))
        self.assertEqual(recursive_knee(a,np.arange(21),weights,appearance)[0],
                         recursive_knee(b,np.arange(21),weights,appearance)[0])
        self.assertTrue(input_quality(distorted,visibility,0,20,appearance)['passed'])

    def test_low_confidence_has_less_influence_without_inventing_coordinates(self):
        a=np.zeros((16,2));b=a.copy();b[4,0]=1
        weights=np.ones(16);weights[4]=.1
        self.assertLess(distance(a,b,weights),distance(a,b,np.ones(16)))

    def test_reliable_smoothing_matches_existing_smoothing(self):
        positions=np.random.default_rng(2).normal(size=(12,16,2))
        np.testing.assert_array_equal(weighted_smooth(positions,np.ones((12,16))),smooth(positions,1))

    def test_symmetric_evidence_rules_and_invalid_inputs(self):
        positions=np.zeros((3,16,2));visibility=np.ones((3,16))
        for joints in ((11,13,15),(12,14,16)):
            v=visibility.copy();v[1,[JOINTS.index(j) for j in joints]]=0
            self.assertTrue(input_quality(positions,v,0,2,np.zeros((3,8)))['passed'])
            self.assertEqual(input_quality(positions,v,0,2)['reason'],'appearance_required_for_occlusion')
        self.assertFalse(input_quality(positions[:2],visibility,0,2)['passed'])
        positions[0,0,0]=np.nan
        self.assertFalse(input_quality(positions,visibility,0,2)['passed'])

    def test_image_motion_is_not_zero_when_hidden_joints_are_unavailable(self):
        poses=np.zeros((21,16,2));weights=np.ones((21,16));weights[:,[0,2,4]]=0
        appearance=np.sin(np.linspace(0,np.pi,21))[:,None]
        metric=EvidenceMetric(poses,weights,appearance)
        self.assertGreater(metric.interpolation(0,20,10,.5),0)
        selected,_=recursive_knee(poses,np.arange(21),weights,appearance)
        self.assertIn(10,selected)
        with self.assertRaises(ValueError):EvidenceMetric(poses,weights)

    def test_no_shared_joints_can_use_image_evidence_without_zero_distance(self):
        poses=np.zeros((2,16,2));weights=np.zeros((2,16));weights[0,:8]=1;weights[1,8:]=1
        metric=EvidenceMetric(poses,weights,np.asarray([[0.],[1.]]))
        self.assertGreater(metric.pairs()[0,1],0)


if __name__=='__main__':unittest.main()
