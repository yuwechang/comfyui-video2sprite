import importlib.util
from pathlib import Path
import unittest
import argparse
import json
import tempfile
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

spec = importlib.util.spec_from_file_location('generate', Path(__file__).parents[1] / 'scripts/generate.py')
generate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate)


class GenerateTests(unittest.TestCase):
    def test_third_reference_change_invalidates_existing_job(self):
        from job_contract import file_digest
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('profile','image','image2','image3','prompt'):(root/name).write_text(name)
            args=argparse.Namespace(job=root,profile=root/'profile',image=root/'image',image2=root/'image2',
                extra_images=[root/'image3'],prompt_file=root/'prompt',width=768,height=768,seconds=5,seed=42,timeout=1)
            contract=dict(profile=file_digest(args.profile),image=file_digest(args.image),image2=file_digest(args.image2),
                extra_images=[file_digest(root/'image3')],prompt=file_digest(args.prompt_file),
                width=768,height=768,seconds=5,seed=42)
            (root/'job.json').write_text(json.dumps({'status':'complete','input_contract':contract,'videos':[]}))
            (root/'image3').write_text('changed')
            with self.assertRaisesRegex(ValueError,'inputs changed'):generate.run(args)

    def test_resume_rejects_changed_inputs_and_missing_video_never_returns_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('profile', 'image', 'prompt'):
                (root/name).write_text(name)
            args = argparse.Namespace(job=root, profile=root/'profile', image=root/'image',
                    image2=None, prompt_file=root/'prompt', width=768, height=768,
                    seconds=2.4, seed=42, timeout=1)
            # Existing completion cannot conceal changed inputs.
            (root/'job.json').write_text(json.dumps({'status':'complete', 'input_contract':{},
                                                   'videos':[{'path':str(root/'missing.mp4')}]}))
            with self.assertRaisesRegex(ValueError, 'inputs changed'):
                generate.run(args)
            # Job-only resume may recover missing outputs from its existing prompt ID.
            args.image = args.prompt_file = None
            state = {'status':'complete', 'url':'http://localhost', 'prompt_id':'existing',
                     'output_node':'1', 'videos':[{'path':str(root/'missing.mp4')}]}
            (root/'job.json').write_text(json.dumps(state))
            with patch.object(generate, 'wait_for_result', return_value={}) as wait, \
                 patch.object(generate, 'download', return_value=[{'path':'recovered.mp4'}]) as download, \
                 patch.object(generate, 'request') as submit:
                result = generate.run(args)
            self.assertEqual(result['videos'][0]['path'], 'recovered.mp4')
            wait.assert_called_once()
            download.assert_called_once()
            submit.assert_not_called()

    def test_alignment(self):
        rules = {'fps': 24, 'frame_min': 5, 'frame_step': 17, 'frame_offset': 5, 'frame_max': 3600}
        self.assertEqual(generate.align_frames(2.4, rules), 73)
        for seconds in (.01, .2, 1, 2.4, 15):
            count = generate.align_frames(seconds, rules)
            self.assertGreaterEqual(count, seconds * 24)
            self.assertEqual((count - 5) % 17, 0)

    def test_omit_and_prune_without_changing_source(self):
        graph = {'1': {'inputs': {'image': 'a'}}, '2': {'inputs': {'image': 'b'}},
                 '3': {'inputs': {'first': ['1', 0], 'last': ['2', 0], 'width': ['4', 0]}},
                 '4': {'inputs': {'value': 100}}, '5': {'inputs': {}}}
        profile = {'workflow': graph, 'output_node': '3',
                   'bindings': {'width': [{'node': '3', 'input': 'width', 'mode': 'replace_link'}]},
                   'image_2_mode': {'optional': True, 'omit_inputs': [{'node': '3', 'input': 'last'}]}}
        result = generate.build_graph(profile, {'width': 768}, True)
        self.assertEqual(set(result), {'1', '3'})
        self.assertNotIn('last', result['3']['inputs'])
        self.assertEqual(graph['3']['inputs']['width'], ['4', 0])


if __name__ == '__main__':
    unittest.main()
