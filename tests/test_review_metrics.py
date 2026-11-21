import json
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from review_metrics import compare_pair,refinement_checks,geometry_check
from workflow_ops import geometry


def subject(x=12):
    image=Image.new('RGBA',(64,96))
    ImageDraw.Draw(image).rectangle((x,10,x+20,86),fill=(200,50,30,255))
    return image


def source(image):
    bg=Image.new('RGBA',image.size,(128,128,128,255));bg.alpha_composite(image)
    return bg


class ReviewMetricsTests(unittest.TestCase):
    def test_matching_and_shifted_subjects_are_distinguished(self):
        self.assertEqual(compare_pair(source(subject()),subject())['flags'],[])
        self.assertIn('position_change',compare_pair(source(subject()),subject(28))['flags'])

    def test_blank_and_resized_refine_are_flagged(self):
        self.assertIn('empty_subject',compare_pair(source(subject()),Image.new('RGBA',(64,96)))['flags'])
        self.assertIn('size_changed',compare_pair(source(subject()),subject().resize((32,48)))['flags'])

    def test_recorded_padding_is_not_mistaken_for_scale_change(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);original=source(subject())
            padded=Image.new('RGBA',(80,112),(128,128,128,255));padded.paste(original,(0,0))
            padded.save(r/'input.png');subject().save(r/'refined.png')
            report={'refinement':[{'input':str(r/'input.png'),'refined':str(r/'refined.png'),
                                   'padding':[16,16],'source_frame_index':42}]}
            result=refinement_checks(report,r/'checks')
            self.assertEqual(result['suspect_indices'],[])
            self.assertEqual(len(result['pairs']),0)
            self.assertFalse(list((r/'checks').glob('*.png')))
            self.assertEqual(result['semantic_status'],'requires_visual_review')

    def test_geometry_must_match_pixels_not_just_dimensions(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);subject().save(r/'source.png')
            args={'image':str(r/'source.png'),'job':str(r/'job'),'output':str(r/'out'),'stage':'standing'}
            report=geometry(**args)
            self.assertTrue(report['geometry_verification']['passed'])
            subject(28).save(report['standing'])
            self.assertFalse(geometry_check(args,report)['passed'])

    def test_pose_review_is_not_bypassed_by_verified_geometry(self):
        from execution_plan import Plan
        from pose_reference import prepare,accept
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);subject().save(r/'source.png');(r/'prompt.txt').write_text('pose')
            prepare(r/'source.png',r/'prompt.txt',r/'job');record=accept(r/'job',r/'source.png')
            config={'workspace':str(r),'tasks':[{'id':'reference','effect_type':'none','steps':[
                {'id':'pose','operation':'pose_reference','args':{'manifest':record['manifest']}},
                {'id':'standing','operation':'geometry','args':{
                    'image':{'from':'reference.pose','key':'file'},'stage':'standing',
                    'job':str(r/'geo-job'),'output':str(r/'out')}}]}]}
            path=r/'plan.json';path.write_text(json.dumps(config));plan=Plan(path)
            plan.run()
            self.assertEqual(plan.state['tasks']['reference']['steps']['pose']['status'],'needs_review')
            decision=r/'review.json';decision.write_text(json.dumps({'items':{
                key:{'status':'pass','reason':'synthetic pose inspected','evidence':str(r/'source.png')}
                for key in ('pose','identity','body_scale','background')}}))
            plan.review('reference','pose',decision);plan.run()
            stage=plan.state['tasks']['reference']['steps']['standing']
            self.assertEqual(stage['status'],'completed')
            self.assertTrue(Path(stage['automatic_check']).is_file())
            self.assertNotIn('review',stage['result'])


if __name__=='__main__':unittest.main()
