import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('generate', Path(__file__).parents[1] / 'scripts/generate.py')
generate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate)


class GenerateTests(unittest.TestCase):
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
