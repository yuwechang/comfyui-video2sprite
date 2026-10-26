"""Flag possible subject clipping against a simple video background."""
import argparse
import json
from statistics import median
import subprocess


def frame_contacts(image, tolerance=32):
    width, height = image.size
    pixels = image.load()
    edge = [pixels[x, 0] for x in range(width)] + [pixels[x, height-1] for x in range(width)]
    edge += [pixels[0, y] for y in range(height)] + [pixels[width-1, y] for y in range(height)]
    background = tuple(round(median(p[c] for p in edge)) for c in range(3))
    def foreground(p):
        return max(abs(p[c]-background[c]) for c in range(3)) > tolerance
    if sum(not foreground(p) for p in edge) / len(edge) < .6:
        return None
    lines = {'left': [pixels[0, y] for y in range(height)],
             'right': [pixels[width-1, y] for y in range(height)],
             'top': [pixels[x, 0] for x in range(width)],
             'bottom': [pixels[x, height-1] for x in range(width)]}
    return [side for side, line in lines.items() if any(
        foreground(a) and foreground(b) for a, b in zip(line, line[1:]))]


def check(video, tolerance=32):
    from PIL import Image
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                       '-show_entries', 'stream=width,height', '-of', 'json', str(video)]))['streams'][0]
    scale = min(1, 320 / max(probe['width'], probe['height']))
    width, height = max(1, round(probe['width']*scale)), max(1, round(probe['height']*scale))
    command = ['ffmpeg', '-v', 'error', '-i', str(video), '-vf',
               f'scale={width}:{height}:flags=area', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    contacts = {side: [] for side in ('left', 'right', 'top', 'bottom')}
    count = unknown = 0
    with subprocess.Popen(command, stdout=subprocess.PIPE) as process:
        while raw := process.stdout.read(width*height*3):
            if len(raw) != width*height*3:
                raise ValueError('Incomplete decoded frame')
            sides = frame_contacts(Image.frombytes('RGB', (width, height), raw), tolerance)
            if sides is None:
                unknown += 1
            else:
                for side in sides:
                    contacts[side].append(count)
            count += 1
        if process.wait() != 0:
            raise ValueError('Video decoding failed')
    if not count:
        raise ValueError('No decoded frames')
    return {'frames': count, 'unassessable_frames': unknown,
            'possible_clipping': {side: {'count': len(indices), 'first_frames': indices[:8]}
                                  for side, indices in contacts.items() if indices},
            'scan_size': [width, height]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video')
    parser.add_argument('--tolerance', type=int, default=32)
    args = parser.parse_args()
    print(json.dumps(check(args.video, args.tolerance)))
