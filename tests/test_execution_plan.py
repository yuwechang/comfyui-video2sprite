import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image, ImageDraw
import sys
sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
import execution_plan as execution
import finish_animation
from plan_templates import ref, create


class ExecutionTests(unittest.TestCase):
    def test_explicit_research_indices_can_use_source_timing_without_reselection(self):
        from workflow_ops import selection
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root)
            result=selection(root/'source.mkv',root/'preview-selection',.2,'return_to_start',
                             indices=[0,2,3],source_timing=True)
            self.assertEqual(result['sample_indices'],[0,2,3])
            self.assertEqual(sum(result['frame_durations_ms']),200)
            self.assertEqual(result['sampling']['timing_assignment']['method'],'source_timestamp_midpoints')

    def test_diagnostic_selection_preview_does_not_approve_or_advance(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);paths=[]
            for i in range(2):
                path=root/f'{i}.png';Image.new('RGB',(24,24),(i*200,30,50)).save(path)
                paths.append(str(path))
            result={'selected_frames':paths,'frame_durations_ms':[60,100]}
            plan=execution.Plan.__new__(execution.Plan)
            plan.workspace=root
            plan.state={'tasks':{'task':{'steps':{'selection':{'status':'review_failed',
                'result':result,'result_fingerprint':'unchanged'}}}}}
            plan.fingerprint=lambda value:'unchanged'
            before=copy.deepcopy(plan.state)
            preview=execution.Plan.preview_selection.__wrapped__(plan,'task','selection',root/'diagnostic.gif')
            self.assertEqual(plan.state,before)
            self.assertTrue(preview['diagnostic_only'])
            with Image.open(preview['preview']) as gif:
                self.assertEqual(gif.info['loop'],0)
                self.assertEqual(gif.n_frames,2)
                self.assertEqual(gif.info['duration'],60)
                gif.seek(1);self.assertEqual(gif.info['duration'],100)

    def test_explicit_selection_does_not_require_unused_analysis_profile(self):
        from material_contract import requirements
        from types import SimpleNamespace
        plan=SimpleNamespace(config={'tasks':[{'id':'task','steps':[{
            'id':'selection','operation':'selection','args':{'foreground':{'profile':'unused.json'}}}]}]},
            state={'tasks':{'task':{'steps':{'selection':{'status':'completed',
                'result':{'sampling':{'strategy':'explicit'}}}}}}},resolve=lambda value:value)
        self.assertEqual(requirements(plan,'task',{},{}),{})
        plan.state['tasks']['task']['steps']['selection']['result']['sampling']['strategy']='local_novelty'
        with self.assertRaisesRegex(ValueError,'foreground/profile'):
            requirements(plan,'task',{}, {})

    def test_explicit_shared_json_material_is_registered(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'workflow.json'
            source.write_text('{}')
            plan=execution.Plan.__new__(execution.Plan)
            plan.state={'tasks':{'task':{'assets':{}}}}
            plan.collect('task','common',{'imported/declared/workflow.json':str(source)})
            assets=plan.state['tasks']['task']['assets']
            self.assertEqual([item['path'] for item in assets.values()],[str(source.resolve())])

    def test_switch_video_profile_preserves_existing_tasks(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan=self.fixture(root)
            tasks=copy.deepcopy(plan.config['tasks'])
            profile=root/'new-video.json'
            profile.write_text(json.dumps({'kind':'video','bindings':{'image_1':[]},'generation':{'fps':24}}))
            with patch.object(sys,'argv',['execution_plan.py','--plan',str(plan.path),'set-video-profile','--file',str(profile)]), \
                    patch('builtins.print'):
                execution.main()
            updated=json.loads(plan.path.read_text(encoding='utf-8'))
            self.assertEqual(updated['tasks'],tasks)
            self.assertEqual(updated['video_profile'],str(profile.resolve()))

    def fixture(self, root, count=1):
        for i in range(4):
            image = Image.new('RGB',(32,32),(128,128,128))
            draw = ImageDraw.Draw(image)
            draw.rectangle((10+i,8,16+i,28),fill=(220,30,20))
            draw.rectangle((23,4,26,8),fill=(40,90,240))
            image.save(root/f'{i}.png')
        subprocess.run(['ffmpeg','-v','error','-framerate','20','-i',str(root/'%d.png'),
                        '-c:v','ffv1',str(root/'source.mkv')],check=True)
        (root/'profile.json').write_text('{}')
        (root/'prompt.txt').write_text('Refine and remove background')
        tasks = []
        for i in range(count):
            task = 'animation-'+str(i)
            tasks.append({'id':task,'effect_type':'none','depends_on':[] if i==0 else ['animation-'+str(i-1)],
                'steps':[
                  {'id':'select','operation':'selection','args':{
                    'video':str(root/'source.mkv'),'output':str(root/task/'selection'),
                    'seconds':.2,'motion_type':'return_to_start','start':0,'end':3,'count':2}},
                  {'id':'finish','operation':'finish','args':{
                    'selection_file':ref(task,'select','selection_file'),
                    'image_profile':str(root/'profile.json'),'prompt_file':str(root/'prompt.txt'),
                    'job':str(root/task/'finish'),'output':str(root/task/'out'),
                    'effects_present':ref(task,'select','review.values.effects_present')}},
                  {'id':'pack','operation':'package','args':{
                    'summary':ref(task,'finish','result_file'),'video':str(root/'source.mkv'),
                    'output':str(root/task/'delivery')}}]})
        # Reverse input order to verify dependency ordering rather than input-list luck.
        config = {'workspace':str(root),'assets':{'reference':str(root/'0.png')},'tasks':list(reversed(tasks))}
        path = root/'plan.json';path.write_text(json.dumps(config))
        return execution.Plan(path)

    def processor(self, calls):
        def process(profile, image, prompt, job):
            target = Path(job)/'result.png'
            if not target.exists():
                target.parent.mkdir(parents=True,exist_ok=True)
                with Image.open(image) as raw:
                    result = raw.convert('RGBA')
                    pixels = result.get_flattened_data() if hasattr(result,'get_flattened_data') else result.getdata()
                    alpha = bytes(0 if p[:3]==(128,128,128) else 255 for p in pixels)
                    result.putalpha(Image.frombytes('L',result.size,alpha))
                    if 'repair' in prompt:
                        ImageDraw.Draw(result).rectangle((1,1,3,3),fill=(230,20,20,255))
                    result.save(target)
                calls.append(str(target))
            return {'file':str(target)}
        return process

    def decision(self, plan, request, root, fail=False):
        record = plan.state['tasks'][request['task']]['steps'][request['stage']]
        data = json.loads(Path(request['request']).read_text())
        evidence = data['diagnostic']['pictures'][0]
        decision = {'items':{name:{'status':'fail' if fail else 'pass',
                         'reason':'Controlled fixture has the expected complete content and geometry.',
                         'evidence':evidence} for name in data['required_items']},
                    'values':{'effects_present':False}}
        observations=[{'path':x['path'],'method':'continuous_playback','full_clip_observed':True,
            'replay_boundary_observed':True,
            'elapsed_visible_ms':x['clip_duration_ms'],'clip_duration_ms':x['clip_duration_ms'],
            'sha256':execution.file_digest(x['path']),
            'reason':'Controlled test observation, not a production visual claim.'}
            for x in data['diagnostic'].get('playback',[])]
        if observations:
            observed=root/(request['task']+'-'+request['stage']+'-test-playback.json')
            observed.write_text(json.dumps({'status':'complete','observations':observations}))
            decision['playback_record']=str(observed)
        if fail:
            decision['failed_frames'] = {'clean':[0]}
        path = root/'decision.json';path.write_text(json.dumps(decision))
        return plan.review(request['task'],request['stage'],path)

    def test_one_and_many_share_loop_resume_and_register_assets(self):
        for count in (1,2):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as folder:
                root = Path(folder);plan = self.fixture(root,count);calls=[]
                with patch.object(finish_animation,'process',side_effect=self.processor(calls)):
                    for _ in range(count*3+1):
                        result = plan.run()
                        if result['status']=='completed':break
                        for request in result['requests']:
                            self.decision(plan,request,root)
                    self.assertEqual(result['status'],'completed')
                    self.assertEqual(len(calls),count*2)  # clean branch, never a duplicate effect branch
                    self.assertEqual(plan.run()['status'],'completed')
                    self.assertEqual(len(calls),count*2)
                    display=plan.display(root/'chat-display')
                    self.assertTrue(Path(display['chat']).is_file())
                    self.assertEqual(len(plan.state['display']['previews']),count)
                for i in range(count):
                    task = 'animation-'+str(i)
                    state = plan.state['tasks'][task]
                    self.assertTrue(any('prompt_file' in key for key in state['assets']))
                    archive_path = state['steps']['pack']['result']['action']['zip']
                    with zipfile.ZipFile(archive_path) as archive:
                        self.assertIn('variants/clean/animation.json',archive.namelist())
                        self.assertFalse(any('with_effects' in n for n in archive.namelist()))
                        self.assertTrue(any('materials/' in n for n in archive.namelist()))
                        if i:
                            self.assertTrue(any('materials/dependency/' in n for n in archive.namelist()))

    def test_preserve_background_template_uses_explicit_layout_without_standing_edit(self):
        import character_plan
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);Image.new('RGB',(16,16)).save(root/'character.png')
            character=character_plan.initialize(root,root/'character.png',['combat'],['walk'],512)
            config=create(character,root,'image.json','video.json',background_mode='preserve')
            self.assertEqual([s['id'] for s in config['tasks'][0]['steps']],['pose'])
            layout=config['tasks'][1]['steps'][0]['args']
            self.assertEqual(layout['image'],ref('combat-reference','pose','file'))
            self.assertNotIn('standing_reference',layout)
            self.assertIsNone(layout['subject_box'])
            self.assertIsNone(layout['ground_anchor'])
            self.assertEqual(layout['bottom_ratio'],.15)

    def test_document_reader_deduplicates_sections_and_does_not_record_truncated_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan=self.fixture(root)
            guide=root/'guide.md';guide.write_text('# Guide\nIntro\n## One\nalpha\n## Two\nbeta\n')
            first=plan.read_documents([guide],section='One')
            self.assertIn('alpha',first[0]['content']);self.assertNotIn('beta',first[0]['content'])
            self.assertEqual(plan.read_documents([guide],section='One')[0]['status'],'already_read')
            with self.assertRaisesRegex(ValueError,'budget'):
                plan.read_documents([guide],section='Two',max_chars=2)
            self.assertEqual(plan.read_documents([guide],section='Two')[0]['status'],'read')
            self.assertEqual(plan.read_documents([guide],section='One',refresh=True)[0]['status'],'read')

    def test_finish_review_accepts_existing_files_without_browser_record(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan=self.fixture(root);calls=[]
            with patch.object(finish_animation,'process',side_effect=self.processor(calls)):
                result=plan.run();self.decision(plan,result['requests'][0],root)
                request=plan.run()['requests'][0]
                data=json.loads(Path(request['request']).read_text())
                decision={'items':{name:{'status':'pass','reason':'Fixture geometry inspected.',
                    'evidence':data['diagnostic']['pictures'][0]} for name in data['required_items']}}
                path=root/'bad-review.json';path.write_text(json.dumps(decision))
                plan.review(request['task'],request['stage'],path)
                self.assertEqual(plan.state['tasks'][request['task']]['steps'][request['stage']]['status'],'completed')
                self.assertFalse((root/'animation-0/delivery/action.zip').exists())

    def test_failed_review_repair_only_target_frames_and_then_package(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan=self.fixture(root);calls=[]
            with patch.object(finish_animation,'process',side_effect=self.processor(calls)):
                result=plan.run();self.decision(plan,result['requests'][0],root)
                result=plan.run();self.decision(plan,result['requests'][0],root,fail=True)
                self.assertFalse((root/'animation-0/delivery/action.zip').exists())
                (root/'repair.txt').write_text('repair the controlled defect')
                (root/'repair.json').write_text(json.dumps({'clean':{'0':{'prompt_file':'repair.txt'}}}))
                with patch('process_image.process',side_effect=self.processor(calls)):
                    request=plan.repair('animation-0','finish',root/'repair.json','fix-1')
                self.assertEqual(len(calls),3)
                self.decision(plan,dict(request,task='animation-0',stage='finish'),root)
                self.assertEqual(plan.run()['status'],'completed')
                self.assertEqual(len(calls),3)
            with zipfile.ZipFile(root/'animation-0/delivery/action.zip') as archive:
                self.assertIn('variants/clean/corrections/000-prompt.txt',archive.namelist())

    def test_no_automatic_visual_pass_and_no_skipping_required_items(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan=self.fixture(root);result=plan.run()
            self.assertEqual(plan.state['tasks']['animation-0']['steps']['select']['status'],'needs_review')
            path=root/'bad.json';path.write_text(json.dumps({'items':{}}))
            with self.assertRaisesRegex(ValueError,'every required'):
                plan.review('animation-0','select',path)
            self.assertFalse((root/'animation-0/finish').exists())

    def test_hold_selection_cannot_pass_without_x_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan=self.fixture(root);config=json.loads(plan.path.read_text())
            config['tasks'][0]['steps'][0]['args']['motion_type']='hold_end_pose'
            plan.path.write_text(json.dumps(config));plan=execution.Plan(plan.path)
            result=plan.run()
            with self.assertRaisesRegex(ValueError,'explicit lead_start'):
                self.decision(plan,result['requests'][0],root)
            self.assertFalse((root/'animation-0/finish').exists())

    def test_unknown_operation_rejects_invalid_plan_before_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan=self.fixture(root)
            config=json.loads(plan.path.read_text());config['tasks'][0]['steps'][0]['operation']='custom-python'
            plan.path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError,'Invalid plan operation'):
                execution.Plan(plan.path)
            self.assertFalse((root/'animation-0/selection').exists())

    def test_document_registry_reports_changes_and_dependency_cycles_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan=self.fixture(root);doc=root/'guide.md';doc.write_text('a')
            self.assertEqual(plan.documents([doc])[0]['status'],'new_or_changed')
            plan.state['documents'][str(doc.resolve())]=execution.file_digest(doc);plan.persist()
            self.assertEqual(plan.documents([doc])[0]['status'],'already_recorded')
            doc.write_text('b');self.assertEqual(plan.documents([doc])[0]['status'],'new_or_changed')
            config=json.loads(plan.path.read_text());config['tasks'][0]['depends_on']=['animation-0']
            plan.path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError,'cycle'):execution.Plan(plan.path)

    def test_plan_template_uses_data_references_not_workspace_programs(self):
        import character_plan
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);Image.new('RGB',(16,16)).save(root/'character.png')
            character=character_plan.initialize(root,root/'character.png',['normal','combat'],['walk','jump'])
            config=create(character,root,'image.json','video.json')
            path=root/'flow.json';path.write_text(json.dumps(config));plan=execution.Plan(path)
            self.assertEqual(len(plan.config['tasks']),len(character['tasks'])+4)
            self.assertFalse(any(t.get('is_idle') for t in config['tasks']))
            walk = next(t for t in config['tasks'] if t['id']=='combat-walk')
            self.assertEqual(walk['depends_on'], ['combat-layout'])
            self.assertEqual(walk['steps'][0]['args']['image'], ref('combat-layout','layout','prepared'))
            self.assertEqual(sum(s['operation']=='package' for s in walk['steps']), 1)
            self.assertTrue(any(s['operation']=='jump_finish' for t in config['tasks'] for s in t['steps']))
            self.assertFalse(any(p.suffix=='.py' for p in root.rglob('*')))

    def test_clean_jump_processes_union_once_and_packages_both_phases(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan=self.fixture(root);config=json.loads(plan.path.read_text())
            task=config['tasks'][0]
            task['steps'][0]['operation']='jump_selection'
            task['steps'][0]['args']={'video':str(root/'source.mkv'),'output':str(root/'selected'),
                'rise_start':0,'apex':1,'fall_end':3,'roi':[17,0,31,14],
                'rise_count':2,'fall_count':2,'rise_seconds':.1,'fall_seconds':.1}
            task['steps'][1]['operation']='jump_finish'
            plan.path.write_text(json.dumps(config));plan=execution.Plan(plan.path);calls=[]
            with patch.object(finish_animation,'process',side_effect=self.processor(calls)):
                for _ in range(4):
                    result=plan.run()
                    if result['status']=='completed':break
                    for request in result['requests']:
                        self.assertIn('request',request,result)
                        self.decision(plan,request,root)
            self.assertEqual(result['status'],'completed')
            self.assertEqual(len(calls),3)
            report=plan.state['tasks']['animation-0']['steps']['finish']['result']
            self.assertTrue(Path(report['reference_image']).is_file())
            a=report['rise']['variants']['clean'];b=report['fall']['variants']['clean']
            with Image.open(a['final_frames'][-1]) as first,Image.open(b['final_frames'][0]) as last:
                self.assertEqual(first.tobytes(),last.tobytes())
            for phase in ('rise','fall'):
                with zipfile.ZipFile(root/'animation-0/delivery'/(phase+'.zip')) as archive:
                    self.assertIn('variants/clean/animation.json',archive.namelist())
                    self.assertIn('alignment/airborne-reference.json',archive.namelist())

    def test_native_character_plan_synced_only_after_reviews_and_package(self):
        import character_plan
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan=self.fixture(root)
            native=character_plan.initialize(root,root/'0.png',['normal'],['idle'])
            native['tasks'][0]['id']='animation-0'
            native_path=root/'work/character/plan.json';native_path.write_text(json.dumps(native))
            config=json.loads(plan.path.read_text());config['character_plan']=str(native_path)
            task=config['tasks'][0];task.update(character_task='animation-0',stance='normal',pipeline='standard')
            task['steps'][-1]['id']='package'
            task['steps'].insert(0,{'id':'video','operation':'video','args':{
                'profile':'unused','image':str(root/'0.png'),'prompt_file':str(root/'prompt.txt'),'job':'unused',
                'width':32,'height':32,'seconds':.2,'seed':11}})
            plan.path.write_text(json.dumps(config));plan=execution.Plan(plan.path);calls=[]
            with patch.dict(execution.OPERATIONS,video=lambda **kw:{'videos':[{'path':str(root/'source.mkv')}]}), \
                 patch.object(finish_animation,'process',side_effect=self.processor(calls)):
                result=plan.run()
                self.assertNotEqual(json.loads(native_path.read_text())['tasks'][0]['status'],'completed')
                self.decision(plan,result['requests'][0],root)
                result=plan.run();self.decision(plan,result['requests'][0],root)
                self.assertEqual(plan.run()['status'],'completed')
            saved=json.loads(native_path.read_text())
            self.assertEqual(saved['tasks'][0]['status'],'completed')
            for path in saved['tasks'][0]['artifacts'].values():self.assertTrue(Path(path).is_file())

    def test_changed_recorded_input_stops_instead_of_resubmitting(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan=self.fixture(root);calls=[]
            with patch.object(finish_animation,'process',side_effect=self.processor(calls)):
                for _ in range(4):
                    result=plan.run()
                    if result['status']=='completed':break
                    for request in result['requests']:
                        self.assertIn('request',request,result)
                        self.decision(plan,request,root)
                (root/'prompt.txt').write_text('changed prompt')
                result=plan.run()
                self.assertEqual(result['status'],'needs_attention')
                self.assertIn('inputs changed',result['requests'][0]['reason'])
                self.assertEqual(len(calls),2)


if __name__=='__main__':
    unittest.main()
