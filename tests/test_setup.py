import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('setup_local', Path(__file__).parents[1] / 'scripts/setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def test_image_binding_without_video_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            graph = {'1': {'class_type': 'Editor', 'inputs': {'image': 'a.png', 'text': 'edit'}}}
            mapping = {'bindings': {'image_1': [{'node': '1', 'input': 'image'}],
                                    'positive_prompt': [{'node': '1', 'input': 'text'}]}, 'output_node': '1'}
            (root / 'api.json').write_text(json.dumps(graph))
            (root / 'map.json').write_text(json.dumps(mapping))
            schema = {'Editor': {'input': {'required': {'image': ['STRING'], 'text': ['STRING']}}, 'output_node': True}}
            with patch.object(setup, 'fetch', return_value=schema):
                setup.bind(root / 'api.json', root / 'map.json', 'http://localhost:8188', root / 'profile.json', 'image')
            saved = json.loads((root / 'profile.json').read_text())
            self.assertEqual(saved['kind'], 'image')
            self.assertNotIn('generation', saved)

    def test_reject_ui_workflow(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ui.json'
            path.write_text('{"nodes": []}')
            with self.assertRaises(ValueError):
                setup.read_workflow(path)

    def test_inspect_missing_class(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'api.json'
            path.write_text('{"1": {"class_type": "Missing", "inputs": {}}}')
            with patch.object(setup, 'fetch', return_value={}):
                result = setup.inspect(path, 'http://localhost:8188', Path(folder) / 'inspection.json')
            self.assertEqual(result['missing_node_classes'], ['Missing'])

    def test_save_and_reject_link_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            graph = {'1': {'class_type': 'Example', 'inputs': {'value': 1}}}
            (root / 'api.json').write_text(json.dumps(graph))
            roles = ('image_1', 'image_2', 'positive_prompt', 'width', 'height', 'length', 'seed')
            mapping = {'bindings': {r: [{'node': '1', 'input': 'value'}] for r in roles},
                       'output_node': '1', 'image_2_mode': 'optional',
                       'generation': {'width_multiple': 32, 'height_multiple': 32,
                                      'frame_step': 17, 'frame_offset': 5, 'frame_min': 22,
                                      'length_unit': 'frames', 'fps': 24}}
            (root / 'map.json').write_text(json.dumps(mapping))
            schema = {'Example': {'input': {'required': {'value': ['INT', {}]}}, 'output_node': True}}
            with patch.object(setup, 'fetch', return_value=schema):
                setup.bind(root / 'api.json', root / 'map.json', 'http://localhost:8188', root / 'profile.json')
                saved = json.loads((root / 'profile.json').read_text())
                self.assertEqual(saved['workflow'], graph)
                self.assertEqual(saved['verification'], 'bindings_checked_generation_not_tested')
                graph['1']['inputs']['value'] = ['2', 0]
                (root / 'api.json').write_text(json.dumps(graph))
                with self.assertRaisesRegex(ValueError, 'linked socket'):
                    setup.bind(root / 'api.json', root / 'map.json', 'http://localhost:8188', root / 'other.json')
                for targets in mapping['bindings'].values():
                    targets[0]['mode'] = 'replace_link'
                (root / 'map.json').write_text(json.dumps(mapping))
                setup.bind(root / 'api.json', root / 'map.json', 'http://localhost:8188', root / 'linked.json')
                self.assertEqual(json.loads((root / 'linked.json').read_text())['workflow'], graph)


if __name__ == '__main__':
    unittest.main()
