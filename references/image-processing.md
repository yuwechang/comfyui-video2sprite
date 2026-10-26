# 圖片預處理

依目前階段執行以下步驟。圖片工作流由 `scripts/process_image.py` 上傳、等待與下載；Codex 準備本次提示詞並展示結果，需要修改時在目前成果上調整。生成與使用者確認分開，不自動接續下一階段。

## 自然站立參考

先確認角色基準邊長 S。以完整、自然站立的角色圖建立共用尺度；原圖不適合時，先透過圖片工作流產生自然站立參考圖，保留角色外觀與整體形體設計。

整理站立參考的配置後，展示給使用者確認：

```text
python scripts/prepare_character.py --stage standing --image standing.png --image-profile .local/image-profile.json --job work/character/standing-job --output outputs/character-reference
```

含背景時先透過圖片工作流去背。Python 保持畫布尺寸，四邊內距為 `ceil(圖片短邊×3%)`，角色等比例放入內框，水平置中、可見最下緣對齊內框底邊。輸出透明 `standing.png`、並排確認預覽 `preview.png` 及 `standing.json`，記錄內距與配置倍率。預覽左側呈現實際透明素材，右側加灰底及黃色內距框；透明原檔不加背景或框線，與預覽一起提供。展示此預覽供使用者確認後，才用這張站立圖準備動作首幀。尺度依據是配置後的固定角色畫布長寬，不是後續姿勢的外接框。定位使用 Alpha 至少 16 的可見範圍，輸出保留完整 Alpha。

## 動作首幀

站立圖已適合作首幀時可直接沿用。需要改姿勢時，Codex 依所需動作決定是否先擴充角色畫布，以及各方向的像素數：

```text
python scripts/prepare_character.py --stage pose-input --standing-reference outputs/character-reference/standing.json --pad-top 12 --output work/action/pose-input
```

`--pad-left`、`--pad-top`、`--pad-right`、`--pad-bottom` 預設 0。Python 只補透明空間，記錄原站立畫布尺寸、補邊與位移，輸出 `pose-input.png`、`pose-input.json`，不改角色像素或尺度。

將 `pose-input.png` 交給圖片工作流，提示詞描述目標姿勢、沿用參考角色的形體與尺度、保持這次輸入畫布尺寸，輸出完整透明角色。產生後先執行：

```text
python scripts/prepare_character.py --stage review --image pose-result.png --job work/action/review-job --output outputs/action-first-frame
```

Python 依目前畫布短邊計算同樣的 3% 內距，只以整數平移水平置中、對齊內框底邊，不縮放角色。較矮姿勢上方自然留出更多空白。若原尺度無法完整放入內框，增加角色畫布空間；不以縮小姿勢填滿內框。輸出透明 `first-frame.png`、`preview.png` 與位移資料 `first-frame.json`。同樣以左側透明素材、右側灰底與內距框的並排預覽供使用者確認，需要時修改後再次整理與展示。這時尚未建立影片演出版面。

## 影片演出版面

確認首幀後執行：

```text
python scripts/prepare_character.py --image outputs/action-first-frame/first-frame.png --standing-reference outputs/character-reference/standing.json --pose-input work/action/pose-input/pose-input.json --side 256 --video-profile .local/profile.json --image-profile .local/image-profile.json --job work/action/preparation-job --output outputs/action-input
```

直接使用站立圖時，以 `standing.png` 為輸入並省略 `--pose-input`。首幀畫布大小以對應的輸入資料核對。Python 先水平置中、貼底補償位置，再套用站立畫布建立的固定倍率；新姿勢的可見範圍只用於定位，不重算倍率。新增範圍一起縮放，可超出角色基準框並由演出留白容納。

以站立畫布最大邊與 S 決定理想生成尺度。按目標尺度計算左右與上方各 S/2、底部 ceil(S×7%) 及追加留白，再整體換算到生成尺度。影片設定提供 `generation.max_pixels`（預設 1,000,000）與尺寸對齊單位；完整畫布超出預算時，等比例降低整體生成尺度，倍率允許小數。最後寬高向上補齊工作流倍數，寬度餘量分到左右、高度餘量加到上方，補齊後不再檢查像素上限。

Python 依角色輪廓亮度分布選純灰背景：一般使用中灰，偏暗輪廓提高背景亮度，偏亮輪廓降低背景亮度，連續限制在 0.25～0.75（RGB 64～191）。

需要追加影片演出空間時，`--expand-horizontal N` 指定左右各追加 N 級 S/4，`--expand-top N` 指定上方追加 N 級 S/4，預設 0。重用已準備版面可傳入其 `--preparation preparation.json`，位於輸入圖片旁的同名設定也會自動讀取；未指定級數沿用，相同總級數不重複擴充。觸及像素預算時，統一調低生成尺度，角色與留白保持相同比例。每次輸出使用獨立任務目錄。

輸出 `prepared.png`、`preparation.json`，記錄生成尺度、首幀平移量及 `restore_scale`。此倍率等於 S 除以實際生成基準邊長，不因首幀畫布增加或姿勢範圍改變而重算。Codex 檢視最終構圖後，使用 `prepared.png` 生成影片並保留縮回倍率。
