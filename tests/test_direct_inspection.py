import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from diagnostics import inspect_result
from workflow_ops import source


class DirectInspectionTests(unittest.TestCase):
    def test_selected_frames_are_read_directly_without_new_review_images(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);paths=[]
            for i in range(2):
                path=root/f'{i}.png';Image.new('RGB',(8,8)).save(path);paths.append(str(path))
            result=inspect_result({'selected_frames':paths,'sample_indices':[0,2],
                                   'frame_durations_ms':[100,100]},root/'checks')
            self.assertEqual(result['pictures'],paths)
            self.assertEqual(result['playback'],[])
            self.assertFalse(list((root/'checks').glob('*.png')))

    def test_source_check_keeps_original_video_without_review_transcoding(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch('source_clock.FrameClock.read',return_value=SimpleNamespace(pts=[0,1])), \
                    patch('check_video_bounds.check',return_value={'frames':2}):
                result=source(root/'source.mp4',root/'checks')
            self.assertEqual(result['video'],str((root/'source.mp4').resolve()))
            self.assertNotIn('overview',result)
            self.assertEqual([p.suffix for p in (root/'checks').iterdir()],['.json'])


if __name__=='__main__':unittest.main()
