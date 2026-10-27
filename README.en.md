# ComfyUI Video to Sprite

[繁體中文](README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [English](README.en.md)

A character animation Skill for Codex. Upload a character image and describe an action to create a transparent sprite sheet and GIF preview using local ComfyUI. You can also supply an existing video and continue with frame selection and delivery.

Codex interprets requests, writes prompts, and reviews results. Local Python handles layout, scaling, job waiting, frame selection, cropping, packing, and validation. ComfyUI handles image processing and video generation. Conversation, confirmation options, and delivery explanations follow your language or explicit preference; workflow prompts use the language appropriate for the model.

<table>
  <tr><th>Character showcase</th><th>Walking loop</th></tr>
  <tr>
    <td align="center"><img src="docs/images/character-showcase.png" alt="Character showcase" height="270"></td>
    <td align="center"><img src="examples/right-profile-walk/result/preview.gif" alt="Transparent walking loop" height="246"><br>8 frames · 0.8 seconds · Transparent</td>
  </tr>
</table>

- [Continuous loop: walking](examples/right-profile-walk/README.en.md)
- [Loop with a pause: attack](examples/right-profile-attack/README.en.md)
- [Non-looping action: death](examples/right-profile-death/README.en.md)

Follow the actual results from the standing reference and performance canvas through the gray-background video to the transparent sheet, including assets you can reuse.

## Copy this request to Codex

```text
Please install this Codex Skill: https://github.com/yuwechang/comfyui-video2sprite . Follow the repository's installation instructions to install it and check the environment. Ask me only when required information is missing.
```

Codex follows the [installation and update instructions](references/install.md) to download the Skill and check Python packages and FFmpeg/ffprobe. If an external program is missing, it asks whether you want installation help. You do not need to copy folders, choose installation paths, or run Python yourself.

## What you need

- A Codex environment with access to local files and ComfyUI.
- Working ComfyUI, models, and nodes. Start ComfyUI before use.
- API-format workflow JSON files: one for video generation and one for image processing. For existing videos, start with the image workflow only.

The Skill does not include models, nodes, FFmpeg, or ffprobe. Codex checks the environment and installs only missing dependencies with the necessary approval.

## First use

Tell Codex which working folder should hold your assets and results, and provide your workflow JSON files. It first tries `http://127.0.0.1:8188`, asks for another address only if that fails, then helps identify and save node mappings.

Upload a character image and describe the action. When a standing reference needs confirmation, Codex displays it. If UI questions are available, you can answer with an option or free text.

### Video workflow

The workflow must expose image inputs, a positive prompt, width, height, video length, seed, and a downloadable video output. The purpose of each image input and whether the second image can be omitted are recorded in the mapping. Single-image generation uses the configured omission method.

FPS, dimension multiples, valid frame counts, and ranges are also recorded. The default generation canvas budget is **1,000,000 pixels**, adjustable in local settings. Final padding to workflow dimension multiples may slightly exceed it. Usable resolution and duration depend on your hardware and workflow.

### Image workflow

The workflow must accept an image and editing prompt, save results, generate natural standing references, and remove backgrounds to produce genuinely transparent PNGs. Whole-sheet background removal must preserve dimensions, cell positions, and character scale. Image dimension multiples are recorded during setup.

This project's example uses **MiniMax H3** for video and **Qwen Image 2.1** for images. This is a tested combination, not a model restriction: the Skill connects through node mappings. You provide model weights, nodes, and API workflows; installing the Skill does not install them.

## Create an animation

Upload a character image and tell Codex:

> Use comfyui-video2sprite to create a walking loop facing right in a strict side view, with a 256×256 character baseline.

If necessary, a natural standing reference is prepared for your confirmation. The standing canvas is used directly to generate the target action; Python excludes the posture transition and selects an interval automatically. The baseline establishes character scale. Final cells share a crop enclosing the complete action, so they may be rectangular or exceed the baseline when the character extends outward.

Frame count starts at 8 and is adjusted to the action. Each action receives its own deliverables:

- `spritesheet.png`: transparent sheet with equal-sized cells, ordered left to right, then top to bottom.
- `preview.gif`: transparent looping preview made from the final sheet.
- `animation.json`: dimensions, sampling, playback timing, and other output data.
- A ZIP containing the uploaded image, standing reference, video input, source video, all extracted and selected frames, actual prompts, and final outputs.

Image and video processing run in local ComfyUI. Prompt preparation, conversation, and visual review still use Codex usage allowance.

## Use an existing video

Provide a video and describe the action interval, playback duration, and size requirements to continue with selection, shared cropping, packing, background removal, and GIF creation.

Suitable videos have:

- The complete character and action, without clipped limbs, hair, or accessories.
- A simple, distinguishable background with sufficient separation from the character; avoid complex scenery, captions, and occlusions.
- Clear enough action frames to select.

Videos do not need the Skill's performance padding. The crop is calculated from selected frames. Slight background color differences between frames are acceptable; complex scenes are outside the currently supported scope.

If a generated result is unsatisfactory, ask Codex for the prepared input image and actual prompt, experiment in ComfyUI, then bring a suitable video back to continue processing.

## Local data and updates

Workflow files and mappings live in the working folder's `.local/`, intermediate tasks in `work/`, and deliverables in `outputs/`. These are separate from the Skill installation and are not distributed with it.

To update, tell Codex:

```text
Please update comfyui-video2sprite following this repository's installation and update instructions, preserving my workflow settings, assets, and outputs: https://github.com/yuwechang/comfyui-video2sprite
```

Installation locations follow the [official OpenAI Skill documentation](https://learn.chatgpt.com/docs/build-skills). Codex-facing [workflow setup details](references/setup.md) describe mapping and validation. Internal instructions are shared across languages; Codex explains them in your language.
