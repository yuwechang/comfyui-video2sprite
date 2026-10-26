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
    def test_standing_inset_and_pose_padding(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = character((40,80))
            source.putpixel((20,30), (12,34,56,100))
            source.save(root/'source.png')
            args = argparse.Namespace(image=str(root/'source.png'), image_profile='unused',
                                      job=str(root/'job'), output=str(root/'standing'))
            standing = pc.standing_reference(args)
            self.assertEqual(standing['canvas_size'], [60,100])
            self.assertEqual(standing['scale_side'], 100)
            with Image.open(standing['standing']) as normalized:
                box = pc.visible_mask(normalized).getbbox()
                self.assertEqual(box[3],98)
                self.assertEqual(standing['alignment']['padding'],2)
                self.assertEqual(standing['alignment']['factor'],1.2)
            args.standing_reference = str(root/'standing/standing.json')
            args.output = str(root/'pose')
            args.pad_top, args.pad_left, args.pad_right, args.pad_bottom = 12,7,9,0
            padded = pc.pose_input(args)
            self.assertEqual(padded['canvas_size'],[76,112])
            self.assertEqual(padded['standing_offset'],[7,12])
            self.assertEqual(padded['scale_side'],100)
            with Image.open(padded['image']) as image, Image.open(standing['standing']) as before:
                self.assertEqual(before.tobytes(),image.crop((7,12,67,112)).tobytes())

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

    def test_pose_review_translates_only_and_leaves_more_space_above_short_pose(self):
        import json
        pose=Image.new('RGBA',(512,768))
        ImageDraw.Draw(pose).rectangle((80,400,359,699),fill=(180,40,30,255))
        pose.putpixel((150,500),(12,34,56,100))
        aligned,info=pc.pose_with_inset(pose)
        bbox=info['after_bbox']
        self.assertEqual(info['scale'],1)
        self.assertEqual(bbox[3],752)
        self.assertGreater(bbox[1],16)
        self.assertEqual(pose.crop((80,400,360,700)).tobytes(),aligned.crop(bbox).tobytes())
        repeated,again=pc.pose_with_inset(aligned)
        self.assertEqual(again['offset'],[0,0])
        self.assertEqual(repeated.tobytes(),aligned.tobytes())
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            pose.save(root/'pose.png')
            args=argparse.Namespace(image=str(root/'pose.png'),image_profile='unused',
                                    job=str(root/'job'),output=str(root/'review'))
            with patch.object(pc,'process',side_effect=AssertionError('No AI needed')):
                report=pc.review_pose(args)
            self.assertTrue(Path(report['preview']).exists())
            saved=json.loads((root/'review/first-frame.json').read_text())
            self.assertEqual(saved['alignment']['after_bbox'],bbox)
        too_tall=Image.new('RGBA',(512,768))
        ImageDraw.Draw(too_tall).rectangle((100,0,200,767),fill='red')
        with self.assertRaises(ValueError):
            pc.pose_with_inset(too_tall)

    def test_fixed_canvas_scale_for_shorter_pose_and_top_extension(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            # Scale comes from 436x832, not from any pose's visible bounds.
            standing = Image.new('RGBA',(436,832))
            ImageDraw.Draw(standing).rectangle((100,0,335,831),fill='red')
            standing.save(root/'standing.png')
            (root/'standing.json').write_text(json.dumps({'standing':str(root/'standing.png'),
                'canvas_size':[436,832],'scale_side':832}))
            (root/'profile.json').write_text(json.dumps({'generation':{'max_pixels':5_000_000}}))
            args = argparse.Namespace(image=str(root/'standing.png'),side=256,multiple_x=32,
                multiple_y=32,image_profile='unused',job=str(root/'job'),output=str(root/'base'),
                standing_reference=str(root/'standing.json'),video_profile=str(root/'profile.json'))
            base = pc.prepare(args)
            crouch=Image.new('RGBA',(436,832))
            ImageDraw.Draw(crouch).rectangle((80,400,355,781),fill='red')
            crouch.save(root/'crouch.png')
            args.image,args.output=str(root/'crouch.png'),str(root/'crouch-out')
            short=pc.prepare(args)
            self.assertEqual(base['restore_scale'],short['restore_scale'])
            base_info=json.loads((root/'base/preparation.json').read_text())
            short_info=json.loads((root/'crouch-out/preparation.json').read_text())
            self.assertEqual(base_info['placement']['factor'],1)
            self.assertEqual(short_info['placement']['factor'],1)
            self.assertEqual(short_info['pose_alignment']['offset'][1],50)
            self.assertEqual(short_info['placement']['placed_bbox'][3],short['geometry']['box'][3])
            self.assertEqual(short_info['placement']['placed_bbox'][3]-short_info['placement']['placed_bbox'][1],382)
            pad_args=argparse.Namespace(standing_reference=str(root/'standing.json'),
                output=str(root/'padded'),pad_top=12)
            padded=pc.pose_input(pad_args)
            raised=Image.new('RGBA',(436,844))
            ImageDraw.Draw(raised).rectangle((100,0,335,843),fill='red')
            raised.save(root/'raised.png')
            args.image,args.output=str(root/'raised.png'),str(root/'raised-out')
            args.pose_input=str(root/'padded/pose-input.json')
            raised_result=pc.prepare(args)
            info=json.loads((root/'raised-out/preparation.json').read_text())
            self.assertEqual(info['placement']['factor'],1)
            self.assertEqual(raised_result['restore_scale'],256/832)
            self.assertEqual(info['placement']['placed_bbox'][1],raised_result['geometry']['box'][1]-12)
            self.assertEqual(info['placement']['placed_bbox'][3]-info['placement']['placed_bbox'][1],844)
            with Image.open(raised_result['prepared']) as image:
                self.assertEqual(image.crop(info['placement']['placed_bbox']).tobytes(),
                                 Image.new('RGB',(236,844),'red').tobytes())
            args.image = raised_result['prepared']
            for name in ('repeat1','repeat2'):
                args.output = str(root/name)
                repeated = pc.prepare(args)
                self.assertEqual(Path(repeated['prepared']).read_bytes(),Path(raised_result['prepared']).read_bytes())
                args.image = repeated['prepared']

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
                                      output=str(root/'out'), pose_file=None, video_profile=str(root/'profile.json'))
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
                                      output=str(root/'base'), pose_file=None)
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
                                      job=str(root / 'job'), output=str(root / 'out'), pose_file=None)
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
                                      output=str(root / 'out'), pose_file=None)
            with patch.object(pc, 'process', return_value={'file': str(root / 'cutout.png')}) as process:
                pc.prepare(args)
                self.assertEqual(process.call_count, 1)

    def test_alignment_preserves_every_character_pixel(self):
        g = pc.layout(128)
        pose = Image.new('RGBA', (g['width'], g['height']))
        draw = ImageDraw.Draw(pose)
        draw.rectangle((40, 100, 99, 179), fill=(180, 50, 30, 255))
        pose.putpixel((60, 110), (12, 34, 56, 100))
        shifted, info = pc.align_pose(pose, g)
        bbox = info['after_bbox']
        self.assertEqual(bbox[3], g['box'][3])
        self.assertEqual((bbox[0] + bbox[2]) / 2, g['width'] / 2)
        self.assertEqual(pose.crop((40, 100, 100, 180)).tobytes(), shifted.crop(bbox).tobytes())
        unchanged, second = pc.align_pose(shifted, g)
        self.assertEqual(second['offset'], [0, 0])
        self.assertEqual(shifted.tobytes(), unchanged.tobytes())

    def test_alignment_can_move_up_and_reject_clipping(self):
        g = pc.layout(128)
        pose = Image.new('RGBA', (g['width'], g['height']))
        ImageDraw.Draw(pose).rectangle((150, 160, 209, 219), fill='red')
        shifted, info = pc.align_pose(pose, g)
        self.assertLess(info['offset'][0], 0)
        self.assertLess(info['offset'][1], 0)
        self.assertEqual(pc.visible_mask(shifted).getbbox()[3], g['box'][3])
        ImageDraw.Draw(pose).rectangle((150, 0, 209, 223), fill='red')
        with self.assertRaisesRegex(ValueError, 'clipping'):
            pc.align_pose(pose, g)


if __name__ == '__main__':
    unittest.main()
