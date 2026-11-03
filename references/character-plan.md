# 角色與動畫計畫

## 觸發與對話範圍

已安裝 Skill 後，新對話可用「使用 `$comfyui-video2sprite`，替這個角色建立遊戲動畫」並附角色參考圖觸發。明確的角色動畫製作需求也可觸發；單純上傳圖片不代表要求執行。

一個對話只處理一個角色，使用獨立工作資料夾。首次參考存入計畫後不覆蓋。同角色補充參考可留在原對話，不重新詢問首次設定；用途不明時只釐清是否為同角色。第二個角色請使用者另開新對話並上傳圖片，不在目前計畫中切換角色。即使重用同一套本機工作流，新對話也不自動套用其他角色計畫。

僅提供既有影片時，直接執行後段，不強制建立 Idle、角色計畫或前段素材。

`examples/` 展示單一動作的實際素材、處理階段與成品規格，供外觀比較及素材回查；它們未示範新角色完整的 Idle 建立與批次任務流程。首次製作依本指引執行，不從範例使用者說明推導流程，也不因範例曾直接從站立圖片生成動作而省略本角色的 Idle。範例來源與實際提示詞是素材記錄，不是必須照抄的通用規則。

## 首次詢問

第一次提供新角色參考且要求製作時，集中收集三項。已明說的項目直接採用，只補問缺少的項目；多選工具不可用時，列出選項讓使用者以文字選擇，不把單選工具偽裝為多選。

1. **姿態（可複選）**：一般／攻擊。至少選一種。一般對應 `normal`；攻擊對應 `combat`，指戰鬥準備架勢，不是執行出招。
2. **其他動作（可複選，也可不選）**：走路／跑步／跳躍／死亡。對應 `walk`／`run`／`jump`／`death`。跳躍是一項製作請求，交付上升、下落兩段，並保存共用空中基準；不要求使用者分別選兩段。
3. **角色基準大小（單選，可自訂）**：128×128／256×256（建議）／512×512，允許輸入其他正整數邊長。問題旁說明這是遊戲成品的角色尺度基準，不是來源影片解析度，也不是最終格子的固定尺寸。等待使用者回答，不能只告知預設便開始；使用者明確表示交由 Codex 決定時採 256×256。

問題旁明示：**每個所選姿態都會自動製作 Idle（待機動畫），不需勾選。未選其他動作時，只製作 Idle。** 不詢問 2D／2.5D 或方向；統一面朝右、正側視角，左向可在遊戲引擎鏡像。使用者明確要求不同方向時先說明目前預設與影響，不悄悄擴成多方向批次。

選中的姿態與動作取全部組合。例如兩種姿態與走路都選，清單包含一般 Idle、攻擊 Idle、一般走路、攻擊姿態走路。死亡、跳起等也不能因動作名稱自行省略其中一份。不因「攻擊姿態」額外加入攻擊招式、姿態轉換或未選動作。

將確認的角色基準邊長傳入計畫的 `--side` 並保存；同角色後續動作沿用，不重問。這是尺度基準，不限制最終裁切格子形狀。播放時間、格數等依現有動作處理指引，不逐題重新詢問已有設定。簡短列出製作清單及採用設定後開始；沿用既有參考圖的必要視覺確認，不為每個動作重複相同問答。

## 保存與執行

使用 `scripts/character_plan.py`，在使用者工作資料夾執行；此腳本只保存計畫，不提交 ComfyUI。每個工作資料夾只保存一個角色：

```text
python scripts/character_plan.py init --reference character.png --stances normal combat --actions walk run --side 256
python scripts/character_plan.py show
```

資料在 `work/character/plan.json`，記錄原始參考、方向、尺度、姿態素材及全部任務。初始化遇到既有計畫會拒絕覆蓋；讀取並沿用，不能刪除計畫來偷偷換角色。`--actions` 可省略；Idle 由程式自動加入。相同選項會去重。

1. 依[圖片預處理](image-processing.md)準備各姿態參考，建立共用尺度與站位，使用者確認外觀。
2. 優先完成各姿態 Idle：圖片參考不等於 Idle 動畫，必須生成呼吸、重心等適合姿態的待機動作影片，完成後段與視覺驗證。細微 Idle 可能低於現有自動選段的運動門檻；若回報 `needs_review`，檢視後以 `--start`、`--end` 指定可銜接的完整週期，不為通過選段而把待機動作誇大或將靜止影片列為成功。
3. 從該 Idle 來源影片選一張清楚、完整且符合待機架勢的影格作為後續影片輸入；保持來源演出畫布、角色尺度與站位。不把後段再次裁切過的最終小圖直接當成前段版面。必要時先透過圖片工作流清理此基準影格並保持畫布座標，這是前段參考準備，不對其他動作預先執行後段 Refine。
4. 保存姿態參考、該 Idle 輸入版面的 `preparation.json` 及可重用 Idle 影格：

```text
python scripts/character_plan.py record-stance --stance normal --reference outputs/normal-reference/standing.png --preparation outputs/normal-input/preparation.json --idle-frame work/character/normal-idle-frame.png
```

