# 倒地死亡：不可循环

[繁體中文](README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [English](README.en.md)

[← 返回安装与使用说明](../../README.zh-CN.md)

复用自然站立参考与灰阶动作画布，直接生成目标动作。Python 排除姿态过渡、自动选段和等距采样，再完成共同裁剪、整张去背景与交付。

<table><tr><th>角色参考图</th><th>透明成品</th></tr><tr><td align="center"><img src="images/character-reference.png" alt="reference" height="300"></td><td align="center"><img src="result/preview.gif" alt="preview" height="249"></td></tr></table>

> 面朝右的倒地死亡动作，最后保持倒地姿态，角色基准大小 256×256。

本例使用 MiniMax H3 生成视频、Qwen Image 2.1 处理图片。下列均为实际使用的素材与提示词。

## 1. 上传角色参考图

**用户**提供角色参考与需求。**Codex**判断这张带有透视与动态姿势的宣传图，需要先准备完整的自然站立参考。

<p align="center"><img src="images/character-reference.png" alt="character-reference" width="400"></p>

[下载原图](images/character-reference.png)

## 2. 建立自然站立参考与固定站位

**ComfyUI**生成自然站立参考；**Python**整理短边 3% 的内边距。本次参考图为 **1024×1536、内边距 31 px**。建立动作画布时，以脚下位置作为水平锚点和底部基准，避免头发与飘带改变身体站位。**Codex**展示参考供确认。

<p align="center"><img src="images/standing-preview.png" alt="standing-preview" width="900"></p>

左侧是实际透明 PNG，右侧是灰底与黄色内边距框的确认图。背景与框线不进入透明原图。共用图片内的标签为繁体中文。

[透明站立图](images/standing.png) · [实际站立提示词](prompts/standing.txt)

## 3. 直接建立视频输入画布

**动作画布为动作伸展预留空间，降低四肢、头发与配件超出画面被截断的可能。** **Python**直接放入自然站姿，保持固定锚点，按像素预算确定生成尺度，再补齐工作流的尺寸倍数。交付时按完整动作统一裁剪。

<p align="center"><img src="images/video-input.png" alt="video-input" width="640"></p>

| 项目 | 本次结果 |
| --- | --- |
| 角色目标基准框 | 256×256 |
| 生成画布 | 1152×896 |
| 背景 | 纯灰 RGB（128, 128, 128） |
| 像素预算 | 对齐前 998,280；对齐后 1,032,192，允许补边余量 |
| 统一缩回倍率 | 256÷564 ≈ 0.453901 |

[下载实际视频输入图](images/video-input.png)

## 4. 从站姿生成目标动作

**Codex**编写从自然站姿进入战斗架势、再进行目标动作的提示词；**Python**提交、在本机等待并下载；**ComfyUI**生成视频。

本片由站姿转为架势，再失去力量倒地，末段保持倒地姿态。

<p align="center"><img src="video/source-preview.gif" alt="source-preview" width="576"></p>

原片：**1152×896、24 FPS、158 帧、约 6.58 秒**。上图为网页 GIF；MP4 保留原始分辨率。

[观看／下载 MP4](video/source.mp4) · [实际视频提示词](prompts/video.txt)

## 5. Python 自动选段与选帧

**Codex**指定 `once`：结束后不回到起始姿态。**Python**先找末端稳定倒地区间，再回找最后一个符合条件的起始稳定段，排除自然站立与转架势的前段。

自动区间为 **86～136 帧**，包含头尾。等距采样 **12 帧**：**86, 91, 95, 100, 104, 109, 113, 118, 122, 127, 131, 136**。编号从 0 开始。

<p align="center"><img src="images/selected-frames.png" alt="selected-frames" width="900"></p>

## 6. 统一缩回、共同裁剪与拼接

**Python**对所有选中帧应用同一倍率，计算以视频中线为中心、左右对称的共同裁剪框，不逐帧重新居中、贴底或缩放。底部补 1 px，按从左到右、从上到下排列为 **6 列×2 行**。

<p align="center"><img src="images/spritesheet-before-removal.png" alt="spritesheet-before-removal" width="900"></p>

每格 **303×249 px**，整张 **1818×498 px**。256×256 是角色尺度基准；成品按完整动作范围裁剪，保留相对位移。

[下载去背景前的图集](images/spritesheet-before-removal.png)

## 7. 整张去背景与交付

**ComfyUI**对整张图集去背景一次；**Python**验证尺寸、透明度及 GIF 时间，并打包素材；**Codex**检查并展示结果。棋盘格仅用于展示，原 PNG 为真正透明背景。

<p align="center"><img src="images/spritesheet-preview.png" alt="spritesheet-preview" width="900"></p>

<p align="center"><img src="result/preview.gif" alt="preview" width="303"></p>

GIF 每段 **1.2 秒**，为了网页观看而重复。倒地后重新站起的跳变只是预览重新开始；游戏中此动作播放一次，然后保持尾姿势。

| 下载 | 内容 |
| --- | --- |
| [透明精灵图集 PNG](result/spritesheet.png) | 12 · 6×2 · 303×249 px |
| [预览 GIF](result/preview.gif) | 1.2 s |
| [完整素材 ZIP](death-complete.zip) | 约 39 MB，含原图、站立参考、视频输入、源视频、全部 158 帧、12 张选中帧、实际提示词及成品。 |
| [成品规格 JSON](result/animation.json) | 自动选段、采样、共同裁剪与播放时间 |
| [实际去背景提示词](prompts/background-removal.txt) | 整张去背景使用的文字 |

## 值得保存的素材

- 自然站立参考与动作画布：其他动作可复用角色尺度、站位与外观。
- 源视频与全部帧：重新选段、人工挑帧或调整节奏，无需再次生成视频。
- 实际提示词与输入图：可在 ComfyUI 测试后，将视频交回 Skill 处理。

[连续循环：行走](../right-profile-walk/README.zh-CN.md) · [非连续循环：攻击](../right-profile-attack/README.zh-CN.md) · [不可循环：死亡](../right-profile-death/README.zh-CN.md)
