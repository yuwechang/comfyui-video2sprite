# 圖片預處理

正常執行使用 [執行計畫與資料流](execution.md)，本頁定義該階段的規則與底層介面，不另寫工作區腳本串接。

先依[角色與動畫計畫](character-plan.md)取得所選姿態與角色基準邊長 S。一般姿態準備自然站立參考；攻擊姿態準備戰鬥待機架勢，可包含原設計或使用者指定裝備，但不是正在出招。只選攻擊姿態時，不額外製作一般 Idle；必要的中性靜態參考只是工作素材。依[初始姿勢圖](pose-generation.md)以 GPT Image 及正式登錄建立完整姿態參考：plain 模式採透明圖，preserve 模式採簡單牆面與地面，不先去背。使用者選擇 ComfyUI 時才使用 `scripts/process_image.py`；固定側面鏡頭下的身體朝向依所選架勢自然呈現。

一種姿態先建立尺度與站位；多種姿態以第一種已確認參考的畫布、身體比例與腳下站位為共用幾何基準，但新姿態不必以該姿態圖為編輯輸入。優先從同角色中性基準圖分別建立不同姿態，再保持共用畫布尺寸、角色尺度與根部站位。不要將蹲低的戰鬥姿態重新放大到自然站姿高度，也不要各自依外接框重新置中。若編輯模型未保持基準，依已確認的基準修正圖片再繼續。站姿圖完成版面處理後，即可用作目標動作的首幀。

## 準備姿態編輯提示詞與執行

先讀取[前段提示詞參考](prompts.md)的選圖策略、編寫原則與姿態版型。建立新姿態優先選同角色中性基準；微調同一姿態才沿用該姿態圖。這是有實測依據的優先策略，不是所有輸入都必須先重生中性圖。使用者已提供合適目標姿態時直接檢查並沿用。

依參考圖辨識角色身份、服裝、配件、實體裝備及繪製風格，以簡短目標描述交代所選架勢及必要的支撐、肢體與接觸關係。只寫「一般」或「攻擊」不足以確定架勢；也不因選擇攻擊姿態自行新增裝備。未提供的可見細節以一致且最少的補足處理，不重新設計角色。第二種姿態雖可另選中性輸入，仍須符合第一種已確認的共用幾何基準；這些座標要求不限制第一次參考的必要視角調整。此處不加入影片動作、視覺效果或後段逐幀 Refine 指令。

GPT Image 使用[初始姿勢接點](pose-generation.md)，不呼叫下列圖片工作流。使用者選擇 ComfyUI 時，將實際提示詞存成 UTF-8 檔案，再執行：

```text
python scripts/process_image.py --profile .local/image-profile.json --image character.png --prompt-file work/character/pose.txt --job work/character/pose-job
```

