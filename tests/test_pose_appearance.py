import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from pose_appearance import extract,load


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'ffmpeg required')
class AppearanceTests(unittest.TestCase):
    def test_original_masked_rgb_ignores_background_and_contract_detects_changed_mask(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root);masks=folder/'masks';masks.mkdir()
            for i,color in enumerate(('blue','green','white','black')):
                image=Image.new('RGB',(32,32),color);ImageDraw.Draw(image).rectangle((8,8,23,23),fill='red')
                image.save(folder/f'frame-{i}.png')
                mask=Image.new('L',(32,32));ImageDraw.Draw(mask).rectangle((8,8,23,23),fill=255)
                mask.save(masks/f'mask-{i:04d}.png')
            video=folder/'source.mkv'
            subprocess.run(['ffmpeg','-v','error','-framerate','4','-i',str(folder/'frame-%d.png'),
                '-c:v','ffv1','-pix_fmt','bgr0',str(video)],check=True)
            (masks/'analysis.json').write_text(json.dumps({'video':str(video),'source_indices':list(range(4))}))
            appearance,contract=extract(video,masks,0,3,folder/'appearance.npz')
            np.testing.assert_array_equal(appearance[0],appearance[1])
            np.testing.assert_array_equal(load(contract,video,0,3),appearance)
            Image.new('L',(32,32)).save(masks/'mask-0001.png')
            with self.assertRaisesRegex(ValueError,'evidence changed'):load(contract,video,0,3)


if __name__=='__main__':unittest.main()