5. 依任務的 `depends_on`、`entry_reference`、`pipeline` 與 `vertical_alignment` 執行，不跨姿態套用。`idle`、`walk`、`run` 使用 `loop`；`death` 使用 `hold_end_pose`，完整定義見[影格表與預覽](spritesheet.md)。`jump` 使用[跳躍與空中處理](airborne.md)，由對應 Idle 生成完整來源，再分段；一般地面動作使用原有處理，空中動作使用已保存的空中基準。每項任務保存實際提示詞。
6. 任務進度以 `pending`、`running`、`needs_review`、`completed` 保存。提交前標示 `running`，失敗或需檢視時保存 `needs_review`；`completed` 須先符合[完成與交付驗證](spritesheet.md#完成與交付驗證)。不要為了通過依賴檢查提早標為完成。

```text
python scripts/character_plan.py mark --task normal-idle --status running
python scripts/character_plan.py mark --task normal-idle --status completed --artifacts work/normal-idle-artifacts.json
```

`--artifacts` 為 JSON：檔名使用絕對路徑或相對目前工作目錄，欄位名稱用小寫識別字；完成至少需要 `source_video`、`animation`，可另存 `prompt`、`input_image`、`zip`。例如 `{"source_video":"work/character/tasks/normal-idle/job/source.mp4","animation":"outputs/character/normal-idle/animation.json"}`，以實際產物路徑為準。

跳躍任務的完成記錄改為 `source_video`、`rise_animation`、`fall_animation`、`airborne_profile`，分別指向實際產物。另將空中基準登記至該姿態：

```text
python scripts/character_plan.py record-airborne --stance normal --profile outputs/character/normal-jump/airborne-reference/airborne-reference.json
```

`character_plan.py` 檢查任務依賴、必要記錄與提供的素材路徑是否存在；它不驗證影片或圖片品質，不判定所指檔案是否符合任務，也不確認使用者已能取得交付檔案。`mark --status completed` 是保存 Codex 已完成驗證的結論，不是啟動驗證的指令。記錄中的必要欄位不等於完整交付清單；Codex 仍須檢查 PNG、GIF、JSON、ZIP 及實際使用素材。

中斷後先 `show`，再查各既有工作流任務狀態，依原目錄接續；計畫的 `running` 不代表應重新提交。完成項目不重新生成。批次清單逐項執行並交付，不因完成第一個動作就結束整項任務。變更同名成品時建立新的獨立執行目錄並更新產物記錄，不覆寫已交付資料。

後段不讀取此計畫，只接收來源影片、統一縮回倍率、動作類型與必要處理參數；不因本流程要求既有影片使用者建立前段資料。打包各任務時依實際使用的來源列出上傳圖、姿態參考、Idle 基準影格、提示詞等，不固定假設自然站姿。

## 交付與建立新動作

交付清單按姿態／動作列出 PNG、無限重播 GIF、JSON 與 ZIP。本次要求全部完成後，結尾加上：**要替這個角色追加動畫，請輸入「建立新動作」。** 此入口屬於本對話角色。

收到指令後依序收集：**姿態（一般／攻擊，可複選）**、**動作環境（地面／空中，單選）**、**動作描述（自由文字）**。已在同則訊息明確提供的內容不重問；沒有明確環境時只補問該項，不以描述中的詞彙推測。使用者語言的同義要求也使用此入口。新姿態先補建 Idle，不重問整套首次清單；兩種姿態都選時，同一描述各做一份。

### 環境與結束行為分開判定

環境是使用者明確指定的任務條件；動作類型描述完成後的行為。兩者是獨立欄位，不由動作名稱互相推導。

| 環境 | 起始／起收基準 | 位移與處理 | 計畫路徑 |
| --- | --- | --- | --- |
| 地面 `ground` | 對應姿態的 Idle | 保留完整演出的垂直位移，使用一般選段、Refine 與拼表流程 | `pipeline=standard`、`entry_reference=idle`、`vertical_alignment=none` |
| 空中 `air` | 對應姿態已保存的空中基準 | 只交付空中動作本體；選幀後以腰部做垂直定位，位移由引擎控制 | `pipeline=airborne`、`entry_reference=airborne`、`vertical_alignment=waist` |

地面環境指動作的發動與銜接情境，不表示每格都必須接地。動作中即使離地或翻轉，仍保留完整演出與位移，不自行拆成空中片段、不套用腰部高度固定。明確選擇的環境優先於任何文字內容，不能以關鍵字、動作名稱或特定情境清單分流。若使用者的要求互相衝突，釐清衝突，不悄悄改環境。

再依[動作類型定義](spritesheet.md)判斷：`loop` 保留循環本體；`return_to_start` 完成一次動作後回到該環境的起始基準；`hold_end_pose` 停在目標結束姿態。地面的返回基準是對應 Idle，空中則是對應空中姿態，不強制回到地面。只有結束行為有歧義時才補問。後段的選幀策略與時間分配依該指引，不任意刪除中段停留或重設來源節奏。

對單次、可再次觸發的動作，未另指定結束要求時，以 `return_to_start` 規劃。描述已明確表達持續循環或保留目標結束狀態時，依其要求選擇類型。此處判斷的是結束行為，不改變已選環境，也不建立按動作名稱列舉的對照表。

```text
python scripts/character_plan.py add --stances normal combat --environment ground --description "使用者提供的動作描述" --motion-type return_to_start
```

程式為新增動作分配獨立編號，同次兩姿態使用相同動作編號。`--environment` 必填，腳本只保存描述，不讀取描述來決定處理路徑。選空中且缺少跳躍任務時，自動補入該姿態的跳躍依賴；其完成並登記空中基準後才能執行空中動作。選地面不會自動補跳躍依賴。檢查計畫後按依賴順序完成，交付後再次提供同一觸發指令。
