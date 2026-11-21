import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from types import SimpleNamespace
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from task_inputs import compile_request,render,prepare_pose,missing_inputs
from execution_plan import Plan
from material_contract import requirements
from job_contract import file_digest
from review_player import receipt,validate,load_progress
from region_proposals import propose,background
import prepare_character as geometry

class InterfaceTests(unittest.TestCase):
    def config(self,root):
        return {'workspace':str(root),'assets':{},'tasks':[{'id':'action','kind':'animation',
            'effect_type':'none','pipeline':'standard','steps':[
             {'id':'selection','operation':'selection','args':{'video':'source.mp4','output':'selected','seconds':1,'motion_type':'loop'}},
             {'id':'finish','operation':'finish','args':{'selection_file':{'from':'action.selection','key':'selection_file'},
               'prompt_file':None,'output':'finished','job':'job','image_profile':'profile.json','effects_present':False}}]}]}

    def test_request_merges_only_declared_inputs_and_renders_prompts(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config=self.config(root)
            self.assertIn('prompt_file',missing_inputs(config,{})[0]['fields'])
            request={'tasks':{'action':{'selection':{'parameters':{'seconds':2}},
                'finish':{'prompts':{'prompt_file':{'template':'refine','values':{'preserve':'身份與實體配件','effects':'保留既有效果'}}}}}}}
            result=compile_request(config,{},request,root)
            self.assertEqual(missing_inputs(result,{}),[])
            self.assertEqual(result['tasks'][0]['steps'][0]['args']['seconds'],2)
            args=result['tasks'][0]['steps'][1]['args']
            self.assertEqual(args['selection_file'],config['tasks'][0]['steps'][1]['args']['selection_file'])
            self.assertIn('保留既有效果',Path(args['prompt_file']).read_text(encoding='utf-8'))
            self.assertIsNone(config['tasks'][0]['steps'][1]['args']['prompt_file'])
            many=copy.deepcopy(config);other=copy.deepcopy(many['tasks'][0]);other['id']='other';many['tasks'].append(other)
            other['steps'][1]['args']['selection_file']['from']='other.selection'
            batch=copy.deepcopy(request);batch['tasks']['other']=copy.deepcopy(batch['tasks']['action'])
            compiled=compile_request(many,{},batch,root)
            self.assertEqual([t['steps'][0]['args']['seconds'] for t in compiled['tasks']],[2,2])
            invalid=copy.deepcopy(request);invalid['tasks']['action']['missing']={}
            with self.assertRaises(ValueError):compile_request(config,{},invalid,root)
            self.assertEqual(len(list((root/'work/prompts').rglob('*.txt'))),2)
            with self.assertRaises(ValueError):render({'template':'refine','values':{'preserve':'identity'}})

    def test_enable_camera_builds_references_and_protects_started_finish(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'plan.json';path.write_text(json.dumps(self.config(root)))
            regions=root/'regions.json';regions.write_text('{"regions":[]}')
            plan=Plan(path);plan.enable_camera('action',regions)
            steps=json.loads(path.read_text())['tasks'][0]['steps']
            self.assertEqual([s['operation'] for s in steps],['selection','camera_alignment','finish'])
            self.assertEqual(steps[2]['args']['selection_file']['from'],'action.camera-alignment')
            with self.assertRaises(ValueError):plan.enable_camera('action',regions)
            fresh=root/'started.json';fresh.write_text(json.dumps(self.config(root)))
            started=Plan(fresh);started.state['tasks']={'action':{'steps':{'finish':{'status':'completed','result':{}}}}}
            started.persist()
            with self.assertRaisesRegex(ValueError,'before finish'):started.enable_camera('action',regions)
            self.assertEqual(len(json.loads(fresh.read_text())['tasks'][0]['steps']),2)

    def test_initial_pose_request_is_recorded_before_external_tool(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=root/'reference.png';Image.new('RGB',(20,30)).save(image)
            config={'tasks':[{'id':'reference','kind':'reference','steps':[{'operation':'pose_reference',
                'args':{'manifest':'work/pose/manifest.json'}}]}]}
            result=prepare_pose(config,'reference',{'reference':str(image),'prompt':{'template':'pose',
                'values':{'target':'目標支撐姿勢','preserve':'原身份與風格','background':'簡單地面'}}},root)
            self.assertEqual(result['prompt_text'],Path(result['prompt_file']).read_text(encoding='utf-8'))
            self.assertTrue((root/'work/pose/request.json').exists())
            self.assertFalse((root/'work/pose/manifest.json').exists())

    def test_background_candidates_use_multiple_selected_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);paths=[]
            for i,shift in enumerate((0,4)):
                im=Image.new('RGB',(160,120),(170,)*3);draw=ImageDraw.Draw(im)
                draw.rectangle((0,95+shift,159,119),fill=(70,)*3)
                draw.rectangle((70,20+shift,90,90+shift),fill=(220,30,30))
                path=root/str(i);path=path.with_suffix('.png');im.save(path);paths.append(str(path))
            selection=root/'selection.json';selection.write_text(json.dumps({'selected_frames':paths}))
            result=background(selection)
            self.assertEqual(result['status'],'candidate')
            self.assertEqual(result['checks']['estimated_dy'],[0,-4])
            self.assertTrue(result['requires_confirmation'])

    def test_required_roles_reject_missing_registration_and_mutated_content(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'reference.png';Image.new('RGB',(16,16)).save(source)
            fake=SimpleNamespace(config={'assets':{'reference':str(source)},'tasks':[{'id':'action','steps':[]}]},state={'tasks':{}})
            inventory={'common/reference.png':{'path':str(source),'sha256':file_digest(source)}}
            files={'materials/reference.png':str(source)}
            self.assertEqual(len(requirements(fake,'action',inventory,files)),1)
            with self.assertRaisesRegex(ValueError,'Missing registered'):requirements(fake,'action',{},files)
            Image.new('RGB',(16,16),'red').save(source)
            with self.assertRaisesRegex(ValueError,'changed'):requirements(fake,'action',inventory,files)

    def test_registered_material_manifest_connects_independent_video_backend(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'plan.json';path.write_text(json.dumps(self.config(root)))
            image=root/'reference.png';Image.new('RGB',(20,30)).save(image)
            plan=Plan(path);plan.state['tasks']={'action':{'status':'completed','steps':{},'assets':{
                'video/inputs/image.png':{'path':str(image),'sha256':file_digest(image)}}}}
            plan.persist();manifest=root/'materials.json'
            self.assertEqual(plan.export_materials(['action'],manifest)['files'],1)
            target=root/'backend.json'
            subprocess.run([sys.executable,str(Path(__file__).parents[1]/'scripts/execution_plan.py'),
                '--plan',str(target),'create-video','--video',str(root/'source.mp4'),
                '--workspace',str(root/'backend'),'--materials-file',str(manifest)],check=True,capture_output=True)
            assets=json.loads(target.read_text())['assets']
            self.assertEqual(list(assets.values()),[str(image)])
            Image.new('RGB',(20,30),'red').save(image)
            with self.assertRaisesRegex(ValueError,'changed'):plan.export_materials(['action'],root/'changed.json')

    def test_shared_geometry_keeps_pixel_scale_across_different_canvas_and_bent_pose(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            def image(name,size,box):
                im=Image.new('RGB',size,(130,)*3);ImageDraw.Draw(im).rectangle(box,fill=(230,30,30));im.save(root/name)
            image('a.png',(100,200),(30,20,70,180))
            def args(name,out,box,anchor,**kw):
                return argparse.Namespace(image=str(root/name),output=str(root/out),side=200,video_profile=None,
                    multiple_x=32,multiple_y=32,background_mode='preserve',subject_box=box,ground_anchor=anchor,**kw)
            first=geometry.prepare(args('a.png','a',[30,20,71,181],[50,181]))
            from review_metrics import geometry_check
            self.assertTrue(geometry_check({'image':str(root/'a.png')},first)['passed'])
            image('b.png',(140,240),(50,90,90,220))
            second_args=args('b.png','b',[50,90,91,221],[70,221],reference_geometry=str(root/'a/preparation.json'))
            with self.assertRaisesRegex(ValueError,'explicit'):geometry.prepare(second_args)
            second_args.source_coordinate_scale=1
            second=geometry.prepare(second_args)
            self.assertEqual(first['placement']['factor'],second['placement']['factor'])
            self.assertEqual(first['geometry'],second['geometry'])
            self.assertLess(second['placement']['placed_bbox'][3]-second['placement']['placed_bbox'][1],
                            first['placement']['placed_bbox'][3]-first['placement']['placed_bbox'][1])

    def test_geometry_proposal_reports_candidates_not_contact_certainty(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'reference.png';image=Image.new('RGBA',(100,200))
            ImageDraw.Draw(image).rectangle((30,20,70,180),fill=(230,30,30,255));image.save(path)
            result=propose(path)
            self.assertTrue(result['requires_confirmation'])
            self.assertEqual(result['subject_box'],[30,20,71,181])

    def test_playback_record_requires_full_clip_boundary_and_unchanged_asset(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'preview.gif';Image.new('RGB',(10,10)).save(path)
            entry={'path':str(path),'clip_duration_ms':200,'check_replay_boundary':True}
            observation={'full_clip_observed':True,'replay_boundary_observed':True,'reason':'Controlled test observation'}
            with self.assertRaises(ValueError):receipt(entry,observation,199)
            with self.assertRaises(ValueError):receipt(entry,{**observation,'replay_boundary_observed':False},400)
            record={'status':'complete','observations':[receipt(entry,observation,220)]}
            validate(record,[entry])
            Image.new('RGB',(10,10),'red').save(path)
            with self.assertRaisesRegex(ValueError,'changed'):validate(record,[entry])

    def test_playback_progress_resumes_only_unobserved_previews(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);entries=[]
            for name in ('first','second'):
                path=root/(name+'.gif');Image.new('RGB',(10,10)).save(path)
                entries.append({'path':str(path),'clip_duration_ms':200,'check_replay_boundary':False})
            session=root/'session';session.mkdir()
            (session/'session.json').write_text(json.dumps({'fingerprint':'same-inputs'}))
            observation={'full_clip_observed':True,'reason':'Controlled fixture observation'}
            first=receipt(entries[0],observation,220)
            (session/'observations.json').write_text(json.dumps({'status':'in_progress','observations':[first]}))
            self.assertEqual(list(load_progress(session,entries,'same-inputs')),[0])
            with self.assertRaisesRegex(ValueError,'changed'):load_progress(session,entries,'different-inputs')
            second=receipt(entries[1],observation,220)
            (session/'observations.json').write_text(json.dumps({'status':'complete','observations':[first,second]}))
            self.assertEqual(list(load_progress(session,entries,'same-inputs')),[0,1])
