import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import package_delivery as delivery


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class DeliveryTests(unittest.TestCase):
    def fixture(self, root):
        source = root / 'source'
        source.mkdir()
        for i in range(4):
            Image.new('RGB', (24,32), (i*50,20,30)).save(source/f'{i:03d}.png')
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-framerate','4',
                        '-i',str(source/'%03d.png'),'-c:v','ffv1',str(root/'video.mkv')],check=True)
        Image.new('RGBA',(48,32),(255,0,0,128)).save(root/'sheet.png')
        Image.new('RGB',(24,32),'red').save(root/'preview.gif')
        (root/'提示詞.txt').write_text('保留角色，輸出透明背景。',encoding='utf-8')
        (root/'animation.json').write_text(json.dumps({'frames':2,'sample_indices':[0,2],
            'sheet':'sheet.png','preview':'preview.gif','input_sheet':'/temporary/input.png',
            'frame_scale':.5}),encoding='utf-8')
        config={'video':'video.mkv','animation':'animation.json',
                'files':{'input/reference.png':'source/000.png',
                         'prompts/去背.txt':'提示詞.txt'}}
        (root/'package.json').write_text(json.dumps(config),encoding='utf-8')
        return config

    def test_real_archive_frames_assets_and_portable_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.fixture(root)
            result=delivery.package(root/'package.json',root/'bundle.zip')
            self.assertEqual((result['all_frames'],result['selected_frames']),(4,2))
            with zipfile.ZipFile(result['zip']) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read('frames/all/frame_000002.png'),
                                 archive.read('frames/selected/001_frame_000002.png'))
                self.assertEqual(archive.read('video/source.mkv'),(root/'video.mkv').read_bytes())
                self.assertEqual(archive.read('prompts/去背.txt'),(root/'提示詞.txt').read_bytes())
                report=json.loads(archive.read('result/animation.json'))
                self.assertEqual(report['sheet'],'spritesheet.png')
                self.assertNotIn('input_sheet',report)
                inventory=json.loads(archive.read('manifest.json'))
                self.assertEqual(inventory['selected_frames'][1]['source_frame_index'],2)
                self.assertNotIn('keyframes/tail.png',archive.namelist())
            self.assertTrue((root/'source/002.png').exists())
            self.assertFalse(list(root.glob('delivery-*')))

    def test_missing_input_fails_before_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            config=self.fixture(root)
            config['files']['keyframes/first.png']='missing.png'
            (root/'package.json').write_text(json.dumps(config))
            with patch.object(delivery.subprocess,'run') as export:
                with self.assertRaisesRegex(ValueError,'Missing asset'):
                    delivery.package(root/'package.json',root/'bundle.zip')
                export.assert_not_called()
            self.assertFalse((root/'bundle.zip').exists())

    def test_out_of_range_selection_leaves_no_partial_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.fixture(root)
            report=json.loads((root/'animation.json').read_text())
            report['sample_indices']=[0,7]
            (root/'animation.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'every selected frame'):
                delivery.package(root/'package.json',root/'bundle.zip')
            self.assertFalse((root/'bundle.zip').exists())
            self.assertFalse(list(root.glob('delivery-*')))

    def test_path_and_collision_validation(self):
        for name in ('../escape.txt','/absolute.txt','C:/drive.txt','bad\\path.txt'):
            with self.assertRaises(ValueError):
                delivery.archive_name(name)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            config=self.fixture(root)
            config['files']['RESULT/PREVIEW.GIF']='preview.gif'
            (root/'package.json').write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError,'case-insensitive'):
                delivery.package(root/'package.json',root/'bundle.zip')


if __name__ == '__main__':
    unittest.main()
