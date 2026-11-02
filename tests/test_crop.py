import importlib.util
from io import BytesIO
import json
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import spritesheet as sheet
import finish_animation as pipeline


class CropTests(unittest.TestCase):
    def test_uniform_scale_before_crop_preserves_relative_motion(self):
        frames = [self.frame((20,22,35,51)), self.frame((30,7,54,48))]
        resized = sheet.scale_frames(frames, .625)
        self.assertEqual([frame.size for frame in resized], [(40,40)]*2)
        for before, after in zip(frames, resized):
            self.assertEqual(after.tobytes(), before.resize((40,40), Image.Resampling.LANCZOS).tobytes())
        cells, report = sheet.crop_frames(resized)
        self.assertEqual(report['source_size'], [40,40])
        self.assertEqual(cells[0].size, cells[1].size)
        # The wider pose remains wider; no per-pose fitting to a target box.
        self.assertGreater(report['source_content_boxes'][1][2]-report['source_content_boxes'][1][0],
                           report['source_content_boxes'][0][2]-report['source_content_boxes'][0][0])
        for invalid in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                sheet.scale_frames(frames, invalid)

    def test_background_colour_can_change_between_frames(self):
        first = self.frame((20, 20, 35, 51))
        second = Image.new('RGB', (64, 64), (175, 175, 175))
        ImageDraw.Draw(second).rectangle((22, 15, 37, 50), fill=(240, 40, 60))
        frames, report = sheet.crop_frames([first, second])
        self.assertEqual(report['frame_backgrounds'], [[20, 160, 220], [175, 175, 175]])
        self.assertEqual(report['source_content_boxes'], [[20, 20, 36, 52], [22, 15, 38, 51]])
        self.assertEqual(report['crop_box'], [20, 15, 44, 52])
        self.assertEqual(frames[1].getpixel((2, 0)), (240, 40, 60, 255))

    background = (20, 160, 220)

    def frame(self, rect):
        im = Image.new('RGB', (64, 64), self.background)
        ImageDraw.Draw(im).rectangle(rect, fill=(240, 40, 60))
        return im

    def test_symmetric_extension_uses_video_center(self):
        box = sheet.common_crop([(64, 20, 205, 100)], 256)
        self.assertEqual(box, [51, 20, 205, 100])
        self.assertEqual(box[2] - box[0], 154)
        self.assertEqual((box[0] + box[2]) / 2, 128)
        self.assertEqual(sheet.common_crop([(51, 5, 180, 90)], 256), [51, 5, 205, 90])
        self.assertEqual(sheet.common_crop([(30, 10, 34, 20)], 64), [30, 10, 34, 20])
        self.assertEqual(sheet.common_crop([(12, 1, 20, 10)], 65), [12, 1, 53, 10])

    def test_common_crop_retains_pixels_and_relative_motion(self):
        frames = [self.frame((20, 22, 35, 51)), self.frame((30, 7, 54, 48))]
        frames[0].putpixel((24, 25), (1, 2, 3))
        cropped, info = sheet.crop_frames(frames)
        self.assertEqual(info['crop_box'], [9, 7, 55, 52])
        self.assertEqual(cropped[0].size, cropped[1].size)
        self.assertEqual(cropped[0].size, (46, 46))
        for source, result in zip(frames, cropped):
            self.assertEqual(result.tobytes(), source.crop((9, 7, 55, 53)).convert('RGBA').tobytes())
        self.assertEqual(cropped[0].getpixel((24 - 9, 25 - 7)), (1, 2, 3, 255))
        self.assertEqual(cropped[1].getpixel((30 - 9, 7 - 7)), (240, 40, 60, 255))

    def test_padding_outside_source_has_same_background(self):
        source = self.frame((47, 40, 63, 63))
        cropped, info = sheet.crop_frames([source])
        self.assertEqual(info['crop_box'], [0, 40, 64, 64])
        self.assertEqual(cropped[0].getpixel((63, 23)), (240, 40, 60, 255))
        self.assertEqual(cropped[0].getpixel((63, 24)), (20, 160, 220, 255))
        source = self.frame((0, 10, 10, 30))
        cropped, info = sheet.crop_frames([source])
        self.assertEqual(info['crop_box'][2], 64)
        self.assertEqual(cropped[0].getpixel((63, 0)), (20, 160, 220, 255))

    def test_background_tolerance_keeps_thin_accessories_and_enclosed_colour(self):
        im = self.frame((20, 20, 35, 51))
        ImageDraw.Draw(im).line((35, 25, 55, 25), fill=(250, 200, 10), width=1)
        im.putpixel((0, 0), (30, 150, 235))
        self.assertEqual(sheet.content_bbox(im, self.background), (20, 20, 56, 52))
        im.putpixel((25, 25), self.background)
        cropped, info = sheet.crop_frames([im])
        left, top = info['crop_box'][:2]
        self.assertEqual(cropped[0].getpixel((25 - left, 25 - top)), (20, 160, 220, 255))

    def test_compressed_background_does_not_expand_to_canvas(self):
        im = self.frame((20, 20, 35, 51))
        buffer = BytesIO()
        im.save(buffer, format='JPEG', quality=85)
        buffer.seek(0)
        with Image.open(buffer) as decoded:
            box = sheet.content_bbox(decoded, self.background)
            self.assertGreater(box[0], 0)
            self.assertGreater(box[1], 0)
            self.assertLess(box[2], 64)
            self.assertLess(box[3], 64)
            self.assertLessEqual(box[0], 20)
            self.assertGreaterEqual(box[2], 36)

    def test_small_background_colour_block_is_ignored(self):
        image = self.frame((20, 20, 35, 51))
        ImageDraw.Draw(image).rectangle((5, 5, 9, 8), fill=(47, 160, 220))
        ImageDraw.Draw(image).line((35, 30, 50, 30), fill=(180, 80, 40), width=1)
        self.assertEqual(sheet.content_bbox(image, self.background), (20, 20, 51, 52))

    def test_unused_cells_have_background_before_removal(self):
        sheet_image, columns, rows = sheet.pack([Image.new('RGBA', (10, 20), 'red') for _ in range(7)],
                                               (20, 160, 220))
        self.assertEqual((columns, rows), (4, 2))
        self.assertEqual(sheet_image.getpixel((35, 30)), (20, 160, 220, 255))

    def test_mixed_frame_dimensions_rejected(self):
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            sheet.crop_frames([Image.new('RGB', (32, 32)), Image.new('RGB', (64, 64))])

    def test_scaling_is_shared_and_reserves_final_one_pixel(self):
        frames = [self.frame((2, 4, 61, 61)), self.frame((20, 15, 40, 50))]
        cropped, report = sheet.crop_frames(frames, max_side=20)
        self.assertLessEqual(max(cropped[0].size), 20)
        self.assertEqual(cropped[0].size, cropped[1].size)
        self.assertLess(report['scale'], 1)
        self.assertEqual(report['bottom_padding'], 1)
        for image in cropped:
            self.assertEqual(image.height, report['scaled_content_size'][1] + 1)
            for x in range(image.width):
                self.assertEqual(image.getpixel((x, image.height - 1)), self.background + (255,))

    def test_no_minimum_width_and_no_frontend_frame_requirement(self):
        image = Image.new('RGB', (97, 75), 'white')
        ImageDraw.Draw(image).rectangle((45, 10, 51, 60), fill='black')
        cells, report = sheet.crop_frames([image], max_side=128)
        self.assertEqual(report['source_size'], [97, 75])
        self.assertEqual(report['crop_box'], [45, 10, 52, 61])
        self.assertEqual(cells[0].size, (7, 52))
        self.assertEqual(report['scale'], 1)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg is required for video extraction')
    def test_real_video_selection_and_packing_without_resizing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            frames = [self.frame((20 + i, 20 - i, 35 + i, 51)) for i in range(8)]
            for i, frame in enumerate(frames):
                frame.save(root / f'{i:03}.png')
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-framerate', '10',
                            '-i', str(root / '%03d.png'), '-c:v', 'ffv1', '-pix_fmt', 'bgr0',
                            str(root / 'source.mkv')], check=True)
            with patch.object(Path, 'read_text', side_effect=AssertionError('No input metadata is available')):
                report = sheet.prepare(root / 'source.mkv', root / 'packed', 64, 8, 0, 7, .8, True)
                scaled_report = sheet.prepare(root / 'source.mkv', root / 'scaled', None, 8, 0, 7,
                                               .8, True, scale=.625)
            self.assertEqual(scaled_report['frame_scale'], .625)
            self.assertEqual(scaled_report['original_frame_size'], [64,64])
            self.assertEqual(scaled_report['source_size'], [40,40])
            expected_frames, expected = sheet.crop_frames(sheet.scale_frames(frames, .625))
            self.assertEqual(scaled_report['crop_box'], expected['crop_box'])
            self.assertEqual((scaled_report['cell_width'], scaled_report['cell_height']), expected_frames[0].size)
            self.assertEqual(report['sample_indices'], list(range(8)))
            self.assertEqual(report['crop_box'], [20, 13, 44, 52])
            self.assertEqual((report['cell_width'], report['cell_height']), (24, 40))
            for path, frame in zip(report['cropped_frames'], frames):
                with Image.open(path) as cropped:
                    self.assertEqual(cropped.tobytes(), frame.crop((20,13,44,53)).convert('RGBA').tobytes())


if __name__ == '__main__':
    unittest.main()
