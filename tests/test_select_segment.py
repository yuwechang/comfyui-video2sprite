import sys
from pathlib import Path
import unittest
import tempfile
import subprocess
import shutil
from unittest.mock import patch
from PIL import Image,ImageDraw

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from select_segment import locate


def pose(x):
    image=Image.new('L',(48,64))
    ImageDraw.Draw(image).rectangle((x,16,x+9,54),fill=220)
    return image


class SegmentTests(unittest.TestCase):
    def test_continuous_excludes_matching_tail(self):
        images=[pose(x) for x in [4,4,4,8,12,16,20,16,12,8,4,8,12,16,20,16,12,8,4]]
        result=locate(images,'continuous',count=6,stable_threshold=.01)
        self.assertEqual(result['status'],'selected')
        self.assertEqual(result['end'],result['matching_tail']-1)
        self.assertTrue(result['loop'])

    def test_paused_includes_head_and_tail(self):
        images=[pose(x) for x in [2,2,2,8,8,8,12,18,24,18,12,8,8,8]]
        result=locate(images,'paused',count=4,stable_threshold=.01)
        self.assertEqual((result['start'],result['end']),(5,11))
        self.assertFalse(result['loop'])
        self.assertEqual(result['seam_distance'],0)

    def test_once_uses_last_preparation_not_initial_standing(self):
        images=[pose(x) for x in [2,2,2,6,10,10,10,16,22,28,34,34,34]]
        result=locate(images,'once',count=4,stable_threshold=.01)
        self.assertEqual((result['start'],result['end']),(6,10))

    def test_static_clip_is_not_a_loop(self):
        self.assertEqual(locate([pose(8)]*20,'continuous')['status'],'needs_review')

    def test_paused_can_finish_before_a_later_transition(self):
        images=[pose(x) for x in [2,2,2,8,8,8,12,18,24,18,12,8,8,8,20,30]]
        result=locate(images,'paused',count=4,stable_threshold=.01)
        self.assertEqual((result['start'],result['end']),(5,11))

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
                                            .6,False,motion_type='continuous')
            selected=result['automatic_selection']
            self.assertEqual(selected['end'],selected['matching_tail']-1)
            self.assertLess(max(result['sample_indices']),selected['matching_tail'])
            self.assertEqual(len(result['sample_indices']),6)


if __name__=='__main__':unittest.main()
