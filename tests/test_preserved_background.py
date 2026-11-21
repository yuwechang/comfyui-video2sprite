import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import prepare_character as p


class PreservedBackgroundTests(unittest.TestCase):
    def test_row_colors_extend_and_original_pixels_are_preserved(self):
        image=Image.new('RGB',(4,6),(130,130,130))
        ImageDraw.Draw(image).rectangle((0,4,3,5),fill=(90,90,90))
        image.putpixel((1,2),(255,0,0))
        out=p.extend_edges(image,(10,12),(3,3))
        self.assertEqual(out.crop((3,3,7,9)).tobytes(),image.tobytes())
        self.assertEqual(out.getpixel((0,6)),(130,)*3)
        self.assertEqual(out.getpixel((9,7)),(90,)*3)
        self.assertEqual(out.getpixel((0,0)),(130,)*3)
        self.assertEqual(out.getpixel((9,11)),(90,)*3)

    def test_ground_distance_is_fixed_and_resume_uses_original(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            im=Image.new('RGB',(100,200),(130,)*3)
            draw=ImageDraw.Draw(im);draw.rectangle((0,160,99,199),fill=(90,)*3)
            draw.rectangle((30,10,70,180),fill=(220,50,50));im.save(root/'source.png')
            args=argparse.Namespace(image=str(root/'source.png'),output=str(root/'out'),side=200,
                multiple_x=32,multiple_y=32,video_profile=None,background_mode='preserve',
                subject_box=[30,10,71,181],ground_anchor=[50,181],bottom_ratio=.12)
            with patch.object(p,'process',side_effect=AssertionError('Must not remove background')):
                r=p.prepare(args)
                self.assertLessEqual(abs(r['geometry']['height']-r['placement']['anchor'][1]
                                        -r['geometry']['side']*.12),1)
                with Image.open(r['prepared']) as out:
                    self.assertEqual(out.getpixel((0,0)),(130,)*3)
                    self.assertEqual(out.getpixel((0,out.height-1)),(90,)*3)
                args.image=r['prepared'];args.output=str(root/'repeat')
                args.preparation=str(root/'out/preparation.json');args.bottom_ratio=None
                again=p.prepare(args)
                self.assertEqual(Path(r['prepared']).read_bytes(),Path(again['prepared']).read_bytes())
                self.assertEqual(again['geometry']['bottom_ratio'],.12)

    def test_missing_contact_data_is_not_guessed_from_floor_or_shadow(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);Image.new('RGB',(100,200),(130,)*3).save(root/'source.png')
            args=argparse.Namespace(image=str(root/'source.png'),output=str(root/'out'),side=128,
                background_mode='preserve')
            with self.assertRaisesRegex(ValueError,'subject_box and ground_anchor'):p.prepare(args)


if __name__=='__main__':unittest.main()
