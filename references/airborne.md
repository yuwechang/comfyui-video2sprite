# 跳躍與空中處理（供 Codex 執行）

## 路徑與責任

先讀取[角色與動畫計畫](character-plan.md)的環境規則。只有明確的空中任務與跳躍製作請求進入本流程；地面任務保留完整演出的垂直位移，不能因文字內容提到離地或旋轉而套用本流程。

前段依任務的起始基準生成影片並檢查來源完整性；本段只處理明確提供的影片、區間、腰部參考及處理參數，不讀取角色計畫或前段內部目錄。既有影片也能直接使用這些入口。圖片工作流、Refine 提示詞與[影格表指引](spritesheet.md)共用。

地面／空中環境與三種動作類型是兩個獨立維度；前者決定起始基準和是否移除垂直位移，後者決定首尾及結束行為。

## 跳躍來源與分段

首次建立某姿態的跳躍時，前段使用對應 Idle 來源基準，生成由 Idle 開始、上升、到達頂點、下落、落地緩衝、再回到 Idle 的完整來源影片。提示詞保持同角色、朝向、尺度、鏡頭與留白，讓階段清楚；前段不先執行定位或 Refine。

檢視影片概覽後，指定三個原始影格索引：

- `rise_start`：已進入空中上升動作的開始，排除地面待機及起手過渡。
- `apex`：頂點附近清楚、完整且適合作為空中起收基準的一格。
- `fall_end`：下落動作結束，排除接地緩衝及返回 Idle 的過渡。

三者須依時間遞增。交付上升與下落兩段，各自等距取樣，兩段共用同一張 `apex`。不是將完整影片任意平均分成兩半，也不要求片段包含地面 Idle。

大寫參數以下均為本次明確指定的數值，執行前代入，不作固定預設：

```text
python scripts/airborne_pipeline.py jump source.mp4 --rise-start RISE_START --apex APEX --fall-end FALL_END --waist-roi X0 Y0 X1 Y1 --rise-count 8 --fall-count 8 --rise-seconds 0.8 --fall-seconds 0.8 --scale RESTORE_SCALE --job work/action/finish-job --output outputs/action --image-profile .local/image-profile.json --prompt-file work/action/refine.txt
```

輸出 `rise/`、`fall/` 各含 PNG、GIF、JSON；`jump.json` 記錄本機結果。`airborne-reference/` 保存原始完整切點畫布 `reference.png` 與 `airborne-reference.json`。該 profile 記錄畫布尺寸、腰部參考區域、統一縮回倍率；不得以最終小格或裁切後角色取代完整來源基準。兩段的共用切點只送入圖片工作流一次，整組使用相同第二次裁切，交界像素一致。

各段的 `shared_crop_source_indices` 記錄共同裁切所用的兩段選格聯集；裁切統計因此可能包含另一段影格，並非只用該段重新裁切。

