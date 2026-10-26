import argparse
import importlib.util
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
spec = importlib.util.spec_from_file_location('prepare_character', Path(__file__).parents[1] / 'scripts/prepare_character.py')
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)


def character(size=(90, 180)):
    im = Image.new('RGBA', (size[0] + 20, size[1] + 20))
    ImageDraw.Draw(im).rectangle((10, 10, 10 + size[0] - 1, 10 + size[1] - 1), fill='red')
    return im


class PreparationTests(unittest.TestCase):
    def test_standing_uses_ground_anchor_instead_of_accessory_bounds(self):
        image=Image.new('RGBA',(512,768))
        draw=ImageDraw.Draw(image)
        draw.rectangle((290,30,350,730),fill='red')
        draw.rectangle((90,70,289,140),fill='red')
        result,info=pc.reference_with_inset(image)
        self.assertAlmostEqual(info['anchor'][0],256,delta=.5)
        self.assertAlmostEqual(info['anchor'][1],752,delta=.5)
        box=pc.visible_mask(result).getbbox()
        self.assertLess((box[0]+box[2])/2,256)
        self.assertGreaterEqual(box[0],16)
        self.assertGreaterEqual(box[1],16)
        g=pc.generation_layout(256,768)
        placed,details=pc.place_at_scale(result,g,768,info['anchor'])
        self.assertAlmostEqual(details['anchor'][0],g['width']/2,delta=.5)
        self.assertAlmostEqual(details['anchor'][1],g['box'][3],delta=.5)

    def test_standing_metadata_preserves_anchor(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            character().save(root/'input.png')
            args=argparse.Namespace(image=str(root/'input.png'),image_profile='unused',
                                   job=str(root/'job'),output=str(root/'reference'))
            report=pc.standing_reference(args)
            self.assertEqual(report['anchor'],report['alignment']['anchor'])
            self.assertTrue(Path(report['preview']).is_file())
            saved=json.loads((root/'reference/standing.json').read_text())
            self.assertEqual(saved['anchor'],report['anchor'])
    def test_review_panels_preserve_alpha_and_do_not_modify_source(self):
        image=Image.new('RGBA',(128,192))
        ImageDraw.Draw(image).rectangle((40,20,79,150),fill=(180,40,30,255))
        original=image.tobytes()
        with tempfile.TemporaryDirectory() as folder:
            path=pc.save_preview(image,Path(folder))
            with Image.open(path) as preview:
                self.assertEqual(preview.size,(280,228))
                self.assertEqual(preview.crop((0,36,128,228)).tobytes(),original)
                self.assertEqual(preview.getpixel((152,36)),(128,128,128,255))
                self.assertEqual(preview.getpixel((156,40)),(255,190,0,255))
            self.assertEqual(image.tobytes(),original)


    def test_reference_inset_512_by_768(self):
        self.assertEqual(pc.inset_box((512,768)),(16,[16,16,496,752]))
        image=Image.new('RGBA',(512,768))
        ImageDraw.Draw(image).rectangle((100,10,399,709),fill='red')
        result, info=pc.reference_with_inset(image)
        box=pc.visible_mask(result).getbbox()
        self.assertEqual(result.size,image.size)
        self.assertEqual(box[3],752)
        self.assertGreaterEqual(box[0],16)
        self.assertGreaterEqual(box[1],16)
        self.assertLessEqual(box[2],496)
        self.assertLessEqual(abs((box[0]+box[2])/2-256),.5)



    def test_generation_layout_uses_native_detail_and_fractional_restore(self):
        g = pc.generation_layout(128, 832, max_pixels=5_000_000)
        self.assertEqual(g['side'], 832)
        self.assertEqual(g['generation_scale'], 6.5)
        self.assertEqual(g['restore_scale'], 128/832)
        capped = pc.generation_layout(128, 832)
        self.assertLess(capped['side'], 832)
        self.assertLessEqual(__import__('math').prod(capped['unaligned_size']), 1_000_000)
        self.assertEqual(capped['width'] % 32, 0)
        self.assertEqual(capped['height'] % 32, 0)
        self.assertGreater(capped['width']*capped['height'], 1_000_000)
        self.assertEqual(capped['restore_scale'], 128/capped['side'])
        expanded = pc.generation_layout(128, 832, expand_horizontal=1, expand_top=1)
        self.assertLess(expanded['side'], capped['side'])
        self.assertLessEqual(__import__('math').prod(expanded['unaligned_size']), 1_000_000)

    def test_small_source_and_native_scale(self):
        small = pc.generation_layout(256, 64)
        self.assertEqual((small['side'], small['restore_scale']), (256, 1))
        self.assertEqual((small['width'], small['height']), (512, 416))
        source = character((90,180))
        g = pc.generation_layout(128, max(source.size))
        fitted, info = pc.place_at_scale(source, g, max(source.size))
        self.assertEqual(info['factor'], 1)
        bbox = pc.visible_mask(source).getbbox()
        self.assertEqual(source.crop(bbox).tobytes(), fitted.crop(info['placed_bbox']).tobytes())

    def test_local_profile_controls_pixel_budget_and_alignment(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            character((458,832)).save(root/'input.png')
            (root/'profile.json').write_text(json.dumps({'generation': {
                'max_pixels': 300_000, 'width_multiple':64, 'height_multiple':32}}))
            args = argparse.Namespace(image=str(root/'input.png'), side=128, multiple_x=32,
                                      multiple_y=32, image_profile='unused', job=str(root/'job'),
                                      output=str(root/'out'), video_profile=str(root/'profile.json'))
            with patch.object(pc, 'process', side_effect=AssertionError('No AI needed')):
                result = pc.prepare(args)
            self.assertLessEqual(__import__('math').prod(result['geometry']['unaligned_size']), 300_000)
            self.assertEqual(result['geometry']['width'] % 64, 0)
            self.assertEqual(result['restore_scale'], 128/result['geometry']['side'])

    def test_extra_layout_preserves_base_and_bottom(self):
        self.assertEqual((pc.layout(256, expand_horizontal=1)['width'], pc.layout(256, expand_horizontal=1)['height']), (640, 416))
        self.assertEqual((pc.layout(256, expand_top=1)['width'], pc.layout(256, expand_top=1)['height']), (512, 480))
        for side in (65, 128, 255, 256):
            g = pc.layout(side, 32, 64, 2, 1)
            self.assertEqual(g['box'][2]-g['box'][0], side)
            self.assertEqual(g['box'][3]-g['box'][1], side)
            self.assertEqual(g['height']-g['box'][3], __import__('math').ceil(side*.07))
            self.assertEqual(g['width'] % 32, 0)
            self.assertEqual(g['height'] % 64, 0)
        with self.assertRaises(ValueError):
            pc.layout(256, expand_top=-1)

    def test_grayscale_selection_tracks_outline_brightness(self):
        values = []
        for brightness in (0, 32, 64, 102, 128, 153, 192, 224, 255):
            subject = character()
            subject.paste((brightness,)*3+(255,), (10, 10, 100, 190))
            color = pc.choose_background(subject)
            self.assertEqual(len(set(color)), 1)
            self.assertTrue(64 <= color[0] <= 191)
            values.append(color[0])
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertEqual(values[4], 128)
        self.assertEqual(values[0], 191)
        self.assertEqual(values[-1], 64)
        mixed = character()
        mixed.paste((128,128,128,255), (10,10,100,190))
        ImageDraw.Draw(mixed).rectangle((20,20,80,180), fill='white')
        self.assertEqual(pc.choose_background(mixed), (128,)*3)

    def test_expand_prepared_and_resume_preserves_pixels(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            character().save(root / 'input.png')
            args = argparse.Namespace(image=str(root/'input.png'), side=128, multiple_x=32,
                                      multiple_y=32, image_profile='unused', job=str(root/'job'),
                                      output=str(root/'base'))
            with patch.object(pc, 'process', side_effect=AssertionError('No AI needed')):
                base = pc.prepare(args)
                args.image = base['prepared']
                args.expand_horizontal = 1
                args.expand_top = 1
                args.output = str(root/'expanded')
                expanded = pc.prepare(args)
                g0, g1 = base['geometry'], expanded['geometry']
                with Image.open(base['prepared']) as before, Image.open(expanded['prepared']) as after:
                    dx, dy = g1['box'][0]-g0['box'][0], g1['box'][3]-g0['box'][3]
                    self.assertEqual(before.tobytes(), after.crop((dx,dy,dx+before.width,dy+before.height)).tobytes())
                args.image = expanded['prepared']
                args.preparation = str(root/'expanded/preparation.json')
                args.output = str(root/'repeat')
                repeated = pc.prepare(args)
                self.assertEqual(Path(expanded['prepared']).read_bytes(), Path(repeated['prepared']).read_bytes())
                args.expand_horizontal = 2
                args.expand_top = None
                args.output = str(root/'more')
                more = pc.prepare(args)
                self.assertEqual(more['geometry']['width'], 608)
                self.assertEqual(more['geometry']['expand_top'], 1)
                report = json.loads((root/'more/preparation.json').read_text())
                self.assertEqual(report['geometry']['expand_horizontal'], 2)

    def test_layout_and_alignment(self):
        g = pc.layout(256)
        self.assertEqual((g['width'], g['height']), (512, 416))
        self.assertEqual(g['box'], [128, 142, 384, 398])
        self.assertEqual(g['margins']['bottom'], 18)
        g = pc.layout(128)
        self.assertEqual((g['width'], g['height']), (256, 224))
        self.assertEqual(g['margins']['bottom'], 9)
        for side in (65, 127, 192, 256):
            g = pc.layout(side, 32, 64)
            self.assertEqual(g['width'] % 32, 0)
            self.assertEqual(g['height'] % 64, 0)
            self.assertEqual(g['box'][3], g['height'] - g['margins']['bottom'])

    def test_fit_non_square(self):
        g = pc.layout(128)
        im, details = pc.place_at_scale(character(), g, 180)
        x0, y0, x1, y1 = details['placed_bbox']
        self.assertEqual((x1 - x0, y1 - y0), (64, 128))
        self.assertEqual(y1, g['box'][3])
        self.assertEqual((x0 + x1) / 2, g['width'] / 2)

    def test_detect_and_reject_wrong_layout(self):
        g = pc.layout(128)
        subject, _ = pc.place_at_scale(character(), g, 180)
        good = pc.flatten(subject, (40, 180, 200))
        self.assertTrue(pc.detect_prepared(good, g)['prepared'])
        self.assertFalse(pc.detect_prepared(Image.new('RGB', good.size, (40, 180, 200)), g)['prepared'])
        bad = good.copy()
        ImageDraw.Draw(bad).rectangle((5, 50, 40, 190), fill='red')
        self.assertFalse(pc.detect_prepared(bad, g)['prepared'])
        self.assertFalse(pc.detect_prepared(character(), g)['prepared'])

    def test_jpeg_tolerance(self):
        g = pc.layout(256)
        subject, _ = pc.place_at_scale(character(), g, 180)
        good = pc.flatten(subject, (20, 170, 210))
        buffer = BytesIO()
        good.save(buffer, format='JPEG', quality=85)
        buffer.seek(0)
        with Image.open(buffer) as decoded:
            self.assertTrue(pc.detect_prepared(decoded, g)['prepared'])

    def test_borderline_rechecks_original(self):
        g = pc.layout(128)
        subject, _ = pc.place_at_scale(character(), g, 180)
        image = pc.flatten(subject, (40, 180, 200))
        ImageDraw.Draw(image).rectangle((5, 50, 9, 99), fill='red')
        detected = pc.detect_prepared(image, g)
        self.assertEqual(detected['scan_size'], list(image.size))
        self.assertFalse(detected['prepared'])

    def test_repeat_does_not_reextract_or_refit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            character().save(root / 'input.png')
            args = argparse.Namespace(image=str(root / 'input.png'), side=128, multiple_x=32,
                                      multiple_y=32, image_profile='unused.json',
                                      job=str(root / 'job'), output=str(root / 'out'))
            with patch.object(pc, 'process', side_effect=AssertionError('No AI needed')):
                first = pc.prepare(args)
                args.image = first['prepared']
                args.output = str(root / 'out2')
                second = pc.prepare(args)
            self.assertEqual(Path(first['prepared']).read_bytes(), Path(second['prepared']).read_bytes())

    def test_background_input_uses_image_workflow_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            im = character()
            im.save(root / 'cutout.png')
            pc.flatten(im, (255, 255, 255)).save(root / 'input.png')
            args = argparse.Namespace(image=str(root / 'input.png'), side=128, multiple_x=32,
                                      multiple_y=32, image_profile='image.json', job=str(root / 'job'),
                                      output=str(root / 'out'))
            with patch.object(pc, 'process', return_value={'file': str(root / 'cutout.png')}) as process:
                pc.prepare(args)
                self.assertEqual(process.call_count, 1)




if __name__ == '__main__':
    unittest.main()
