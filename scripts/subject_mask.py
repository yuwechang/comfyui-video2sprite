"""Create analysis-only subject masks locally, with an explicit execution device."""
import argparse
import json
import os
import hashlib
import time
from pathlib import Path
from PIL import Image,ImageDraw


class WorkflowMask:
    """Generate analysis masks with the same built-in ComfyUI alpha profile."""
    def __init__(self,profile,job):
        config=json.loads(Path(profile).read_text(encoding='utf-8-sig'))
        if config.get('output_mode')!='mask':raise ValueError('Analysis requires a mask-output profile')
        self.profile=str(Path(profile).resolve());self.job=Path(job);self.index=0;self.source_index=None
        self.metadata={'provider':'comfyui','profile':self.profile}

    def mask(self,image):
        from process_image import process
        folder=self.job/f'{(self.index if self.source_index is None else self.source_index):04d}';folder.mkdir(parents=True,exist_ok=True)
        source=folder/'input.png';image.convert('RGB').save(source)
        result=process(self.profile,source,None,folder/'mask-job')
        with Image.open(result['file']) as output:
            if output.size!=image.size:raise ValueError('Analysis mask changed source dimensions')
            mask=output.convert('L')
        if mask.getextrema()[0]!=0 or mask.getextrema()[1]<128:
            raise ValueError('Analysis mask is opaque or empty')
        self.index+=1
        return mask


class SubjectMask:
    def __init__(self, model_dir, device='cuda', model='birefnet-general',gpu_memory_mb=None):
        if device not in ('cuda', 'cpu'):
            raise ValueError('device must be cuda or cpu')
        if device=='cuda' and (type(gpu_memory_mb) is not int or gpu_memory_mb<=0):
            raise ValueError('CUDA requires explicit positive gpu_memory_mb')
        os.environ['U2NET_HOME'] = str(Path(model_dir).resolve())
        import onnxruntime as ort
        if device == 'cuda':
            ort.preload_dlls()
        provider = 'CUDAExecutionProvider' if device == 'cuda' else 'CPUExecutionProvider'
        if provider not in ort.get_available_providers():
            raise RuntimeError(f'{provider} unavailable; no automatic device fallback')
        from rembg import new_session
        options={'arena_extend_strategy':'kSameAsRequested','gpu_mem_limit':str((gpu_memory_mb or 0)*1024*1024),
                 'cudnn_conv_algo_search':'HEURISTIC','cudnn_conv_use_max_workspace':'0'}
        self.session = new_session(model, providers=[(provider,options)] if device=='cuda' else [provider])
        actual = self.session.inner_session.get_providers()
        if device == 'cuda' and 'CUDAExecutionProvider' not in actual:
            raise RuntimeError('CUDA initialization failed; refusing silent CPU fallback')
        self.metadata = {'model': model, 'device': device, 'providers': actual}
        if device=='cuda':self.metadata['cuda_options']=options
        model_path = getattr(self.session.inner_session, '_model_path', None)
        if model_path and Path(model_path).is_file():
            with Path(model_path).open('rb') as stream:
                self.metadata['model_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()

    def mask(self, image):
        from rembg import remove
        started=time.perf_counter()
        mask=remove(image.convert('RGB'), session=self.session, only_mask=True).convert('L')
        if mask.size!=image.size or mask.point(lambda v:255 if v>=128 else 0).getbbox() is None:
            raise ValueError('Model returned an empty or incorrectly sized subject mask')
        self.metadata['last_inference_seconds']=round(time.perf_counter()-started,4)
        return mask


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    parser.add_argument('--output', required=True)
    parser.add_argument('--model-dir', required=True)
    parser.add_argument('--device', choices=('cuda', 'cpu'), default='cuda')
    parser.add_argument('--model', default='birefnet-general')
    parser.add_argument('--gpu-memory-mb', type=int,help='Required CUDA arena budget; insufficient memory fails explicitly')
    args = parser.parse_args()
    engine = SubjectMask(args.model_dir, args.device, args.model,args.gpu_memory_mb)
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    with Image.open(args.image) as image:
        mask = engine.mask(image)
        mask.save(output/'mask.png')
        cutout = image.convert('RGBA'); cutout.putalpha(mask); cutout.save(output/'cutout.png')
        box=mask.point(lambda v:255 if v>=128 else 0).getbbox()
        margin=max(8,round(max(box[2]-box[0],box[3]-box[1])*.08))
        box=(max(0,box[0]-margin),max(0,box[1]-margin),
             min(image.width,box[2]+margin),min(image.height,box[3]+margin))
        before=image.convert('RGB').crop(box)
        after=Image.new('RGBA',image.size,(35,80,95,255));after.alpha_composite(cutout)
        after=after.convert('RGB').crop(box)
        factor=min(1,560/before.height)
        size=(round(before.width*factor),round(before.height*factor))
        comparison=Image.new('RGB',(size[0]*2,size[1]+28),(45,45,45))
        comparison.paste(before.resize(size),(0,28));comparison.paste(after.resize(size),(size[0],28))
        draw=ImageDraw.Draw(comparison);draw.text((8,8),'Original',fill='white')
        draw.text((size[0]+8,8),f'BiRefNet / {args.device.upper()}',fill='white')
        comparison.save(output/'comparison.png')
    result = {**engine.metadata, 'source': str(Path(args.image).resolve()),
              'mask': str((output/'mask.png').resolve()), 'cutout': str((output/'cutout.png').resolve()),
              'comparison':str((output/'comparison.png').resolve())}
    (output/'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