讀取命令回傳的 file 作為結果路徑，不猜檔名；確認圖片可讀、角色有效，並按模式檢查背景：plain 必須真正透明，preserve 必須有可保留的簡單牆面與地面。complete 只代表工作流完成，不代表外觀通過。對照原參考檢查目標姿態、肢體數量、握持／接觸、完整性、身份與裝備；必要時放大局部，手靠近裝備不等於握持成立。多姿態另查共用比例及站位。依[提示詞檢查與調整](prompts.md#檢查與有依據的調整)決定換參考或局部修詞，起始圖未合格前不提交依賴影片。變更輸入用新 job；同輸入中斷沿用原 job，沒有確認提交 ID 時先處理提交狀態歧義，不能盲目重送。依[檢查紀錄](spritesheet.md#檢查紀錄)保存結論，完成幾何準備後展示確認。

## 建立共用尺度與站位

本節的透明 standing 流程只用於 plain 模式；preserve 模式直接依下節保留原圖牆面與地面，並以 reference_geometry 共用尺度，不先建立透明 standing。

```text
python scripts/prepare_character.py --stage standing --image standing.png --image-profile .local/image-profile.json --job work/character/standing-job --output outputs/character-reference
```

Python 保持角色畫布尺寸，四邊內距為 `ceil(短邊×3%)`。角色等比例放入內框，以站立角色最下方 5% 的可見區域估計腳下水平站位，將此錨點對齊畫布中線，最下緣對齊內框底邊。頭髮、飄帶的整體外接框不作為水平定位基準。定位使用 Alpha 至少 16 的範圍，保留完整 Alpha。

輸出透明 `standing.png`、尺度及錨點資料 `standing.json`，並以 `preview.png` 展示左側實際透明素材、右側灰底與黃色內距框。透明原檔不加背景或框線。Codex 檢視腳下站位、完整性及外觀，展示給使用者確認；需要時修改後重新建立站立參考。

`standing` 是幾何準備階段與輸出檔名，支援所選的待機姿態，不表示強制自然站立。第二種姿態保持第一種已確認的畫布與座標，直接共用第一份 `standing.json`；不再次執行 `--stage standing` 以免按新外接框重新縮放。兩種參考分開保存，角色尺度只建立一次。

## 建立影片演出版面

生成前用既有 geometry 版面入口預留演出空間。以完整動作的預期外沿評估肢體、髮尾、衣帶、裝備與位移；踢擊須能容納完全伸腿，跳躍須考慮最高點。基本留白不足時，用 expand_horizontal、expand_top 或 expand_bottom 加大空間，維持角色基準與接地錨點。從新畫布取得生成尺寸與縮回倍率，生成後依影片指引掃描碰邊。

### 保留原圖牆面與地面

已有不透明的簡單背景及地面參考時，使用 `background_mode=preserve`，不先去背、不生成背景。Codex 在原圖指定一次 `subject_box=[x0,y0,x1,y1]` 包含完整角色，以及 `ground_anchor=[x,y]` 的鞋底接地基準。不要用陰影下緣、牆地交界或原圖底緣代替接地線；無法確定時先確認，不臆測。版面程式保留角色像素並等比例處理，向上、下延伸邊界行顏色，左右逐高度延伸邊界列顏色，因此牆地交界連續。這是邊緣延伸，不是背景內容生成；側邊有人物或複雜物件時須先換合適參考。

先用 `python scripts/region_proposals.py --image reference.png --output work/regions.json` 產生人物範圍與底部錨點候選及標示圖。requires_confirmation=true 表示仍須確認實際鞋底，不能將陰影、衣物或道具下緣直接當接地。沒有可靠候選則依實際圖片指定；不讓程式假裝已理解接地語意。

多姿態的 preserve layout 由範本引用第一份 preparation.json 作 reference_geometry，不再各自按新圖片長邊定義尺度。source_coordinate_scale 表示「本圖像素／共用基準源圖像素」：相同來源畫布未指定時為 1，不同畫布必須明確提供；裁去純留邊但人物像素大小不變時仍是 1，整張圖片放大兩倍時為 2。這是座標換算，不是要求把屈膝人物拉到相同高度。程式保存基準雜湊、來源尺寸及倍率，視覺上仍須檢查生成模型是否改變身體比例。

左右、上方仍依既有 S/2 規則。腳底接地線到畫布底部由 `bottom_ratio` 決定，同角色及同組角色採相同設定，與原圖底部空白量無關；新建版面未指定時採 0.15；重用版面沿用其已記錄設定。這是經版面及影片試看採用的可調預設，不是所有動作的最佳比例保證。像素預算調整生成倍率時，底部比例一併換算，對齊餘量仍放在上方。不要逐張依陰影或畫布比例重新定位。原有背景中多出的底部可裁除，但 subject_box 必須完整入框。

```text
python scripts/prepare_character.py --image ground-reference.png --background-mode preserve --subject-box X0 Y0 X1 Y1 --ground-anchor X Y --bottom-ratio 0.15 --side 512 --video-profile .local/profile.json --job work/layout-job --output outputs/action-input
```

接點同樣支援 geometry operation 的同名參數。`preparation.json` 保存原圖雜湊、人物範圍、接地基準、比例與位移；再次擴充／接續從記錄的原圖計算，不把已擴充結果當新角色再縮放。保留地面背景的影片，碰邊掃描及後段純色內容偵測可能把地面視為內容，需驗證後才用於完整批次；不能因預覽可用就宣稱選幀與去背整套已驗證。

確認姿態參考後，使用該圖建立對應 Idle 的影片輸入：

```text
python scripts/prepare_character.py --image outputs/character-reference/standing.png --standing-reference outputs/character-reference/standing.json --side 256 --video-profile .local/profile.json --job work/action/preparation-job --output outputs/action-input
```

以固定站立畫布最大邊與 S 決定生成尺度，保留來源細節，倍率允許小數。以目標尺度計算左右、上方各 S/2，鞋底到下緣預設 ceil(S×15%)，可由 bottom_ratio 明確指定，再整體換算到生成尺度。影片設定的 `generation.max_pixels` 預設 1,000,000；完整畫布超出預算時等比例降低尺度，再補齊工作流尺寸倍數。寬度餘量分到左右，高度餘量加到上方，補齊後不再檢查預算。

角色依站立錨點定位於影片畫布中線與基準框底部，不按輪廓重新置中。補邊或改變生成尺度只換算同一座標關係。Python 依輪廓亮度選擇 0.25～0.75 的純灰背景，一般使用中灰，偏暗角色配較亮背景，偏亮角色配較暗背景。

影片超框需要追加空間時，`--expand-horizontal N` 指定左右各追加 N 級 S/4，`--expand-top N` 指定上方追加 N 級 S/4，`--expand-bottom N` 指定下方追加 N 級 S/4。依實際碰邊方向增加留白，不用提示詞或後段重建代替缺失內容。重用版面以 `--preparation preparation.json` 傳入設定，同資料夾的設定也會自動讀取；相同總級數不重複擴充，未指定級數沿用，明確指定 0 才移除該方向追加量。每次輸出使用獨立任務目錄。擴充會按像素預算重新計算生成倍率，沿用新的 restore_scale 縮回同一角色尺度，不用影片像素尺寸推定角色變小。

輸出 `prepared.png`、`preparation.json`，包含實際尺度、錨點換算及 `restore_scale`（S 除以實際生成基準邊長）。各姿態用相同 S 與共用 `standing.json`，分開保存版面及其縮回倍率；確認後，地面動作直接使用 prepared.png 作為來源影片首幀；空中動作依[空中處理](airborne.md)使用保存的完整空中基準。沿用各自的畫布、錨點與縮回倍率，不重新按每個動作的輪廓建立角色尺度。需要追加留白時依既有擴充方式處理。
