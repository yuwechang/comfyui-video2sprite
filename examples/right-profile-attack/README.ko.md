# 펀치 공격: 일시 정지가 있는 루프

[繁體中文](README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [English](README.en.md)

[← 설치 및 사용 안내](../../README.ko.md)

자연스럽게 서 있는 참고 이미지와 회색조 동작 캔버스를 재사용하여 바로 동작을 생성합니다. Python이 자세 전환을 제외하고 구간을 자동 선택한 뒤 일정 간격 추출, 공통 자르기, 합치기, 배경 제거 및 전달을 진행합니다.

<table><tr><th>캐릭터 참고 이미지</th><th>투명 결과물</th></tr><tr><td align="center"><img src="images/character-reference.png" alt="reference" height="300"></td><td align="center"><img src="result/preview.gif" alt="preview" height="249"></td></tr></table>

> 오른쪽으로 펀치한 뒤 전투 자세로 돌아오는 동작. 캐릭터 기준 크기 256×256.

동영상은 MiniMax H3, 이미지는 Qwen Image 2.1을 사용했습니다. 아래는 실제 사용한 자료와 프롬프트입니다.

## 1. 참고 이미지 업로드

**사용자**가 참고 이미지와 요청을 제공합니다. **Codex**는 원근과 역동적인 자세가 있는 홍보 이미지이므로 온전하게 서 있는 참고 이미지를 먼저 준비합니다.

<p align="center"><img src="images/character-reference.png" alt="character-reference" width="400"></p>

[원본 다운로드](images/character-reference.png)

## 2. 서 있는 참고 이미지와 고정 위치 설정

**ComfyUI**가 서 있는 참고 이미지를 만들고 **Python**이 짧은 변의 3%를 안쪽 여백으로 정합니다. **1024×1536, 여백 31 px**입니다. 동작 캔버스에서는 발밑 위치를 가로 앵커와 하단 기준으로 삼아 머리카락과 띠가 몸 위치를 바꾸지 않게 합니다. **Codex**가 확인용으로 표시합니다.

<p align="center"><img src="images/standing-preview.png" alt="standing-preview" width="900"></p>

왼쪽은 실제 투명 PNG, 오른쪽은 회색 배경과 노란 여백 가이드입니다. 배경과 선은 원본에 포함되지 않습니다. 공용 이미지 안의 표기는 번체 중국어입니다.

[투명 서 있는 이미지](images/standing.png) · [서 있는 자세 프롬프트](prompts/standing.txt)

## 3. 동영상 입력 캔버스 바로 만들기

**동작 캔버스는 팔다리, 머리카락, 장식이 움직일 공간을 확보하여 잘림을 줄입니다.** **Python**이 고정 앵커로 캐릭터를 배치하고 픽셀 예산에 맞춰 생성 배율을 정한 뒤 치수 배수에 맞춥니다. 결과물은 전체 동작을 담는 공통 영역으로 자릅니다.

<p align="center"><img src="images/video-input.png" alt="video-input" width="640"></p>

| 항목 | 실제 결과 |
| --- | --- |
| 목표 기준 틀 | 256×256 |
| 생성 캔버스 | 1152×896 |
| 배경 | 단색 회색 RGB (128, 128, 128) |
| 픽셀 예산 | 정렬 전 998,280, 정렬 후 1,032,192. 추가 여백의 소폭 초과 허용 |
| 공통 복원 배율 | 256÷564 ≈ 0.453901 |

[실제 입력 이미지](images/video-input.png)

## 4. 서 있는 자세에서 목표 동작 생성

**Codex**가 서 있는 자세에서 전투 자세로 전환한 뒤 목표 동작을 하는 프롬프트를 작성합니다. **Python**이 제출, 로컬 대기, 다운로드를 담당하고 **ComfyUI**가 동영상을 생성합니다.

실제 영상은 연속 펀치 후 전투 자세로 돌아옵니다. 결과물은 선택 구간의 실제 동작을 유지합니다.

<p align="center"><img src="video/source-preview.gif" alt="source-preview" width="576"></p>

원본: **1152×896, 24 FPS, 107 프레임, 약 4.46초**. GIF는 웹 미리보기이고 MP4는 원본 해상도를 유지합니다.

[MP4 보기／다운로드](video/source.mp4) · [동영상 프롬프트](prompts/video.txt)

## 5. 구간 및 프레임 자동 선택

**Codex**는 `paused`를 지정합니다. 비슷한 시작 자세로 돌아오며 반복 연결 지점에서 멈출 수 있습니다. **Python**이 비슷한 준비·복귀 안정 자세를 찾아 양 끝을 포함합니다.

자동 구간은 **48~94 프레임**이며 양 끝을 포함합니다. 일정 간격으로 선택한 **12장**: **48, 52, 56, 61, 65, 69, 73, 77, 81, 86, 90, 94**. 번호는 0부터 시작합니다.

<p align="center"><img src="images/selected-frames.png" alt="selected-frames" width="900"></p>

## 6. 공통 배율 복원, 자르기 및 합치기

**Python**이 모든 선택 프레임에 같은 복원 배율을 적용하고 동영상 중심선 기준 좌우 대칭의 공통 자르기 영역을 계산합니다. 개별 프레임의 가운데 정렬, 하단 정렬, 크기 변경은 하지 않습니다. 아래 1 px을 추가하고 왼쪽에서 오른쪽, 위에서 아래 순서로 **6열×2행**으로 배치합니다.

<p align="center"><img src="images/spritesheet-before-removal.png" alt="spritesheet-before-removal" width="900"></p>

각 셀 **217×245 px**, 전체 **1302×490 px**입니다. 256×256은 캐릭터 배율 기준이며 전체 동작과 상대적 이동을 보존합니다.

[배경 제거 전 시트](images/spritesheet-before-removal.png)

## 7. 전체 배경 제거 및 전달

**ComfyUI**가 시트 전체 배경을 한 번에 제거합니다. **Python**이 크기, 투명도, GIF 시간을 검증하고 자료를 묶습니다. **Codex**가 검토하여 표시합니다. 체커보드는 표시용이며 원본 PNG는 실제 투명 배경입니다.

<p align="center"><img src="images/spritesheet-preview.png" alt="spritesheet-preview" width="900"></p>

<p align="center"><img src="result/preview.gif" alt="preview" width="217"></p>

GIF는 이 공격 구간을 **0.8초**로 반복합니다. 시작과 끝 자세가 비슷하며 연결 지점의 멈춤을 유지합니다.

| 다운로드 | 내용 |
| --- | --- |
| [투명 PNG 시트](result/spritesheet.png) | 12 · 6×2 · 217×245 px |
| [GIF 미리보기](result/preview.gif) | 0.8 s |
| [전체 자료 ZIP](attack-complete.zip) | 약 27 MB. 원본, 서 있는 참고, 입력 이미지, 원본 동영상, 전체 107 프레임, 선택 12장, 실제 프롬프트 및 결과물. |
| [결과 JSON](result/animation.json) | 자동 구간 선택, 샘플링, 자르기, 재생 시간 |
| [배경 제거 프롬프트](prompts/background-removal.txt) | 시트 전체 처리에 사용한 문구 |

## 보관하면 좋은 자료

- 서 있는 참고와 캔버스: 다른 동작에서도 배율, 위치, 외형 재사용.
- 원본 동영상과 전체 프레임: 재생성 없이 구간, 수동 선택, 재생 타이밍 변경.
- 실제 프롬프트와 입력 이미지: ComfyUI에서 시험한 뒤 동영상을 Skill로 가져와 처리.

[연속 루프: 걷기](../right-profile-walk/README.ko.md) · [일시 정지가 있는 루프: 공격](../right-profile-attack/README.ko.md) · [비반복 동작: 쓰러지기](../right-profile-death/README.ko.md)
