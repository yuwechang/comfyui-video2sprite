# 从角色参考图到行走循环

[繁體中文](README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [English](README.en.md)

[← 返回安装与使用说明](../../README.zh-CN.md)

上传角色参考图，确认自然站姿，直接用同一站立画布生成动作视频。Python 排除姿态过渡，自动选择循环并制作透明成品。

<table>
  <tr><th>上传的角色参考</th><th>行走循环成品</th></tr>
  <tr><td align="center"><img src="images/character-reference.png" alt="角色宣传图" height="300"></td><td align="center"><img src="result/preview.gif" alt="透明行走循环" height="246"><br>8 帧 · 0.8 秒 · 透明背景</td></tr>
</table>

> **本次需求：** 面朝右、正侧视角的行走循环动画，角色基准大小为 256×256。

本次使用 MiniMax H3 生成视频、Qwen Image 2.1 处理图片。以下为同一套灰阶背景流程的实际素材。

## 1. 上传角色参考图

**用户**提供图片与需求。**Codex**判断这张带有透视和动态姿势的宣传图，需要先整理为完整的自然站立参考。

<p align="center"><img src="images/character-reference.png" alt="用户上传的角色参考图" height="440"></p>

[下载原图](images/character-reference.png)

## 2. 建立自然站立参考与固定站位

**ComfyUI**生成正侧面的自然站姿；**Python**整理短边 3% 的内边距，以脚下站位建立水平锚点与底部基准，保留角色尺度。头发与飘带不会把身体站位推向前方。**Codex**展示结果供用户确认。

<p align="center"><img src="images/standing-preview.png" alt="左侧为实际透明素材，右侧为灰底与黄色内边距框" width="900"></p>

原尺寸 **1024×1536**，内边距 **31 px**。左侧保留透明素材；右侧灰底与黄色框线仅供确认，不会画进原文件。共用预览图内的标签为繁体中文。

[透明站立图](images/standing.png) · [实际站立提示词](prompts/standing.txt)

**可以复用：** 同一角色的其他动作共用自然站姿、角色尺度及站位基准。

## 3. 直接建立视频输入画布

**动作画布用于为角色预留活动空间。** 四肢、头发或配件可能伸出自然站姿原本的范围；即使提示词要求角色留在画面内，视频模型也未必完全遵从。因此先留白，降低动作超出画面、身体被截断的可能。交付时再按完整动作范围统一裁剪。

**Python**以固定锚点把自然站立角色放入灰阶画布，加入留白、按像素预算调整生成尺度，再补齐工作流要求的尺寸倍数。

<p align="center"><img src="images/video-input.png" alt="实际使用的灰底自然站立动作画布" width="640"></p>

| 项目 | 本次结果 |
| --- | --- |
| 角色目标基准框 | 256×256 |
| 生成画布 | 1152×896，宽高均为 32 的倍数 |
| 背景 | 纯灰 RGB（146, 146, 146） |
| 像素预算 | 对齐前 998,280；对齐后 1,032,192，允许补边余量 |
| 统一缩回倍率 | 256÷564，约 0.453901 |

[下载实际视频输入图](images/video-input.png)

**可以复用：** 搭配不同动作提示词生成其他动作，也能带到 ComfyUI 自行测试。

## 4. 从站姿生成目标动作

**Codex**描述从站姿进入行走，再完成规律步态；**Python**提交任务、在本机等待并下载；**ComfyUI**生成姿态过渡与动作。

<p align="center"><img src="video/source-preview.gif" alt="从自然站立进入行走的源视频预览" width="576"></p>

原片为 **1152×896、24 FPS、107 帧、约 4.46 秒**。上图为网页预览 GIF，原视频保留完整分辨率。

[观看／下载 MP4](video/source.mp4) · [实际视频提示词](prompts/video.txt)

**可以复用：** 重新选段、采样或调整交付播放时间，不必再次生成视频。

## 5. Python 自动寻找循环并选帧

**Codex**判断这是接点不停顿的“连续循环”，指定 `continuous`；**Python**寻找近似首尾姿势，排除准备与过渡，再等距采样。

本次自动选择 **70～103 帧**。第 **104 帧**是近似的重复尾姿势，因此不重复收取。8 张选中帧为 **70、74、78、83、87、91、96、100**，编号从 0 开始。

<p align="center"><img src="images/selected-frames.png" alt="自动选择的八张源帧" width="900"></p>

| 动作类型 | 程序选段方式 |
| --- | --- |
| 连续循环 | 近似首尾，头至尾−1 |
| 非连续循环 | 近似起手与恢复姿态，头至尾，保留接点停顿 |
| 不可循环 | 从末端稳定姿态回找最后的起始稳定段，头至尾 |

找不到符合条件的区间时，才由 Codex 检查并指定区间。全部源帧与选中帧另存于 ZIP。

## 6. 统一缩回、共同裁剪与拼接

**Python**为所有选中帧应用同一倍率，再计算共用裁剪框；以视频中线左右对称保留动作范围，不逐帧重新居中。底部补 1 px，按从左到右、从上到下排列为 **4 列×2 行**。

<p align="center"><img src="images/spritesheet-before-removal.png" alt="共同裁剪后尚未去背景的图集" width="620"></p>

每格 **155×246 px**，整张 **620×492 px**。256×256 是角色尺度基准，交付格子根据完整动作范围裁剪，可以是长方形。

[下载尚未去背景的图集](images/spritesheet-before-removal.png)

## 7. 整张去背景与交付

**ComfyUI**对整张图集去背景；**Python**验证尺寸与透明度，从最终图集制作 GIF，并打包实际素材、全部与选中帧、提示词和成品。**Codex**检查后，在对话中展示成品并附上 ZIP。

<p align="center"><img src="images/spritesheet-preview.png" alt="棋盘底展示透明精灵图集" width="620"></p>

棋盘格仅用于展示；原 PNG 为真正透明背景。

<p align="center"><img src="result/preview.gif" alt="最终行走循环 GIF"></p>

| 下载 | 内容 |
| --- | --- |
| [透明精灵图集 PNG](result/spritesheet.png) | 8 帧，4 列×2 行，每格 155×246 |
| [预览 GIF](result/preview.gif) | 透明背景，0.8 秒循环 |
| [完整素材 ZIP](walk-complete.zip) | 约 24 MB，含原图、站立参考、视频输入、源视频、107 张全部帧、8 张选中帧、提示词与成品 |
| [成品规格 JSON](result/animation.json) | 自动选段、采样、共同裁剪与播放时间 |
| [实际去背景提示词](prompts/background-removal.txt) | 整张去背景时使用的文字 |

## 值得保存的素材

| 素材 | 复用方式 |
| --- | --- |
| 自然站立参考 | 同一角色的尺度、站位与外观参考 |
| 站立画布与提示词 | 在 ComfyUI 生成其他动作或重试设置 |
| 源视频与全部帧 | 重新选段、采样及设置播放时间 |
| 最终透明精灵图集 | 导入游戏引擎或制作其他预览 |

[开始安装与使用 →](../../README.zh-CN.md)
