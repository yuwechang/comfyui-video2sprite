# 쓰러지는 동작: 종료 자세를 유지하는 동작

[繁體中文](README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [English](README.en.md)

[← README](../../README.ko.md)

이 페이지는 동작 하나의 실제 소재와 결과를 보여주며 새 캐릭터의 전체 첫 제작 절차는 아닙니다. 메인 안내에서 자세와 동작을 선택해 시작하세요. 선택한 자세마다 Idle이 포함됩니다.

원본 영상, 정리 전후 프레임과 최종 결과를 비교하고 실제 소재와 프롬프트를 내려받을 수 있습니다.

## 1. 캐릭터 참조

<p><img src="images/character-reference.png" alt="Character reference" width="400"></p>

[PNG](images/character-reference.png)

## 2. 자세 참조

이 예제는 아래의 자연스러운 서 있는 참조를 사용합니다. 회색 배경과 노란 안내선은 확인용이며 투명 소재에는 포함되지 않습니다.

![Stance reference](images/standing-preview.png)

[PNG](images/standing.png) · [실제 프롬프트](prompts/standing.txt)

## 3. 영상 입력

팔다리, 머리카락과 장비가 화면 밖으로 잘리지 않도록 움직일 공간을 확보합니다.

![Video input](images/video-input.png)

[PNG](images/video-input.png)

## 4. 원본 영상

![Source video preview](video/source-preview.gif)

[MP4](video/source.mp4) · [실제 프롬프트](prompts/video.txt)

## 5. 선택 프레임

![Selected frames](images/selected-frames.png)

## 6. 공통 자르기

선택한 모든 프레임을 같은 범위로 잘라 동작 중 위치 관계를 유지합니다.

![Shared crop](images/first-crop-sheet.png)

## 7. 프레임 보정 및 배경 제거

동작 흐림과 부가 효과를 정리하고 배경을 제거합니다. 비교 이미지 위쪽은 처리 전, 아래쪽은 처리 후입니다.

![Before and after](images/refine-comparison.png)

![Refined frames](images/refined-sheet-preview.png)

[실제 프롬프트](prompts/refine.txt)

## 8. 투명 가장자리 정리 및 결과물

투명 가장자리를 정리한 다음 모든 프레임의 캐릭터 범위로 다시 공통 자르기합니다. 체크무늬는 투명 영역을 보여주는 미리보기 배경입니다.

![Edge cleanup and crop](images/alpha-comparison.png)

| 프레임 수 | 셀 | 배치 | 시트 | 재생 시간 |
| --- | --- | --- | --- | --- |
| 12 | 303×249 | 6×2 | 1818×498 | 1.2 s |

![Spritesheet](images/spritesheet-preview.png)

![Animation preview](result/preview.gif)

[PNG](result/spritesheet.png) · [GIF](result/preview.gif) · [JSON](result/animation.json) · [전체 소재 ZIP](death-complete.zip)

ZIP에는 캐릭터 참조, 영상 입력, 원본 영상, 단계별 프레임, 실제 프롬프트, PNG／GIF／JSON 결과물이 포함됩니다.
