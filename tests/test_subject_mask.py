import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import tempfile,json
from PIL import Image

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from subject_mask import SubjectMask,WorkflowMask


class SubjectMaskTests(unittest.TestCase):
    def test_workflow_masks_keep_source_size_and_have_independent_resumable_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile=root/'profile.json';profile.write_text(json.dumps({'output_mode':'mask'}))
            mask=Image.new('L',(8,9));mask.putpixel((4,4),255);mask.save(root/'mask.png')
            engine=WorkflowMask(profile,root/'jobs')
            with patch('process_image.process',return_value={'file':str(root/'mask.png')}) as run:
                for _ in range(2):self.assertEqual(engine.mask(Image.new('RGB',(8,9))).size,(8,9))
            self.assertNotEqual(run.call_args_list[0].args[3],run.call_args_list[1].args[3])
            self.assertIsNone(run.call_args.args[2])

    def test_cuda_request_cannot_silently_fall_back(self):
        runtime=SimpleNamespace(preload_dlls=Mock(),
                                get_available_providers=lambda:['CUDAExecutionProvider','CPUExecutionProvider'])
        session=SimpleNamespace(inner_session=SimpleNamespace(get_providers=lambda:['CPUExecutionProvider']))
        with patch.dict(sys.modules,{'onnxruntime':runtime,'rembg':SimpleNamespace(new_session=Mock(return_value=session))}):
            with self.assertRaisesRegex(RuntimeError,'silent CPU fallback'):
                SubjectMask('models',gpu_memory_mb=1024)
        runtime.preload_dlls.assert_called_once()

    def test_explicit_cpu_does_not_load_cuda(self):
        runtime=SimpleNamespace(preload_dlls=Mock(),get_available_providers=lambda:['CPUExecutionProvider'])
        factory=Mock(return_value=SimpleNamespace(inner_session=SimpleNamespace(get_providers=lambda:['CPUExecutionProvider'])))
        with patch.dict(sys.modules,{'onnxruntime':runtime,'rembg':SimpleNamespace(new_session=factory)}):
            engine=SubjectMask('models',device='cpu')
        self.assertEqual(engine.metadata['device'],'cpu')
        runtime.preload_dlls.assert_not_called()
        self.assertEqual(factory.call_args.kwargs['providers'],['CPUExecutionProvider'])

    def test_cuda_requires_explicit_memory_budget(self):
        with self.assertRaisesRegex(ValueError,'explicit positive'):
            SubjectMask('models')


if __name__=='__main__':
    unittest.main()
