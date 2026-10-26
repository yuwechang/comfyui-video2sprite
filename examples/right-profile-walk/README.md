# 從角色參考圖到走路循環

[← 回到安裝與使用說明](../../README.md)

上傳角色參考圖，確認自然站姿，直接用同一站立版面生成動作影片。Python 排除姿態過渡，自動選出循環並製作透明成品。

<table>
  <tr><th align="center">上傳的角色參考</th><th align="center">走路循環成品</th></tr>
  <tr>
    <td align="center"><img src="images/character-reference.png" alt="角色宣傳圖" height="300"></td>
    <td align="center"><img src="result/preview.gif" alt="透明走路循環" height="246"><br>8 格 · 0.8 秒 · 透明背景</td>
  </tr>
</table>

> **本次需求：** 面朝右、正側視角的走路循環動畫，角色基準大小為 256×256。

本次使用 MiniMax H3 生成影片、Qwen Image 2.1 處理圖片。以下是同一套灰階背景流程的實際素材。

## 1. 上傳角色參考圖

**使用者**提供圖片與需求。**Codex**判斷這張帶有透視和動態姿勢的宣傳圖，需先整理成完整自然站立參考。

<p align="center"><img src="images/character-reference.png" alt="使用者上傳的角色參考圖" height="440"></p>

[下載原圖](images/character-reference.png)

## 2. 建立自然站立參考與固定站位

**ComfyUI**產生正側面自然站姿；**Python**整理短邊 3% 的內距，以腳下站位建立水平錨點與底部基準，保留角色尺度。頭髮與飄帶不會把身體站位推向前方。**Codex**展示結果供使用者確認。

<p align="center"><img src="images/standing-preview.png" alt="左側實際透明素材，右側灰底與黃色內距框" width="900"></p>

原尺寸 **1024×1536**，內距 **31 px**。左側保留透明素材，右側的灰底與黃色框線僅供確認，不會畫進原檔。

[透明站立圖](images/standing.png) · [實際站立提示詞](prompts/standing.txt)

**可以重用：** 同一角色的其他動作共用這張自然站姿、角色尺度及站位基準。

## 3. 直接建立影片輸入版面

**Python**直接把自然站立角色放入灰階演出版面，以固定錨點定位。加入留白、按像素預算調整生成尺度，再補齊工作流要求的尺寸倍數。

<p align="center"><img src="images/video-input.png" alt="實際使用的灰底自然站立演出版面" width="640"></p>

| 項目 | 本次結果 |
| --- | --- |
| 角色目標基準框 | 256×256 |
| 實際生成畫布 | 1152×896，寬高皆為 32 倍數 |
| 背景 | 純灰 RGB（146, 146, 146） |
| 像素預算 | 對齊前 998,280；對齊後 1,032,192，允許補邊餘量 |
| 統一縮回倍率 | 256÷564，約 0.453901 |

[下載實際影片輸入圖](images/video-input.png)

**可以重用：** 此站立版面搭配不同的動作提示詞即可生成其他動作；也能帶到 ComfyUI 自行測試。

## 4. 從站姿生成目標動作

**Codex**在提示詞描述由站姿進入行走，再完成規律步態；**Python**提交並在本機等待與下載；**ComfyUI**負責姿態過渡及動作演出。

<p align="center"><img src="video/source-preview.gif" alt="從自然站立進入走路的來源影片預覽" width="576"></p>

原片為 **1152×896、24 FPS、107 格、約 4.46 秒**。上圖是網頁預覽 GIF，原影片保留完整解析度。

[觀看／下載 MP4](video/source.mp4) · [實際影片提示詞](prompts/video.txt)

**可以重用：** 重新選段、取樣或調整交付播放時間，都不必再次生成影片。

## 5. Python 自動找循環並選幀

**Codex**判斷這是接點不停頓的「連續循環」，指定 `continuous`；**Python**找出近似的首尾姿勢，排除準備與過渡，再等距選幀。

本次自動選定 **70～103 格**。第 **104 格**是近似的重複尾姿勢，因此不重複收取。8 張選中影格為 **70、74、78、83、87、91、96、100**，編號由 0 起算。

<p align="center"><img src="images/selected-frames.png" alt="實際自動選中的八張來源影格" width="900"></p>

| 動作類型 | 程式選段方式 |
| --- | --- |
| 連續循環 | 近似首尾，頭至尾−1 |
| 非連續循環 | 近似起手與回復姿態，頭至尾，保留接點停頓 |
| 不可循環 | 從末端穩定姿態回找最後起始穩定段，頭至尾 |

程式判定不明確時，才由 Codex 檢視並明確指定區間。全部來源影格與選中影格均另存於 ZIP。

## 6. 統一縮回、共同裁切與拼接

**Python**對所有選中影格套用同一倍率，再計算共用裁切框；以影片中線左右對稱保留動作範圍，不逐幀重新置中。底部補 1 px，按左至右、上至下排列為 **4 欄×2 排**。

<p align="center"><img src="images/spritesheet-before-removal.png" alt="共同裁切後尚未去背的灰底影格表" width="620"></p>

每格 **155×246 px**，整張 **620×492 px**。256×256 是角色尺度基準，交付格子依完整動作範圍裁切，可以是長方形。

[下載尚未去背影格表](images/spritesheet-before-removal.png)

## 7. 整張去背與交付

**ComfyUI**對整張影格表去背；**Python**驗證尺寸與透明度，從最終影格表製作 GIF，並將實際素材、全部及選中影格、提示詞打包。**Codex**檢視後，在對話中展示成品並附 ZIP。

<p align="center"><img src="images/spritesheet-preview.png" alt="棋盤襯底展示透明影格表" width="620"></p>

棋盤格僅作展示；原 PNG 保留真正透明背景。

<p align="center"><img src="result/preview.gif" alt="最終走路循環 GIF"></p>

| 下載 | 內容 |
| --- | --- |
| [透明影格表 PNG](result/spritesheet.png) | 8 格，4 欄×2 排，每格 155×246 |
| [預覽 GIF](result/preview.gif) | 透明背景，0.8 秒循環 |
| [完整素材 ZIP](walk-complete.zip) | 約 24 MB，含原圖、站立參考、影片輸入、來源影片、107 張全部影格、8 張選中影格、提示詞與成品 |
| [成品規格 JSON](result/animation.json) | 自動選段、取樣、共同裁切與播放時間 |
| [實際去背提示詞](prompts/background-removal.txt) | 整張去背使用的文字 |

## 值得保存的素材

| 素材 | 重用方式 |
| --- | --- |
| 自然站立參考 | 同一角色的尺度、站位與外觀參考 |
| 站立演出版面與提示詞 | 在 ComfyUI 生成其他動作或重試設定 |
| 來源影片與全部影格 | 重新選段、取樣與設定成品時間 |
| 最終透明影格表 | 匯入遊戲引擎或製作其他預覽 |

[開始安裝與使用 →](../../README.md#複製這句話給-codex)
