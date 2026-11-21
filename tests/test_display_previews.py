import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image,ImageDraw,ImageSequence

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import display_previews
import finish_animation
from spritesheet import prepare_frames
from job_contract import file_digest
import test_execution_plan as helpers


class DisplayTests(unittest.TestCase):
    def summary(self,root,name,box):
        folder=root/name;folder.mkdir()
        im=Image.new('RGB',(64,64),(128,128,128))
        ImageDraw.Draw(im).rectangle(box,fill=(220,30,20))
        second=im.copy();ImageDraw.Draw(second).point((box[0]+2,box[1]+2),fill=(20,220,30))
        report=prepare_frames([im,second],[0,1],folder/'selection',None,.2)
        (folder/'profile.json').write_text('{}');(folder/'prompt.txt').write_text('Refine')
        helper=helpers.ExecutionTests()
        with patch.object(finish_animation,'process',side_effect=helper.processor([])):
            result=finish_animation.finish_prepared_variants(report,folder/'profile.json',
                folder/'prompt.txt',None,folder/'job',folder/'out')
        return folder/'out/variants.json',result['variants']['clean']

    def test_equal_canvas_preserves_pixels_timing_and_source_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            a,ra=self.summary(root,'standing',(24,4,32,52))
            b,rb=self.summary(root,'lying',(4,24,52,32))
            video=root/'source.mp4';video.write_bytes(b'original video bytes')
            sources=[Path(r[k]) for r in (ra,rb) for k in ('sheet','preview')]
            sources.append(video)
            hashes={p:file_digest(p) for p in sources}
            result=display_previews.render([{'id':'standing','summary':str(a),'source_video':str(video)},
                {'id':'lying','summary':str(b)}],root/'display')
            for record,report in zip(result['previews'],(ra,rb)):
                with Image.open(record['gif']) as gif,Image.open(report['preview']) as source:
                    self.assertEqual(list(gif.size),result['canvas_size'])
                    self.assertEqual(gif.info['loop'],0)
                    padded=[(f.convert('RGBA'),f.info['duration']) for f in ImageSequence.Iterator(gif)]
                    original=[(f.convert('RGBA'),f.info['duration']) for f in ImageSequence.Iterator(source)]
                    self.assertEqual(len(padded),len(original))
                    x,y=record['offset']
                    for (frame,t),(before,expected) in zip(padded,original):
                        crop=frame.crop((x,y,x+before.width,y+before.height))
                        self.assertEqual(crop.tobytes(),before.tobytes())
                        self.assertEqual(t,expected)
                        self.assertEqual(frame.getpixel((0,0))[3],0)
            self.assertEqual(hashes,{p:file_digest(p) for p in sources})
            self.assertIn('max-width:none',(root/'display/index.html').read_text())
            self.assertTrue((root/'display/chat.md').is_file())
            self.assertIn('![Original video]('+video.resolve().as_posix()+')',
                          (root/'display/chat.md').read_text())
            self.assertFalse(list((root/'display').glob('*.mp4')))

    def test_different_delivery_scales_are_not_hidden_by_padding(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a,ra=self.summary(root,'one',(24,4,32,52))
            b,rb=self.summary(root,'two',(4,24,52,32))
            data=json.loads(b.read_text());data['variants']['clean']['delivery_scale']=.5
            b.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'equal delivery_scale'):
                display_previews.render([{'id':'one','summary':str(a)},
                    {'id':'two','summary':str(b)}],root/'display')
            self.assertFalse((root/'display').exists())

    def test_effect_pair_order_and_anchor_alignment_survive_different_crops(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a,ra=self.summary(root,'wide',(4,24,52,32))
            b,rb=self.summary(root,'tall',(24,4,32,52))
            pair=root/'pair.json';pair.write_text(json.dumps({'variants':{
                'without_effects':rb,'with_effects':ra}}))
            result=display_previews.render([{'id':'paired','summary':str(pair)}],root/'display')
            first,second=result['previews']
            self.assertEqual([r['variant'] for r in result['previews']],['with_effects','without_effects'])
            for axis in (0,1):
                self.assertEqual(first['offset'][axis]+round(ra['anchor_px'][axis]),
                                 second['offset'][axis]+round(rb['anchor_px'][axis]))


if __name__=='__main__':unittest.main()