將兩段 JSON 與來源、profile 寫入跳躍任務產物清單，完成[交付驗證](spritesheet.md#完成與交付驗證)後，再完成任務並執行 `record-airborne`。同姿態的後續空中動作重用此基準及倍率；另一姿態需要自己的基準。

## 腰部垂直定位

操作順序固定：**選段 → 等距取樣 → 只抽出選中影格 → 腰部定位 → 第一次共同裁切 → 只對選中影格逐張 Refine／去背 → Alpha 清理 → 再次共同裁切 → 拼表與預覽**。

Codex 在切點原始畫布上指定一次 `waist_roi=[x0,y0,x1,y1]`，範圍以腰部可辨識的身體與服裝特徵為主，避免只選背景或整片無紋理顏色。區域須在畫布內，兩邊至少 12 像素。腰部是最終決定的垂直定位基準，不是重新估計人體物理旋轉軸，也不是每張輪廓、面積或頭部中心。

`scripts/airborne.py` 只比較選中影格。Python 將腰部樣板以不同角度匹配，保留多個候選並細化，取得當前腰部中心。以參考腰部中心與當前中心的 Y 差對整張影格平移；**不反向旋轉、不改尺度、不逐張置中或貼底，不移除水平位移**。所有影格共同擴充畫布容納平移結果，再共同裁切。旋轉仍是角色動作本體，不能被定位消除。

`--crop-margin` 預設 8，僅在送入圖片編輯前的共同裁切保留安全空間，供髮絲或配件邊緣重繪。最終仍依 Alpha 共同裁切。它不是角色位移補償，也不能修復來源已截斷的內容。

## 空中追加動作

前段以保存的完整空中參考圖為影片輸入，維持其畫布尺寸及角色尺度。依所選動作類型描述空中起收姿態與節奏；不自動加入地面起跳、接地或地面 Idle。需要返回起始時，回到同一空中基準。來源停留及發力節奏由等距取樣保留，不以非等距挑格壓縮相近姿態。

```text
python scripts/airborne_pipeline.py action source.mp4 --reference-profile outputs/action/airborne-reference/airborne-reference.json --start START --end END --count 8 --seconds 0.8 --motion-type return_to_start --job work/new-action/finish-job --output outputs/new-action --image-profile .local/image-profile.json --prompt-file work/new-action/refine.txt
```

未指定 `--scale` 時沿用 profile 的倍率；明確指定才覆寫。來源畫布尺寸須與 profile 一致。此入口不根據動作描述或名稱分流，也不自行建立地面過渡。跳躍流程與追加空中動作使用相同腰部定位及影格整理程式。

## 追蹤檢查、失敗與接續

先檢查工作目錄的 `alignment.json`、`selected/`、`aligned/` 及 `alignment-preview.png`，確認腰部確實被追到、角色旋轉保留、補償無異常跳動。`matches` 使用原始來源影格索引，座標是原始畫布，尚未縮放或裁切。

`--max-match-error` 預設 0.25，是色彩匹配誤差的粗略停止門檻，不是成功機率。超過時寫出診斷並停止在 Refine 前。沒有超過也必須目視檢查選中影格；誤匹配可能仍有低誤差。均勻區域、遮擋、缺失、尺寸變更或大幅重繪可能失敗，不能宣稱所有角色都適用。

錯配時先確認參考區域是否合適；只在必要的選中影格上由 Codex 視覺指定腰部中心，保存成 JSON：鍵為原始影格編號的字串，值為原始畫布 `[x,y]` 數值陣列。以 `--waist-overrides work/action/waist-overrides.json` 重跑，報告記錄 `explicit_override`。只修正選中影格，不逐幀視覺判讀整段來源，也不將全部來源影格送去 Refine。

若定位輸入、區間、倍率或提示詞已改變，使用新任務目錄，避免混用已提交的圖片任務。中斷接續沿用原目錄，依既有圖片任務狀態重用完成結果，不重複提交。

## 輸出與交付

每段 JSON 包含 `environment=air`、`vertical_alignment`、`anchor_type=waist` 與最終格子座標中的 `anchor_px`。不同動作可能有不同裁切格子尺寸；跨動畫銜接應按共同角色尺度及腰部基準對齊，不能假定格子中心或底端就是角色定位點。需要同尺寸演示時，以各段固定的透明補邊註冊到共用畫布，不逐幀重定位。

Refine 後對照來源與定位結果，確認模型沒有把倒立或側向姿態改正、沒有改變腰部位置，並檢查首尾及衣物、裝備、髮絲。來源本身沒有回到所需姿態時，回報來源品質問題，不替換首尾影格掩蓋接縫。GIF 仍依[交付指引](spritesheet.md)無限重播；引擎中的播放、停留與中斷是另一件事。

用共用打包腳本分別打包各段；清單額外明確列出實際使用的空中 profile 及其參考 PNG，兩檔放在同一封存資料夾以保持相對路徑可用。另收錄實際 Refine 提示詞、定位報告及必要的人工修正 JSON。`jump.json` 是本機摘要，不直接當成已可攜的封存報告。
