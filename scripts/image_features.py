"""Shared image-mask operations without animation or preparation rules."""
from PIL import Image
from PIL import ImageChops
from statistics import median

def row_background_mask(image, threshold=28):
    """Suppress broad horizontal background bands using both image side margins."""
    rgb=image.convert('RGB');width,height=rgb.size;edge=max(1,width//30)
    background=Image.new('RGB',rgb.size)
    positions=list(range(edge))+list(range(width-edge,width))
    for y in range(height):
        samples=[rgb.getpixel((x,y)) for x in positions]
        color=tuple(round(median(p[c] for p in samples)) for c in range(3))
        background.paste(color,(0,y,width,y+1))
    channels=ImageChops.difference(rgb,background).split()
    return ImageChops.lighter(ImageChops.lighter(channels[0],channels[1]),channels[2]).point(lambda v:255 if v>threshold else 0)

def main_component(mask):
    width,height=mask.size
    active={i for i,v in enumerate(mask.convert('L').tobytes()) if v}
    largest=[]
    while active:
        seed=active.pop();stack=[seed];component=[seed]
        while stack:
            i=stack.pop();x,y=i%width,i//width
            for nx,ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                j=ny*width+nx
                if 0<=nx<width and 0<=ny<height and j in active:
                    active.remove(j);stack.append(j);component.append(j)
        if len(component)>len(largest):largest=component
    result=Image.new('L',mask.size);pixels=result.load()
    for i in largest:pixels[i%width,i//width]=255
    return result
