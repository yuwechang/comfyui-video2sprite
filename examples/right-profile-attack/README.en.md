# Punch attack: a loop with a pause

[繁體中文](README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [English](README.en.md)

[← Installation and usage](../../README.en.md)

Reuse a natural standing reference and grayscale performance canvas to generate the action directly. Python excludes posture transitions, selects an interval, samples evenly, then crops, packs, removes the background, and delivers the results.

<table><tr><th>Character reference</th><th>Transparent result</th></tr><tr><td align="center"><img src="images/character-reference.png" alt="reference" height="300"></td><td align="center"><img src="result/preview.gif" alt="preview" height="249"></td></tr></table>

> A right-facing punch attack that returns to a fighting guard, with a 256×256 character baseline.

This example uses MiniMax H3 for video and Qwen Image 2.1 for images. The assets and prompts shown are those actually used.

## 1. Upload the character reference

The **user** supplies the reference and request. **Codex** identifies that the promotional illustration has perspective and a dynamic pose, requiring a complete natural standing reference first.

<p align="center"><img src="images/character-reference.png" alt="character-reference" width="400"></p>

[Download original](images/character-reference.png)

## 2. Establish the standing reference and fixed position

**ComfyUI** creates the standing reference; **Python** applies an inset of 3% of the shorter side. The reference is **1024×1536 with a 31 px inset**. When building the performance canvas, the ground position defines the horizontal anchor and bottom reference, so hair and trailing fabric do not shift the body forward. **Codex** displays the reference for approval.

<p align="center"><img src="images/standing-preview.png" alt="standing-preview" width="900"></p>

Left: the actual transparent PNG. Right: a gray background and yellow inset guide for review only; neither is drawn into the asset. Labels inside this shared image are in Traditional Chinese.

[Transparent standing image](images/standing.png) · [Actual standing prompt](prompts/standing.txt)

## 3. Build the video input canvas directly

**The performance canvas reserves room for movement, reducing clipping of limbs, hair, and accessories.** **Python** places the standing character using a fixed anchor, adjusts scale to the pixel budget, then pads to workflow dimension multiples. Delivery uses a shared crop enclosing the full action.

<p align="center"><img src="images/video-input.png" alt="video-input" width="640"></p>

| Item | Actual value |
| --- | --- |
| Target character baseline | 256×256 |
| Generation canvas | 1152×896 |
| Background | Solid gray RGB (128, 128, 128) |
| Pixel budget | 998,280 before alignment; 1,032,192 after padding, allowing the small excess |
| Uniform restoration scale | 256÷564 ≈ 0.453901 |

[Download actual video input](images/video-input.png)

## 4. Generate the target action from standing

**Codex** describes a transition from standing into a fighting guard, followed by the requested action. **Python** submits, waits locally, and downloads; **ComfyUI** generates the video.

The generated video actually contains consecutive punches followed by a return to guard. The output preserves the motion in the selected interval.

<p align="center"><img src="video/source-preview.gif" alt="source-preview" width="576"></p>

Source: **1152×896, 24 FPS, 107 frames, approximately 4.46 seconds**. The GIF is a webpage preview; the MP4 retains full resolution.

[Watch/download MP4](video/source.mp4) · [Actual video prompt](prompts/video.txt)

## 5. Automatically select an interval and frames

**Codex** specifies `paused`: the action returns to a similar guard, with a pause allowed at the repeat boundary. **Python** selects similar stable preparation/recovery poses and includes both endpoints.

Automatic interval: **frames 48–94**, including both endpoints. **12** evenly sampled frames: **48, 52, 56, 61, 65, 69, 73, 77, 81, 86, 90, 94**. Indices start at zero.

<p align="center"><img src="images/selected-frames.png" alt="selected-frames" width="900"></p>

## 6. Restore scale, crop jointly, and pack

**Python** applies one restoration scale to all selected frames and calculates a common crop symmetric about the video centerline. It does not recenter, bottom-align, or rescale individual frames. A 1 px bottom margin is added, and frames are packed left to right, top to bottom in **6 columns × 2 rows**.

<p align="center"><img src="images/spritesheet-before-removal.png" alt="spritesheet-before-removal" width="900"></p>

Cells: **217×245 px**. Sheet: **1302×490 px**. The 256×256 baseline defines character scale; the crop encloses the whole action and preserves relative movement.

[Download sheet before background removal](images/spritesheet-before-removal.png)

## 7. Remove the background and deliver

**ComfyUI** removes the background from the entire sheet once. **Python** verifies dimensions, transparency, and GIF duration, and packages the assets. **Codex** reviews and displays the result. The checkerboard is for display only; the original PNG is transparent.

<p align="center"><img src="images/spritesheet-preview.png" alt="spritesheet-preview" width="900"></p>

<p align="center"><img src="result/preview.gif" alt="preview" width="217"></p>

The GIF repeats this attack interval in **0.8 seconds**. Its starting and ending guards are similar, retaining a pause at the boundary.

| Download | Contents |
| --- | --- |
| [Transparent PNG sheet](result/spritesheet.png) | 12 · 6×2 · 217×245 px |
| [GIF preview](result/preview.gif) | 0.8 s |
| [Complete asset ZIP](attack-complete.zip) | About 27 MB: original image, standing reference, input canvas, source video, all 107 frames, 12 selected frames, actual prompts, and results. |
| [Output JSON](result/animation.json) | Automatic interval, sampling, crop, and playback timing |
| [Background-removal prompt](prompts/background-removal.txt) | Actual whole-sheet removal prompt |

## Assets worth keeping

- Standing reference and canvas: reuse character scale, position, and appearance for other actions.
- Source video and all frames: reselect intervals, choose frames manually, or change timing without generating again.
- Actual prompts and input image: experiment in ComfyUI and return a video to the Skill for processing.

[Continuous loop: walking](../right-profile-walk/README.en.md) · [Loop with a pause: attack](../right-profile-attack/README.en.md) · [Non-looping action: death](../right-profile-death/README.en.md)
