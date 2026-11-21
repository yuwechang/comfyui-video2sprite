import sys
import tempfile
import unittest
import json
from unittest.mock import patch
from pathlib import Path
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from pose_reference import prepare,accept,load_manifest
from frame_sampling import AdaptiveScorer,extent_anchors
from image_features import main_component
from select_segment import locate
from execution_plan import Plan


class PoseReferenceTests(unittest.TestCase):
    def test_import_requires_review_and_propagates_recorded_materials(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);Image.new('RGBA',(16,32),'red').save(r/'source.png')
            (r/'prompt.txt').write_text('pose',encoding='utf-8')
            prepare(r/'source.png',r/'prompt.txt',r/'job');out=accept(r/'job',r/'source.png')
            config={'workspace':str(r),'tasks':[
                {'id':'reference','kind':'reference','effect_type':'none','steps':[
                    {'id':'pose','operation':'pose_reference','args':{'manifest':out['manifest']}}]},
                {'id':'action','effect_type':'none','depends_on':['reference'],'steps':[
                    {'id':'frames','operation':'frames','args':{'video':'unused','indices':[],'output':str(r/'frames')}}]}]}
            path=r/'plan.json';path.write_text(json.dumps(config))
            plan=Plan(path);plan.run()
            self.assertEqual(plan.state['tasks']['reference']['steps']['pose']['status'],'needs_review')
            self.assertEqual(plan.state['tasks']['action']['status'],'waiting_dependencies')
            decision=r/'decision.json';decision.write_text(json.dumps({'items':{
                name:{'status':'pass','reason':'synthetic fixture inspected','evidence':out['file']}
                for name in ('pose','identity','body_scale','background')}}))
            plan.review('reference','pose',decision)
            with patch.dict('execution_plan.OPERATIONS',frames=lambda video,indices,output:{'files':[]}):plan.run()
            assets=plan.state['tasks']['action']['assets']
            self.assertTrue(any(v['path'].endswith('prompt.txt') for v in assets.values()))
            self.assertTrue(any(v['path'].endswith('reference.png') for v in assets.values()))

    def test_revision_keeps_actual_inputs_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);Image.new('RGBA',(16,32),'red').save(r/'source.png')
            (r/'prompt.txt').write_text('pose',encoding='utf-8')
            prepare(r/'source.png',r/'prompt.txt',r/'first')
            first=accept(r/'first',r/'source.png')
            prepare(first['file'],r/'prompt.txt',r/'second',first['manifest'])
            second=accept(r/'second',r/'source.png')
            result=load_manifest(second['manifest'])
            self.assertEqual(len(result['lineage']),1)
            self.assertTrue(Path(result['record']['prompt_file']).is_file())
            (r/'first/prompt.txt').write_text('changed',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'changed'):load_manifest(second['manifest'])

    def test_missing_output_cannot_be_adopted(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);Image.new('RGB',(16,32)).save(r/'source.png')
            (r/'prompt.txt').write_text('pose',encoding='utf-8')
            prepare(r/'source.png',r/'prompt.txt',r/'job')
            with self.assertRaises(FileNotFoundError):accept(r/'job',r/'missing.png')
            self.assertFalse((r/'job/manifest.json').exists())

    def test_detached_effect_is_excluded_from_subject(self):
        im=Image.new('L',(48,64));d=ImageDraw.Draw(im)
        d.rectangle((8,8,20,60),fill=255);d.rectangle((35,12,46,24),fill=255)
        self.assertEqual(main_component(im).getbbox(),(8,8,21,61))

    def test_extent_is_preserved_even_under_loose_novelty_threshold(self):
        images=[]
        for right in (15,20,38,25,15):
            im=Image.new('L',(48,64));ImageDraw.Draw(im).rectangle((8,8,right,60),fill=200)
            images.append(im)
        anchors=extent_anchors(images)
        result=AdaptiveScorer(images).select(2,anchors=anchors)
        self.assertIn(2,result['indices'])
        self.assertEqual(result['indices'],[0,2,4])

    def test_independent_repetitions_do_not_form_one_crossing_segment(self):
        images=[]
        for x in (4,4,4,12,20,28,20,12,4,4,4,12,20,28,20,12,4):
            im=Image.new('L',(48,64));ImageDraw.Draw(im).rectangle((x,10,x+8,55),fill=200)
            images.append(im)
        result=locate(images,'return_to_start',stable_threshold=.01)
        self.assertEqual((result['start'],result['end']),(2,8))


if __name__=='__main__':unittest.main()
