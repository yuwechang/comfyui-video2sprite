import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from benchmark_pose_methods import recursive_knee,benchmark


class PoseMethodTests(unittest.TestCase):
    def test_constant_motion_does_not_invent_keyposes(self):
        poses=np.zeros((12,4,2));times=np.arange(12,dtype=float)
        for method in benchmark(poses,times)['methods'].values():
            self.assertEqual(method['indices'],[0,11])

    def test_recursive_knee_finds_closed_motion_turn_and_is_scale_invariant(self):
        values=np.r_[np.linspace(0,1,11),np.linspace(1,0,11)[1:]]
        poses=np.zeros((len(values),3,2));poses[:,0,0]=values
        selected,_=recursive_knee(poses,np.arange(len(values),dtype=float))
        self.assertEqual(selected,[0,10,20])
        other,_=recursive_knee(poses*7+4,np.arange(len(values),dtype=float)*3)
        self.assertEqual(other,selected)

    def test_all_methods_keep_endpoints_and_order_without_target_count(self):
        poses=np.zeros((20,4,2));poses[:,0,0]=np.sin(np.linspace(0,2*np.pi,20))
        report=benchmark(poses,np.arange(20,dtype=float))
        for method in report['methods'].values():
            indices=method['indices']
            self.assertEqual(indices,sorted(set(indices)))
            self.assertEqual((indices[0],indices[-1]),(0,19))


if __name__=='__main__':unittest.main()
