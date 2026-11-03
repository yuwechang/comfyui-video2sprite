# Defeated collapse: hold end pose

[繁體中文](README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [English](README.en.md)

[← README](../../README.en.md)

This page shows the actual assets and results for one action, rather than the complete first-use procedure for a new character. Follow the main guide to choose stances and actions; each selected stance includes Idle.

Compare the source video, frame cleanup and final results below, and download the actual assets and prompts.

## 1. Character reference

<p><img src="images/character-reference.png" alt="Character reference" width="400"></p>

[PNG](images/character-reference.png)

## 2. Stance reference

This example uses the natural standing reference below. Gray backgrounds and yellow guides are review overlays, not part of the transparent asset.

![Stance reference](images/standing-preview.png)

[PNG](images/standing.png) · [Actual prompt](prompts/standing.txt)

## 3. Video input

Space around the character accommodates movement and reduces clipping of limbs, hair and equipment.

![Video input](images/video-input.png)

[PNG](images/video-input.png)

## 4. Source video

![Source video preview](video/source-preview.gif)

[MP4](video/source.mp4) · [Actual prompt](prompts/video.txt)

## 5. Selected frames

![Selected frames](images/selected-frames.png)

## 6. Shared crop

All selected frames use the same crop, preserving their relative placement throughout the action.

![Shared crop](images/first-crop-sheet.png)

## 7. Frame refinement and background removal

Repair motion blur, remove incidental effects and remove the background. The comparison shows frames before cleanup above and after cleanup below.

![Before and after](images/refine-comparison.png)

![Refined frames](images/refined-sheet-preview.png)

[Actual prompt](prompts/refine.txt)

## 8. Transparent edges and final results

After cleaning the transparent edges, all frames share another crop around the character. Checkerboards are preview backgrounds for transparent areas.

![Edge cleanup and crop](images/alpha-comparison.png)

| Frames | Cell | Grid | Sheet | Duration |
| --- | --- | --- | --- | --- |
| 12 | 303×249 | 6×2 | 1818×498 | 1.2 s |

![Spritesheet](images/spritesheet-preview.png)

![Animation preview](result/preview.gif)

[PNG](result/spritesheet.png) · [GIF](result/preview.gif) · [JSON](result/animation.json) · [Complete asset bundle](death-complete.zip)

The bundle includes character references, video input, source video, frames from each stage, actual prompts, and final PNG / GIF / JSON files.
