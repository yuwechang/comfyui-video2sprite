import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from camera_alignment import estimate,translate,align


def frame(camera=0,local=0):
    im=Image.new('RGB',(120,110),(130,)*3)
    draw=ImageDraw.Draw(im)
    draw.rectangle((0,75+camera,119,109),fill=(70,)*3)
    draw.rectangle((50,20+camera+local,64,40+camera+local),fill=(230,10,10))
    return im


REGIONS=[[0,55,20,98],[100,55,120,98]]


class CameraAlignmentTests(unittest.TestCase):
    def test_global_shift_removed_while_local_movement_is_preserved(self):
        images=[frame(),frame(-4,-6),frame(3,2)]
        shifts,_=estimate(images,REGIONS,max_shift=15)
        self.assertEqual(shifts,[0,4,-3])
        corrected,pad=translate(images,shifts)
        self.assertEqual(pad,[3,4])
        for image,y in zip(corrected,[23,17,25]):
            self.assertEqual(image.getpixel((50,y)),(230,10,10,255))
            self.assertEqual(image.getpixel((0,77)),(130,130,130,255))
            self.assertEqual(image.getpixel((0,78)),(70,70,70,255))

    def test_disagreement_or_missing_boundary_is_rejected(self):
        changed=frame();ImageDraw.Draw(changed).rectangle((100,75,119,80),fill=(130,)*3)
        with self.assertRaisesRegex(ValueError,'disagree'):estimate([frame(),changed],REGIONS)
        with self.assertRaisesRegex(ValueError,'weak'):estimate([Image.new('RGB',(120,110),(130,)*3)]*2,REGIONS)
        with self.assertRaisesRegex(ValueError,'separate'):estimate([frame()]*2,[REGIONS[0]]*2)

    def test_formal_output_keeps_timeline_indices_and_originals(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);paths=[]
            for i,image in enumerate([frame(),frame(-4,-6),frame(3,2)]):
                p=root/f'{i}.png';image.save(p);paths.append(str(p))
            data={'selected_frames':paths,'sample_indices':[3,8,20],
                  'frame_durations_ms':[80,140,180],'scale':.5,'seconds':.4,'motion_type':'return_to_start'}
            (root/'selection.json').write_text(json.dumps(data))
            (root/'regions.json').write_text(json.dumps({'regions':REGIONS,'validation_regions':[[25,55,40,98]]}))
            result=align(root/'selection.json',root/'regions.json',root/'out')
            for key in ('sample_indices','frame_durations_ms','scale','seconds'):
                self.assertEqual(result[key],data[key])
            self.assertEqual(result['original_selected_frames'],paths)
            self.assertEqual(result['camera_alignment']['validation'][0]['range_after'],0)
            self.assertEqual(result['camera_alignment']['reference_origin_aligned'],[0,3])
            with self.assertRaisesRegex(ValueError,'already'):
                align(result['selection_file'],root/'regions.json',root/'twice')


if __name__=='__main__':unittest.main()
