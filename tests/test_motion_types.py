import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import spritesheet
from select_segment import locate


class MotionTypeTests(unittest.TestCase):
    def test_old_and_unknown_values_are_rejected_even_for_manual_intervals(self):
        for kind in ('continuous', 'paused', 'once', 'unknown'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                with self.assertRaisesRegex(ValueError, 'Unknown motion type'):
                    locate([Image.new('L', (8, 8))] * 8, kind)
                with patch.object(spritesheet.subprocess, 'run') as decode:
                    with self.assertRaisesRegex(ValueError, 'Unknown motion type'):
                        spritesheet.prepare('unused.mp4', folder, None, 4, 0, 12,
                                            .4, False, motion_type=kind)
                    decode.assert_not_called()

    def test_all_motion_types_export_infinite_gif_independent_of_motion_loop(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            frames = []
            for x in (2, 6, 10, 2):
                frame = Image.new('RGBA', (24, 32))
                ImageDraw.Draw(frame).rectangle((x, 5, x+5, 26), fill='red')
                frames.append(frame)
            sheet, columns, rows = spritesheet.pack(frames)
            sheet.save(root/'source.png')
            for kind in ('loop', 'return_to_start', 'hold_end_pose'):
                with self.subTest(kind=kind):
                    report = dict(frames=4, cell_width=24, cell_height=32,
                                  columns=columns, rows=rows, requested_seconds=.4,
                                  motion_type=kind, loop=kind == 'loop')
                    result = spritesheet.finish(root/'source.png', report, root/kind)
                    self.assertEqual(result['motion_type'], kind)
                    self.assertEqual(result['loop'], kind == 'loop')
                    with Image.open(result['preview']) as gif:
                        self.assertEqual(gif.info['loop'], 0)
                        self.assertEqual(gif.n_frames, 4)
                        duration = 0
                        for i in range(gif.n_frames):
                            gif.seek(i)
                            duration += gif.info['duration']
                        self.assertEqual(duration, 400)
                    saved = json.loads((root/kind/'animation.json').read_text())
                    self.assertEqual(saved['motion_type'], kind)

    def test_cli_choices_are_consistent(self):
        scripts = Path(__file__).parents[1]/'scripts'
        for name in ('select_segment.py', 'spritesheet.py', 'finish_animation.py'):
            with self.subTest(script=name):
                help_text = subprocess.check_output([sys.executable, str(scripts/name), '--help'], text=True)
                self.assertIn('{loop,return_to_start,hold_end_pose}', help_text)
                self.assertNotIn('paused', help_text)


if __name__ == '__main__':
    unittest.main()
