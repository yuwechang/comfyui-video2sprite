import unittest,math
from PIL import Image,ImageDraw
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from frame_sampling import AdaptiveScorer,PROFILES

def pose(x):
 im=Image.new('L',(48,64));d=ImageDraw.Draw(im);d.rectangle((18,15,25,55),fill=180);d.rectangle((x,20,x+7,27),fill=240);return im

class AdaptiveTests(unittest.TestCase):
 def test_static_has_no_insertions(self):
  result=AdaptiveScorer([pose(4)]*80).select(.6)
  self.assertEqual(result['indices'],[0,79]);self.assertEqual(result['max_remaining_score'],0);self.assertEqual(result['insertions'],[])
 def test_four_poses_are_four_images_not_eight_anchors(self):
  images=[pose(x) for x in (4,12,28,8) for _ in range(20)]
  scorer=AdaptiveScorer(images)
  for threshold in PROFILES.values():
   result=scorer.select(threshold);self.assertEqual(result['count'],4)
   self.assertEqual(len({images[i].tobytes() for i in result['indices']}),4)
 def test_long_hold_does_not_require_extra_images(self):
  values=list(range(4,33,4))+list(range(28,3,-4))
  base=[pose(x) for x in values];held=base[:8]+[pose(32)]*60+base[8:];slower=[im for im in base for _ in range(3)]
  for threshold in PROFILES.values():
   results=[AdaptiveScorer(images).select(threshold) for images in (base,held,slower)]
   self.assertEqual(len({r['count'] for r in results}),1)
 def test_static_body_does_not_hide_arm_motion(self):
  images=[pose(x) for x in (4,12,28,8)]
  result=AdaptiveScorer(images).select(.6)
  self.assertEqual(result['indices'],[0,1,2,3])
 def test_small_intensity_noise_not_new_pose(self):
  base=pose(4);images=[]
  for shift in (0,2,1,0,2,0)*5:
   images.append(base.point(lambda v:min(255,v+shift) if v else 0))
  result=AdaptiveScorer(images).select(.2);self.assertEqual(result['count'],2)
 def test_stricter_tolerance_retains_existing_keys(self):
  images=[pose(x) for x in list(range(4,33,4))+list(range(28,3,-4))]
  scorer=AdaptiveScorer(images);a=scorer.select(.6);b=scorer.select(.2)
  self.assertTrue(set(a['indices'])<=set(b['indices']));self.assertGreaterEqual(b['count'],a['count'])
 def test_short_interval_not_forced_to_eight(self):
  result=AdaptiveScorer([pose(4),pose(28),pose(8)]).select(.2)
  self.assertEqual(result['indices'],[0,1,2])
 def test_scores_and_boundaries(self):
  images=[pose(x) for x in (4,8,12,20,28,20,12,8,4)]
  scorer=AdaptiveScorer(images)
  for threshold in (0,.2,.4,.6,1,10):
   result=scorer.select(threshold);indices=result['indices'];self.assertEqual(indices,sorted(set(indices)));self.assertEqual((indices[0],indices[-1]),(0,8))
   self.assertLessEqual(result['max_remaining_score'],threshold);self.assertLessEqual(result['count'],len(images))
   for insertion in result['insertions']:
    self.assertLess(insertion['left'],insertion['frame']);self.assertLess(insertion['frame'],insertion['right']);self.assertGreater(insertion['score'],threshold)
 def test_invalid_tolerance_rejected(self):
  scorer=AdaptiveScorer([pose(4),pose(8)])
  for threshold in (-1,float('nan'),float('inf')):
   with self.assertRaises(ValueError):scorer.select(threshold)

if __name__=='__main__':unittest.main()
