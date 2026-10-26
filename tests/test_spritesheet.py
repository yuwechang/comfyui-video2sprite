import importlib.util
from pathlib import Path
import unittest
from PIL import Image, ImageDraw
import tempfile

spec = importlib.util.spec_from_file_location('spritesheet', Path(__file__).parents[1] / 'scripts/spritesheet.py')
sheet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sheet)


class SheetTests(unittest.TestCase):
    def test_transparent_gif_has_no_trails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = Image.new('RGBA', (40, 20))
            draw = ImageDraw.Draw(image)
            draw.rectangle((2, 5, 6, 10), fill=(255, 0, 0, 255))
            draw.rectangle((32, 5, 36, 10), fill=(0, 0, 255, 255))
            image.putpixel((1, 1), (255, 255, 255, 127))
            image.putpixel((8, 8), (255, 255, 255, 128))
            image.save(root / 'input.png')
            result = sheet.finish(root / 'input.png', {'cell_width': 20, 'cell_height': 20,
                                  'columns': 2, 'rows': 1, 'frames': 2,
                                  'requested_seconds': .2, 'loop': False}, root / 'out')
            with Image.open(result['preview']) as gif:
                self.assertEqual(gif.n_frames, 2)
                self.assertEqual(gif.info['loop'], 0)
                self.assertFalse(result['loop'])
                first = gif.convert('RGBA')
                self.assertEqual(first.getpixel((1, 1))[3], 0)
                self.assertEqual(first.getpixel((8, 8))[3], 255)
                gif.seek(1)
                second = gif.convert('RGBA')
                self.assertEqual(second.getpixel((3, 6))[3], 0)
                self.assertEqual(second.getpixel((13, 6)), (0, 0, 255, 255))

    def test_rectangular_odd_layout(self):
        image, columns, rows = sheet.pack([Image.new('RGBA', (80, 120), (i, 0, 0, 255)) for i in range(7)])
        self.assertEqual((image.size, columns, rows), ((320, 240), 4, 2))
        self.assertEqual(image.getpixel((240, 120))[3], 0)
        self.assertEqual(image.getpixel((160, 120))[0], 6)

    def test_many_rows(self):
        for count in (13, 16, 18, 25):
            image, columns, rows = sheet.pack([Image.new('RGBA', (8, 12)) for _ in range(count)])
            self.assertEqual(columns, 6)
            self.assertEqual(rows, (count + 5) // 6)
            self.assertEqual(image.size, (columns * 8, rows * 12))

    def test_final_sheet_clears_empty_cells_and_gif_timing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = Image.new('RGBA', (60, 30), (255, 0, 0, 255))
            draw = ImageDraw.Draw(image)
            for i in range(13):
                draw.rectangle(((i % 6) * 10, (i // 6) * 10,
                                (i % 6) * 10 + 2, (i // 6) * 10 + 2), fill=(0, 0, 0, 0))
            image.save(root / 'input.png')
            report = {'cell_width': 10, 'cell_height': 10, 'columns': 6, 'rows': 3,
                      'frames': 13, 'requested_seconds': .8, 'loop': True}
            result = sheet.finish(root / 'input.png', report, root / 'out')
            with Image.open(result['sheet']) as output:
                self.assertEqual(output.getpixel((15, 25))[3], 0)
            self.assertEqual(result['verified']['gif_duration_ms'], 800)

    def test_reject_resized_or_opaque_sheet(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'image.png'
            report = {'cell_width': 10, 'cell_height': 10, 'columns': 2, 'rows': 1}
            Image.new('RGBA', (30, 10), 'red').save(path)
            with self.assertRaisesRegex(ValueError, 'dimensions'):
                sheet.finish(path, report, folder)
            Image.new('RGBA', (20, 10), 'red').save(path)
            with self.assertRaisesRegex(ValueError, 'transparent'):
                sheet.finish(path, report, folder)

    def test_uniform_selection(self):
        self.assertEqual(sheet.sample_indices(0, 35, 8, True), [0, 4, 9, 14, 18, 22, 27, 32])
        self.assertEqual(sheet.sample_indices(0, 35, 8, False)[-1], 35)


if __name__ == '__main__':
    unittest.main()
