import unittest
import shutil
import subprocess
import tempfile
from fractions import Fraction
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from source_clock import FrameClock,phase_budget,allocate_ticks,y_weights,representative_x

class ClockTests(unittest.TestCase):
 def cfr(self,fps=30,seconds=3):return FrameClock([Fraction(i,fps) for i in range(fps*seconds)],seconds)
 def test_one_third_x_never_exceeds_cap(self):
  c=self.cfr();b=phase_budget(c,0,30,89,1)
  self.assertEqual(b['x_ms'],320);self.assertEqual(b['y_ms'],680);self.assertEqual(b['actual_total_ms'],1000);self.assertLessEqual(b['x_ms'],b['ideal_x_ms']);self.assertLess(b['ideal_x_ms']-b['x_ms'],20)
 def test_multiple_fps_same_source_time(self):
  results=[phase_budget(self.cfr(fps),0,fps,fps*3-1,1) for fps in (24,30,60)]
  self.assertEqual({(r['x_ms'],r['y_ms']) for r in results},{(320,680)})
 def test_variable_timestamps(self):
  c=FrameClock([0,.1,.4,.6,1,1.5,2.5],3);b=phase_budget(c,0,4,6,1)
  self.assertEqual((b['x_ms'],b['y_ms']),(320,680));self.assertEqual(b['source_total_seconds'],3)
 def test_more_frames_does_not_add_time(self):
  b=phase_budget(self.cfr(),0,30,89,1)
  for count in (1,3,5,10):
   ticks=allocate_ticks([1]*count,b['x_ticks']);self.assertEqual(sum(ticks)*20,b['x_ms']);self.assertTrue(all(t>=1 for t in ticks))
 def test_y_weights_cover_phase(self):
  c=self.cfr();w=y_weights(c,[30,45,70,89],30,89);self.assertEqual(sum(w),2);self.assertTrue(all(x>0 for x in w))
 def test_boundary_owned_by_y_only(self):
  c=self.cfr();b=phase_budget(c,0,30,89,1);x=representative_x(c,0,30,b['x_ticks']);self.assertTrue(all(0<=i<30 for i in x['indices']));self.assertEqual(sum(x['ticks']),b['x_ticks']);self.assertEqual(b['source_x_seconds']+b['source_y_seconds'],b['source_total_seconds'])
 def test_x_count_follows_time_not_fixed(self):
  c=self.cfr();short=representative_x(c,0,30,8);long=representative_x(c,0,30,24)
  self.assertEqual(len(short['indices']),1);self.assertEqual(len(long['indices']),3)
 def test_truly_static_x_remains_one(self):
  c=self.cfr();x=representative_x(c,0,30,40,static=True);self.assertEqual(len(x['indices']),1);self.assertEqual(sum(x['ticks']),40)
 def test_no_x(self):
  c=self.cfr();b=phase_budget(c,0,0,89,1);self.assertEqual(b['x_ms'],0);self.assertEqual(b['y_ms'],1000)
 def test_cannot_stretch_to_fit_images(self):
  with self.assertRaises(ValueError):allocate_ticks([1]*20,16)
 def test_invalid_timestamps(self):
  with self.assertRaises(ValueError):FrameClock([0,.2,.1],1)
 def test_subresolution_x_is_reported(self):
  c=self.cfr()
  with self.assertRaisesRegex(ValueError,'Phase budget'):phase_budget(c,0,1,89,.1)

 @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
 def test_read_real_variable_rate_video_timestamps(self):
  with tempfile.TemporaryDirectory() as folder:
   video=Path(folder)/'variable.mkv'
   subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',
    'color=size=32x32:rate=10:duration=0.6','-vf',
    r'setpts=if(lt(N\,3)\,N\,3+2*(N-3))/(10*TB)',
    '-fps_mode','vfr','-c:v','ffv1',str(video)],check=True)
   c=FrameClock.read(video)
   self.assertEqual(len(c.pts),6)
   self.assertGreater(len({b-a for a,b in zip(c.pts,c.pts[1:])}),1)
   budget=phase_budget(c,0,3,5,1)
   expected=1000*(c.boundary(3)-c.boundary(0))/(c.boundary(6)-c.boundary(0))
   self.assertLessEqual(budget['x_ms'],expected)
   self.assertLess(expected-budget['x_ms'],20)
   self.assertEqual(sum(y_weights(c,[3,5],3,5)),c.boundary(6)-c.boundary(3))

if __name__=='__main__':unittest.main()
