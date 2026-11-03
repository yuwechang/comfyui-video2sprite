# 圖片預處理

先依[角色與動畫計畫](character-plan.md)取得所選姿態與角色基準邊長 S。一般姿態準備自然站立參考；攻擊姿態準備戰鬥待機架勢，可包含原設計武器，但不是正在出招。只選攻擊姿態時，不額外建立自然站姿。透過 `scripts/process_image.py` 產生保留外觀、形體與正側視角、面朝右的完整透明參考。

一種姿態先建立尺度與站位；同時選兩種時，以第一種確認參考的畫布、身體比例與腳下站位為共用基準，再編輯得到另一種姿態，保持畫布尺寸、角色尺度與根部站位。不要將蹲低的戰鬥姿態重新放大到自然站姿高度，也不要各自依外接框重新置中。若編輯模型未保持基準，修正參考再繼續。圖片參考仍需後續生成真正的 Idle 動畫。

## 建立共用尺度與站位

```text
python scripts/prepare_character.py --stage standing --image standing.png --image-profile .local/image-profile.json --job work/character/standing-job --output outputs/character-reference
```

Python 保持角色畫布尺寸，四邊內距為 `ceil(短邊×3%)`。角色等比例放入內框，以站立角色最下方 5% 的可見區域估計腳下水平站位，將此錨點對齊畫布中線，最下緣對齊內框底邊。頭髮、飄帶的整體外接框不作為水平定位基準。定位使用 Alpha 至少 16 的範圍，保留完整 Alpha。

輸出透明 `standing.png`、尺度及錨點資料 `standing.json`，並以 `preview.png` 展示左側實際透明素材、右側灰底與黃色內距框。透明原檔不加背景或框線。Codex 檢視腳下站位、完整性及外觀，展示給使用者確認；需要時修改後重新建立站立參考。

`standing` 是幾何準備階段與輸出檔名，支援所選的待機姿態，不表示強制自然站立。第二種姿態保持第一種已確認的畫布與座標，直接共用第一份 `standing.json`；不再次執行 `--stage standing` 以免按新外接框重新縮放。兩種參考分開保存，角色尺度只建立一次。

## 建立影片演出版面

確認姿態參考後，使用該圖建立對應 Idle 的影片輸入：

```text
python scripts/prepare_character.py --image outputs/character-reference/standing.png --standing-reference outputs/character-reference/standing.json --side 256 --video-profile .local/profile.json --job work/action/preparation-job --output outputs/action-input
```

以固定站立畫布最大邊與 S 決定生成尺度，保留來源細節，倍率允許小數。以目標尺度計算左右、上方各 S/2，底部 ceil(S×7%)，再整體換算到生成尺度。影片設定的 `generation.max_pixels` 預設 1,000,000；完整畫布超出預算時等比例降低尺度，再補齊工作流尺寸倍數。寬度餘量分到左右，高度餘量加到上方，補齊後不再檢查預算。

角色依站立錨點定位於影片畫布中線與基準框底部，不按輪廓重新置中。補邊或改變生成尺度只換算同一座標關係。Python 依輪廓亮度選擇 0.25～0.75 的純灰背景，一般使用中灰，偏暗角色配較亮背景，偏亮角色配較暗背景。

影片超框需要追加空間時，`--expand-horizontal N` 指定左右各追加 N 級 S/4，`--expand-top N` 指定上方追加 N 級 S/4。重用版面以 `--preparation preparation.json` 傳入設定，同資料夾的設定也會自動讀取；相同總級數不重複擴充，未指定級數沿用。每次輸出使用獨立任務目錄。

輸出 `prepared.png`、`preparation.json`，包含實際尺度、錨點換算及 `restore_scale`（S 除以實際生成基準邊長）。各姿態用相同 S 與共用 `standing.json`，分開保存版面及其縮回倍率；Codex 檢視後先生成該姿態的 Idle 影片。地面動作改用該 Idle 來源中的完整基準影格；空中動作依[空中處理](airborne.md)使用保存的完整空中基準。沿用各自的畫布、錨點與縮回倍率，不重新按每個動作的輪廓建立角色尺度。需要追加留白時依既有擴充方式處理。
