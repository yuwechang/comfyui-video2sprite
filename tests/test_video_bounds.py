import sys
from pathlib import Path
import unittest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from check_video_bounds import frame_contacts


class BoundsTests(unittest.TestCase):
    def test_interior_and_contacts(self):
        image = Image.new('RGB', (100, 80), (128,)*3)
        ImageDraw.Draw(image).rectangle((40,20,60,60), fill='red')
        self.assertEqual(frame_contacts(image), [])
        for side, box in [('left',(0,30,40,50)), ('right',(60,30,99,50)),
                          ('top',(40,0,60,20)), ('bottom',(40,60,60,79))]:
            touched = image.copy()
            ImageDraw.Draw(touched).rectangle(box, fill='red')
            self.assertEqual(frame_contacts(touched), [side])

    def test_noisy_background_is_unassessable(self):
        image = Image.new('RGB', (100, 80), 'white')
        ImageDraw.Draw(image).rectangle((0,0,49,79), fill='black')
        self.assertIsNone(frame_contacts(image))


if __name__ == '__main__':
    unittest.main()
