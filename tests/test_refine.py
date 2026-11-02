import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import finish_animation as pipeline
import process_image


class RefineTests(unittest.TestCase):
    def frames(self):
        frames = []
        for box in [(10, 5, 14, 17), (13, 3, 19, 16)]:
            frame = Image.new('RGBA', (32, 24))
            ImageDraw.Draw(frame).rectangle(box, fill=(240, 30, 20, 255))
            frames.append(frame)
        return frames

    def test_second_common_crop_preserves_motion_and_faint_alpha(self):
        frames = self.frames()
        frames[0].putpixel((9, 6), (255, 0, 0, 16))
        result, report = pipeline.crop_refined(frames)
        self.assertEqual(report['crop_box'], [9, 3, 23, 18])
        self.assertEqual(result[0].size, (14, 16))
        for source, frame in zip(frames, result):
            self.assertEqual(frame.crop((0,0,14,15)).tobytes(), source.crop((9,3,23,18)).tobytes())
            self.assertEqual(frame.getpixel((0,15))[3], 0)
        capped, _ = pipeline.crop_refined(frames, 8)
        self.assertLessEqual(max(capped[0].size), 8)

    def test_alpha_cleanup_preserves_gradients_rgb_and_source(self):
        source = Image.new('RGBA', (10, 1))
        values = [0, 1, 7, 8, 15, 16, 64, 128, 254, 255]
        for x, alpha in enumerate(values):
            source.putpixel((x, 0), (30, 70, 110, alpha))
        original = source.tobytes()
        cleaned = pipeline.clean_alpha(source, 8)
        self.assertEqual(list(cleaned.getchannel('A').tobytes()), [0, 0, 0, 8, 15, 16, 64, 128, 254, 255])
        self.assertEqual(cleaned.convert('RGB').tobytes(), source.convert('RGB').tobytes())
        self.assertEqual(source.tobytes(), original)
        self.assertEqual(pipeline.clean_alpha(source, 0).tobytes(), original)

    def test_low_alpha_background_no_longer_expands_common_crop(self):
        frames = self.frames()
        for frame in frames:
            frame.putpixel((0, 0), (255, 255, 255, 7))
        cells, report = pipeline.crop_refined(frames)
        self.assertEqual(report['crop_box'], [10, 3, 22, 18])
        self.assertEqual(report['alpha_cutoff'], 8)
        for cell in cells:
            self.assertFalse(any(cell.getchannel('A').histogram()[1:8]))
        _, disabled = pipeline.crop_refined(frames, alpha_cutoff=0)
        self.assertEqual(disabled['crop_box'][0], 0)
        scaled, _ = pipeline.crop_refined(frames, max_side=8)
        self.assertFalse(any(scaled[0].getchannel('A').histogram()[1:8]))

    def test_alpha_cutoff_rejects_invalid_values_and_empty_cleaned_frame(self):
        for value in [-1, 256, 8.5, True]:
            with self.assertRaisesRegex(ValueError, 'Alpha cutoff'):
                pipeline.crop_refined(self.frames(), alpha_cutoff=value)
        with self.assertRaisesRegex(ValueError, 'empty'):
            pipeline.crop_refined([Image.new('RGBA', (8, 8), (20, 30, 40, 7))])

    def test_per_frame_alignment_validation_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'prompt.txt').write_text('Remove unwanted effects, restore blurred details and output transparent PNG.', encoding='utf-8')
            (root/'profile.json').write_text(json.dumps({'input_alignment': {'width':32,'height':32}}))
            inputs=[]
            for i, frame in enumerate(self.frames()):
                path=root/f'{i}.png'
                frame.convert('RGB').save(path)
                inputs.append(str(path))
            report={'cropped_frames':inputs,'frames':2,'cell_width':32,'cell_height':24,
                    'sample_indices':[4,9], 'frame_backgrounds':[[0,0,0]]*2,
                    'crop_box':[0,0,32,24],'source_size':[32,24],
                    'source_content_boxes':[[10,5,15,18],[13,3,20,17]],
                    'bottom_padding':1,'requested_seconds':.2}
            calls=[]
            fail=[True]
            def execute(profile, image, prompt, job):
                calls.append(job)
                with Image.open(image) as padded:
                    self.assertEqual(padded.size,(32,32))
                # Simulate process_image's existing per-job cache.
                target=job/'result.png'
                if target.exists():return {'file':str(target)}
                if len(calls)==2 and fail[0]:
                    fail[0]=False
                    raise RuntimeError('interrupted')
                index=int(job.parent.name)
                frame=Image.new('RGBA',(32,32))
                frame.paste(self.frames()[index],(0,0))
                job.mkdir(parents=True,exist_ok=True)
                frame.save(target)
                return {'file':str(target)}
            with patch.object(pipeline,'prepare',side_effect=lambda *a:dict(report)), patch.object(pipeline,'process',side_effect=execute):
                args=('source.mp4',None,root/'profile.json',root/'prompt.txt',root/'job',root/'out',2,4,9,.2,False)
                with self.assertRaisesRegex(RuntimeError,'interrupted'):pipeline.finish_action(*args)
                result=pipeline.finish_action(*args)
            self.assertNotEqual(calls[0],calls[1])
            self.assertEqual(calls[0],calls[2])
            self.assertEqual(result['refined_crop']['crop_box'],[10,3,22,18])
            self.assertEqual(result['sample_indices'],[4,9])
            self.assertEqual(result['verified']['gif_duration_ms'],200)
            with Image.open(result['sheet']) as sheet:
                self.assertEqual(sheet.size,(24,16))
            for record in result['refinement']:
                self.assertEqual(record['padding'],[0,8])
                self.assertTrue(Path(record['refined']).exists())

    def test_reject_empty_and_mismatched_results(self):
        with self.assertRaisesRegex(ValueError,'empty'):
            pipeline.crop_refined([Image.new('RGBA',(8,8))])
        with self.assertRaisesRegex(ValueError,'matching'):
            pipeline.crop_refined([Image.new('RGBA',(8,8)),Image.new('RGBA',(9,8))])

    def test_pipeline_rejects_resized_opaque_and_empty_outputs(self):
        for mode, size, colour, message in [
                ('RGBA', (33, 24), (0, 0, 0, 0), 'dimensions'),
                ('RGB', (32, 24), (0, 0, 0), 'alpha channel'),
                ('RGBA', (32, 24), (0, 0, 0, 255), 'transparent'),
                ('RGBA', (32, 24), (0, 0, 0, 0), 'visible content')]:
            with self.subTest(mode=mode, size=size, colour=colour), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.frames()[0].save(root/'input.png')
                Image.new(mode, size, colour).save(root/'result.png')
                (root/'prompt.txt').write_text('refine')
                (root/'profile.json').write_text('{}')
                report = {'cropped_frames': [str(root/'input.png')],
                          'frame_backgrounds': [[0, 0, 0]]}
                with patch.object(pipeline, 'prepare', return_value=report), \
                     patch.object(pipeline, 'process', return_value={'file': str(root/'result.png')}):
                    with self.assertRaisesRegex(ValueError, message):
                        pipeline.finish_action('video', None, root/'profile.json', root/'prompt.txt',
                                               root/'job', root/'out', 2, 0, 1, .2, False)

    def test_process_cache_rejects_changed_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'profile.json').write_text('{}')
            Image.new('RGB',(8,8)).save(root/'input.png')
            (root/'job').mkdir()
            (root/'job'/'job.json').write_text(json.dumps({'fingerprint':'different','prompt_id':'existing'}))
            with patch.object(process_image.g,'request') as request:
                with self.assertRaisesRegex(ValueError,'inputs changed'):
                    process_image.process(root/'profile.json',root/'input.png','refine',root/'job')
                request.assert_not_called()

if __name__=='__main__':unittest.main()
