# 挥剑：保留实体武器并移除附带特效

[繁體中文](README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [English](README.en.md)

[← README](../../README.zh-CN.md)

以同一角色站立版面加入实体剑，再生成挥剑视频。站立参考图尚未加入武器；实际视频输入图包含武器。

## 1. 角色参考图

![Reference](images/character-reference.png)

## 2. 自然站立参考

![Standing](images/standing-preview.png)

[PNG](images/standing.png) · [Prompt](prompts/standing.txt)

## 3. 视频输入与实体武器

[原始版面](images/pre-weapon-input.png) · [添加武器提示词](prompts/weapon-input.txt)

![Video input](images/video-input.png)

## 4. 来源视频

1152×896 · 24 FPS · 124 frames · 5.17 s

![Source preview](video/source-preview.gif)

[MP4](video/source.mp4) · [Prompt](prompts/video.txt)

来源视频与实际生成提示词保留原样；以下成品以当前后段流程重新处理。

## 5. 自动选段与采样

`paused` · 24–108 · 12 frames

`24, 32, 39, 47, 55, 62, 70, 77, 85, 93, 100, 108` (0-based source indices)

![Selected source frames](images/selected-frames.png)

## 6. 第一次共同裁切

517×408 px / frame

![First shared crop](images/first-crop-sheet.png)

## 7. 逐帧 Refine、去特效与去背

逐帧图片工作流保留姿势、尺度与位置，修复动态模糊并同时清理背景。上排为第一次共同裁切，下排为图片工作流的原始输出。

[实际 Refine 提示词](prompts/refine.txt)

![Source and refined comparison](images/refine-comparison.png)

![Raw refined frames](images/refined-sheet-preview.png)

## 8. Alpha 清理、再次共同裁切与交付

仅将 Alpha 小于 8 的值清为 0，保留其余半透明边缘；依全部帧共同裁切，底部保留 1 px 透明留白。棋盘格仅供预览。

![Alpha and second crop comparison](images/alpha-comparison.png)

| 帧数 | 单帧尺寸 | 排列 | 帧表 | 播放时间 |
| --- | --- | --- | --- | --- |
| 12 | 347×340 | 6×2 | 2082×680 | 1.2 s |

![Final spritesheet](images/spritesheet-preview.png)

![Animation](result/preview.gif)

[PNG](result/spritesheet.png) · [GIF](result/preview.gif) · [JSON](result/animation.json) · [完整素材包](sword-complete.zip)

[Workflow / validation](../../references/spritesheet.md)

完整 ZIP 包含来源视频、全部来源帧、选中帧、裁切帧、工作流输入、原始 Refine 输出、最终帧、提示词，以及 PNG／GIF／JSON。
