import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from keyframe_background import compose,normalize,digest
from workflow_ops import video
from material_contract import requirements


class BackgroundTests(unittest.TestCase):
    def sources(self,root):
        paths=[];masks=[]
        for i,factor in enumerate((1,2)):
            image=Image.new('RGB',(80*factor,100*factor),(110+i*40,100,100))
            ImageDraw.Draw(image).rectangle((0,70*factor,80*factor,100*factor),fill=(40+i*30,40,40))
            mask=Image.new('L',image.size)
            ImageDraw.Draw(mask).rectangle((30*factor,20*factor,49*factor,89*factor),fill=255)
            image.paste((220,30,20),(30*factor,20*factor,50*factor,90*factor))
            path=root/f'source-{i}.png';alpha=root/f'mask-{i}.png';image.save(path);mask.save(alpha)
            paths.append(str(path));masks.append(str(alpha))
        return paths,masks

    def test_shared_background_preserves_foreground_and_canvas_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);images,masks=self.sources(root)
            result=compose(images,masks,root/'out',False)
            self.assertEqual(result['canvas_size'],[80,100])
            self.assertEqual(result['background_geometry']['boundary_y'],70)
            first=Image.open(result['images'][0]);last=Image.open(result['images'][1])
            self.assertEqual(first.getpixel((0,5)),last.getpixel((0,5)))
            self.assertEqual(first.getpixel((0,95)),last.getpixel((0,95)))
            self.assertEqual(first.getpixel((40,40)),(220,30,20))
            self.assertEqual(last.getpixel((40,40)),(220,30,20))
            self.assertLessEqual(abs(result['subject_boxes'][0][3]-result['subject_boxes'][1][3]),1)

    def test_misaligned_aspect_ratio_is_rejected_instead_of_silent_crop(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);images,masks=self.sources(root)
            Image.new('RGB',(100,100)).save(images[1]);Image.new('L',(100,100),255).save(masks[1])
            with self.assertRaisesRegex(ValueError,'aspect ratios'):compose(images,masks,root/'out')

    def test_resume_verifies_contract_and_outputs_without_resubmitting_masks(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);images,masks=self.sources(root);profile=root/'profile.json';profile.write_text('{}')
            with patch('process_image.process',side_effect=[{'file':p} for p in masks]) as process:
                first=normalize(images,str(profile),root/'jobs',root/'out')
                second=normalize(images,str(profile),root/'jobs',root/'out')
                self.assertEqual(first,second);self.assertEqual(process.call_count,2)
                Image.new('RGB',(80,100)).save(first['images'][0])
                with self.assertRaisesRegex(ValueError,'changed'):normalize(images,str(profile),root/'jobs',root/'out')

    def test_video_wrapper_only_changes_images_when_option_is_explicit(self):
        kwargs=dict(profile='video.json',image='first.png',image2='last.png',prompt_file='prompt.txt',
                    job='video-job',width=80,height=100,seconds=3,seed=1)
        with patch('generate.run',return_value={}) as run,patch('keyframe_background.normalize') as normal:
            video(**kwargs);normal.assert_not_called()
            self.assertEqual(run.call_args.args[0].image,'first.png')
            normal.return_value={'images':['new-first.png','new-last.png']}
            result=video(**kwargs,keyframe_background={'profile':'alpha.json','job':'masks','output':'normalized'})
            self.assertEqual(run.call_args.args[0].image2,'new-last.png')
            self.assertIn('keyframe_background',result)

    def test_normalized_inputs_and_plate_are_required_delivery_materials(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);paths=[]
            for i in range(9):
                path=root/f'asset-{i}.png';path.write_bytes(bytes([i]));paths.append(str(path))
            normalized=dict(background=paths[0],report_file=paths[1],profile=paths[2],
                images=paths[3:5],source_images=paths[5:7],source_masks=paths[7:9])
            plan=argparse.Namespace(config={'tasks':[{'id':'a','steps':[{'id':'video','operation':'video','args':{}}]}]},
                state={'tasks':{'a':{'steps':{'video':{'status':'completed','result':{'keyframe_background':normalized}}}}}},
                resolve=lambda value:value)
            inventory={str(i):{'path':p,'sha256':digest(p)} for i,p in enumerate(paths)}
            files={str(i):p for i,p in enumerate(paths)}
            self.assertEqual(len(requirements(plan,'a',inventory,files)),9)
            files.pop('0')
            with self.assertRaisesRegex(ValueError,'Missing registered'):requirements(plan,'a',inventory,files)


if __name__=='__main__':unittest.main()
