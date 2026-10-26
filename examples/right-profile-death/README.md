# 倒地死亡：不可循環

[繁體中文](README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [English](README.en.md)

[← 回到安裝與使用說明](../../README.md)

沿用自然站立參考與灰階演出版面，直接生成目標動作。Python 自動排除姿態過渡、選段及等距取樣，再完成共同裁切、整張去背與交付。

<table><tr><th>角色參考圖</th><th>透明成品</th></tr><tr><td align="center"><img src="images/character-reference.png" alt="reference" height="300"></td><td align="center"><img src="result/preview.gif" alt="preview" height="249"></td></tr></table>

> 面朝右的倒地死亡動作，最後維持倒地姿態，角色基準大小 256×256。

本例使用 MiniMax H3 生成影片、Qwen Image 2.1 處理圖片。下列皆為實際使用的素材與提示詞。

## 1. 上傳角色參考圖

**使用者**提供角色參考與需求。**Codex**判斷這張帶有透視與動態姿勢的宣傳圖，需先準備完整的自然站立參考。

<p align="center"><img src="images/character-reference.png" alt="character-reference" width="400"></p>

[下載原圖](images/character-reference.png)

## 2. 建立自然站立參考與固定站位

**ComfyUI**建立自然站立參考；**Python**整理短邊 3% 的內距。本次參考圖為 **1024×1536、內距 31 px**。建立演出版面時，以站姿腳下位置作為水平錨點及底部基準，避免頭髮與飄帶改變身體站位。**Codex**展示參考供確認。

<p align="center"><img src="images/standing-preview.png" alt="standing-preview" width="900"></p>

左側為實際透明 PNG，右側為灰底與黃色內距框的確認圖。灰底與框線不會畫進透明原檔。

[透明站立圖](images/standing.png) · [實際站立提示詞](prompts/standing.txt)

## 3. 直接建立影片輸入版面

**演出版面為動作伸展預留空間，降低四肢、頭髮或配件超出畫面而被裁切的機會。** **Python**直接放入自然站姿，保持固定錨點，依像素預算決定生成尺度，再補齊工作流的尺寸倍數。交付時依完整動作共同裁切。

<p align="center"><img src="images/video-input.png" alt="video-input" width="640"></p>

| 項目 | 本次結果 |
| --- | --- |
| 角色目標基準框 | 256×256 |
| 生成畫布 | 1152×896 |
| 背景 | 純灰 RGB（128, 128, 128） |
| 像素預算 | 對齊前 998,280；對齊後 1,032,192，允許補邊餘量 |
| 統一縮回倍率 | 256÷564 ≈ 0.453901 |

[下載實際影片輸入圖](images/video-input.png)

## 4. 從站姿生成目標動作

**Codex**準備由自然站姿進入戰鬥架勢、再演出目標動作的提示詞；**Python**提交、在本機等待並下載；**ComfyUI**產生影片。

本片由站姿轉為架勢，再失去力量倒地，末段保持倒地姿態。

<p align="center"><img src="video/source-preview.gif" alt="source-preview" width="576"></p>

原片：**1152×896、24 FPS、158 格、約 6.58 秒**。上圖為網頁預覽 GIF；MP4 保留原始解析度。

[觀看／下載 MP4](video/source.mp4) · [實際影片提示詞](prompts/video.txt)

## 5. Python 自動選段與選幀

**Codex**指定 `once`：動作結束不回到起始姿態。**Python**先找到末端穩定倒地區段，再回找最後一個符合條件的起始穩定段，排除自然站立與轉架勢的前段。

自動區間為 **86～136 格**，包含頭尾。等距取樣 **12 格**：**86, 91, 95, 100, 104, 109, 113, 118, 122, 127, 131, 136**。影格編號由 0 起算。

<p align="center"><img src="images/selected-frames.png" alt="selected-frames" width="900"></p>

## 6. 統一縮回、共同裁切與拼接

**Python**將所有選中影格以同一倍率縮回，計算以影片中線為中心的左右對稱共同裁切框，不逐幀重新置中、貼底或縮放。底部補 1 px，再依左至右、上至下排列為 **6 欄×2 排**。

<p align="center"><img src="images/spritesheet-before-removal.png" alt="spritesheet-before-removal" width="900"></p>

每格 **303×249 px**，整張 **1818×498 px**。256×256 是角色尺度基準；交付尺寸依完整動作範圍決定，保留原本的相對位移。

[下載尚未去背影格表](images/spritesheet-before-removal.png)

## 7. 整張去背與交付

**ComfyUI**對整張影格表去背一次；**Python**檢查尺寸、透明度與 GIF 時間，並打包全部素材；**Codex**檢視後展示成品。棋盤格僅作展示，原 PNG 為真正透明背景。

<p align="center"><img src="images/spritesheet-preview.png" alt="spritesheet-preview" width="900"></p>

<p align="center"><img src="result/preview.gif" alt="preview" width="303"></p>

GIF 每段 **1.2 秒**，為方便網頁觀看而重播。倒地後重新站起的跳接只是預覽重新開始；遊戲中此動作播放一次，結束後停留尾姿勢。

| 下載 | 內容 |
| --- | --- |
| [透明影格表 PNG](result/spritesheet.png) | 12 · 6×2 · 303×249 px |
| [預覽 GIF](result/preview.gif) | 1.2 s |
| [完整素材 ZIP](death-complete.zip) | 約 39 MB，含原圖、站立參考、影片輸入、來源影片、全部 158 張影格、12 張選中影格、實際提示詞與成品。 |
| [成品規格 JSON](result/animation.json) | 自動選段、取樣、共同裁切與播放時間 |
| [實際去背提示詞](prompts/background-removal.txt) | 整張去背使用的文字 |

## 值得保存的素材

- 自然站立參考與演出版面：同一角色的其他動作可重用尺度、站位與外觀。
- 來源影片與全部影格：可重新選段、人工挑幀或調整播放節奏，不必再生成影片。
- 實際提示詞與輸入圖：可帶到 ComfyUI 自行測試，再將影片交回 Skill 處理。

[連續循環：走路](../right-profile-walk/README.md) · [非連續循環：攻擊](../right-profile-attack/README.md) · [不可循環：死亡](../right-profile-death/README.md)
