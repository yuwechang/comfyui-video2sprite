import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import background_removal as bg


class BackgroundTests(unittest.TestCase):
    def test_skip_refine_never_submits_a_generative_job(self):
        import finish_animation as pipeline
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'image.json').write_text('{}');(root/'prompt.txt').write_text('Unused planning prompt')
            rgb=Image.new('RGB',(8,8),(30,60,90));rgb.save(root/'source.png')
            rgba=rgb.convert('RGBA');rgba.putpixel((0,0),(30,60,90,0));rgba.save(root/'masked.png')
            report={'cropped_frames':[str(root/'source.png')],'sample_indices':[7],'frame_backgrounds':[(0,0,0)]}
            with patch.object(pipeline,'process',side_effect=AssertionError('No generative call')), \
                    patch.object(bg,'remove_background',return_value={'file':str(root/'masked.png')}) as mask, \
                    patch.object(pipeline,'finish_refined',side_effect=lambda r,records,*args:r):
                result=pipeline.finish_prepared(report,root/'image.json',root/'prompt.txt',root/'job',root/'output',
                                               background_profile='background.json',refine_required=False)
            self.assertFalse(result['image_edit_performed'])
            self.assertNotIn('refinement_prompt',result)
            self.assertEqual(Path(mask.call_args.args[1]).name,'input.png')

    def test_mask_profile_applies_alpha_once_without_changing_rgb(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'profile.json').write_text(json.dumps({'output_mode':'mask'}))
            source=Image.new('RGB',(3,1),(30,60,90));source.save(root/'source.png')
            alpha=Image.new('L',(3,1));alpha.putdata([0,128,255]);alpha.save(root/'alpha.png')
            with patch.object(bg,'process',return_value={'file':str(root/'alpha.png')}):
                result=bg.remove_background(root/'profile.json',root/'source.png',root/'job')
            with Image.open(result['file']) as output:
                self.assertEqual(output.convert('RGB').tobytes(),source.tobytes())
                self.assertEqual(list(output.getchannel('A').tobytes()),[0,128,255])

    def test_refine_rgb_output_is_masked_before_assembly(self):
        import finish_animation as pipeline
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'image.json').write_text('{}');(root/'prompt.txt').write_text('Preserve background')
            rgb=Image.new('RGB',(8,8),(30,60,90));rgb.save(root/'source.png');rgb.save(root/'edited.png')
            rgba=rgb.convert('RGBA');rgba.putpixel((0,0),(30,60,90,0));rgba.save(root/'masked.png')
            report={'cropped_frames':[str(root/'source.png')],'sample_indices':[7],'frame_backgrounds':[(0,0,0)]}
            with patch.object(pipeline,'process',return_value={'file':str(root/'edited.png')}), \
                    patch.object(bg,'remove_background',return_value={'file':str(root/'masked.png')}) as mask, \
                    patch.object(pipeline,'finish_refined',side_effect=lambda r,records,*args:(r,records)):
                result,records=pipeline.finish_prepared(report,root/'image.json',root/'prompt.txt',root/'job',root/'output',
                                                       background_profile='background.json')
            self.assertEqual(mask.call_args.args[:2],('background.json',str(root/'edited.png')))
            self.assertEqual(records[0]['before_background_removal'],str((root/'edited.png').resolve()))
            self.assertEqual(result['background_profile'],str(Path('background.json').resolve()))

    def test_configure_supports_server_combo_schema_and_keeps_original_coordinates(self):
        with tempfile.TemporaryDirectory() as folder:
            for field in ([['birefnet.safetensors']],['COMBO',{'options':['birefnet.safetensors']}]):
                info={'LoadBackgroundRemovalModel':{'input':{'required':{'bg_removal_name':field}}}}
                with patch('generate.request',return_value=info):
                    profile=bg.configure(Path(folder)/'profile.json')
                graph=profile['workflow']
                self.assertEqual(graph['24']['inputs']['expand'],-1)
                self.assertEqual(graph['42']['class_type'],'MaskToImage')
                self.assertFalse(any('Crop' in n['class_type'] for n in graph.values()))

    def test_background_only_rejects_changed_pixels_size_and_missing_alpha(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=Image.new('RGB',(8,8),(30,60,90));source.save(root/'source.png')
            (root/'profile.json').write_text('{}')
            good=source.convert('RGBA');good.putpixel((0,0),(30,60,90,0))
            changed=good.copy();changed.putpixel((1,1),(99,60,90,255))
            for image,error in ((changed,'RGB'),(good.resize((4,4)),'dimensions'),(source,'alpha'),(source.convert('RGBA'),'opaque')):
                image.save(root/'output.png')
                with patch.object(bg,'process',return_value={'file':str(root/'output.png')}):
                    with self.assertRaisesRegex(ValueError,error):
                        bg.remove_background(root/'profile.json',root/'source.png',root/'job')
            good.save(root/'output.png')
            with patch.object(bg,'process',return_value={'file':str(root/'output.png')}) as run:
                bg.remove_background(root/'profile.json',root/'source.png',root/'job')
                self.assertIsNone(run.call_args.args[2])


if __name__=='__main__':unittest.main()
