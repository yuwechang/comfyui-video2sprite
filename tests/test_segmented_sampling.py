import sys
from fractions import Fraction
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from frame_sampling import sample_video, lead_samples
from source_clock import FrameClock
from select_segment import locate


def pose(x):
    im = Image.new('L', (48,64))
    ImageDraw.Draw(im).rectangle((x,10,x+8,54), fill=220)
    return im


class SegmentedTests(unittest.TestCase):
    def test_x_and_y_have_one_shared_budget_with_no_boundary_duplicate(self):
        clock = FrameClock([Fraction(i,24) for i in range(40)], Fraction(40,24))
        x = [pose(2+i//3) for i in range(13)]
        y = [pose(i) for i in (6,6,10,18,26,34,34,34)]
        with patch('select_segment.features', side_effect=[(y,1),(x,1)]), \
             patch('frame_sampling.FrameClock.read', return_value=clock):
            indices, report = sample_video('source',12,19,motion_type='hold_end_pose',
                                           lead_start=0,seconds=1)
        self.assertEqual(indices, sorted(set(indices)))
        self.assertEqual(indices.count(12),1)
        self.assertTrue(all(i<12 for i in report['phases']['x']['indices']))
        self.assertEqual(sum(report['frame_durations_ms']),1000)
        budget=report['budget']
        self.assertEqual(budget['x_ms'],600)
        self.assertLessEqual(budget['x_ms'],budget['ideal_x_ms'])
        self.assertGreater(len(report['phases']['x']['indices']),1)
        self.assertFalse(report['lead_review_required'])

    def test_no_x_does_not_invent_preparation(self):
        clock=FrameClock(range(8),8)
        with patch('select_segment.features',return_value=([pose(i*4) for i in range(8)],1)), \
             patch('frame_sampling.FrameClock.read', return_value=clock):
            indices,report=sample_video('source',0,7,motion_type='hold_end_pose',seconds=1)
        self.assertEqual(report['phases']['x']['indices'],[])
        self.assertTrue(report['lead_review_required'])
        self.assertEqual(report['budget']['y_ms'],1000)

    def test_static_x_does_not_fill_budget_with_copies(self):
        clock=FrameClock(range(30),30)
        x=lead_samples([pose(2)]*20,clock,0,20,30,160)
        self.assertEqual(len(x['indices']),1)
        self.assertEqual(sum(x['ticks']),30)

    def test_x_rejected_for_other_types(self):
        for kind in ('loop','return_to_start',None):
            with self.assertRaisesRegex(ValueError,'lead_start'):
                sample_video('unused',10,20,motion_type=kind,lead_start=0,seconds=1)

    def test_return_without_stable_runs_still_uses_matching_endpoints(self):
        images=[pose(i) for i in (2,9,16,23,30,23,16,9,2)]
        result=locate(images,'return_to_start',stable_threshold=0)
        self.assertEqual(result['status'],'selected')
        self.assertEqual((result['start'],result['end']),(0,8))

    def test_phase_budget_cannot_be_silently_stretched(self):
        clock=FrameClock(range(12),12)
        with patch('select_segment.features',return_value=([pose(2),pose(20),pose(32)],1)), \
             patch('frame_sampling.FrameClock.read',return_value=clock):
            with self.assertRaisesRegex(ValueError,'Too many images'):
                sample_video('source',9,11,motion_type='hold_end_pose',lead_start=0,seconds=.08)


if __name__=='__main__':
    unittest.main()
