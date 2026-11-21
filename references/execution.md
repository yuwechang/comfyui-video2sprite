# 執行計畫與資料流

## 職責與入口

更換影片工作流時，先用 setup.py inspect／bind 建立新的已驗證設定檔，再執行 `execution_plan.py --plan PLAN set-video-profile --file PROFILE`。此入口只切換後續 extend 建立任務使用的影片設定；不修改既有任務參數、已提交工作或成品。既有待執行任務若也需切換，使用 request 明確更新尚未開始的 video.profile，不更動已執行階段。欄位與模型檢查通過不等於實際生成已驗證，兩者分開回報。

正常製作一律使用 `scripts/execution_plan.py`：一個或多個動畫使用同一個任務迴圈，按依賴執行。Codex 只負責收集意圖、選擇參考與編寫提示詞、填入語意參數、檢視指定素材及作成有證據的判斷、向使用者交付。選段計算、取樣、裁切、定位、逐張工作流、Alpha、拼表、GIF、資料登錄及打包由隨 Skill 安裝的程式處理。

真人動作的姿態選幀使用[正式入口](pose-sampling.md)的 selection.sampling_method=pose 與 pose 模型設定；seconds=null 可由來源選段時長推導。run 直接接續整套算法，不讓 Codex 個別執行 benchmark、過渡研究、手搬 indices 或事後調格數。既有 Loop、跳躍與外觀取樣不受影響。

以下 `python` 代表已確認可用的直譯器；腳本路徑換成 Skill 安裝絕對路徑，工作目錄是使用者的工作資料夾。

新角色先依 [角色計畫](character-plan.md)集中收集設定並初始化，再建立執行計畫：

```text
python scripts/execution_plan.py --plan work/execution.json create --character-plan work/character/plan.json --workspace . --image-profile .local/image-profile.json --video-profile .local/profile.json
```

直接提供影片則省略前段及角色計畫：

```text
python scripts/execution_plan.py --plan work/execution.json create-video --video source.mp4 --workspace . --image-profile .local/image-profile.json
```

續接既有製作且需攜帶其實際參考／提示詞時，使用原計畫的 `export-materials --task TASK --output materials.json` 匯出已完成任務的登錄清單，再於 create-video 加 `--materials-file materials.json`；可提供多份，重複角色名稱或內容雜湊不符時拒絕匯入。此接點只傳明確素材資料，不要求後段理解前段計畫；純外部影片仍可不提供素材清單。不要掃資料夾重新收集或手改 assets。

產生的是 JSON 計畫範本，不會生成素材。初始姿勢預設 `pose_provider=gpt_image`，依[初始姿勢圖](pose-generation.md)先保存請求、呼叫圖像工具、匯入實際結果；計畫的 `pose_reference` 接點負責驗證紀錄與品質檢查，再接原有 geometry。使用者指定 ComfyUI 產生姿勢時，create 加 `--pose-provider comfyui`。填入尚未開始階段的資料：姿態參考 `image`、各階段 UTF-8 `prompt_file`、來源長度 `seconds`、成品播放長度、動作類型，以及跳躍的區間與腰部 ROI。`null` 表示待判斷，不能視為預設成功。首次姿態提示詞依 [前段提示詞](prompts.md)，Refine 依 [後段提示詞](spritesheet.md#共用影像編輯與版本提示詞)。各姿態使用相同角色尺度；後段省略 `max_side`，不按每個動作的寬高框重新縮放。

要保留初始圖的簡單背景與地面時，create 加 `--background-mode preserve`。程式直接建立 pose → layout，不加入透明 standing 編輯；用 request 填入 layout 的 subject_box、ground_anchor，bottom_ratio 預設 0.15。plain 模式使用透明參考的 standing 流程。extend 沿用計畫的背景模式，不手動刪改階段。多姿態共用尺度的 reference_geometry 由範本建立依賴；座標與 source_coordinate_scale 的用途見[圖片預處理](image-processing.md#保留原圖牆面與地面)。

## 一份請求設定未執行階段

正常填入語意資料使用 `python scripts/execution_plan.py --plan work/execution.json request --file work/request.json`。request 的 tasks 以任務 ID 對應階段 ID；parameters 只更新指定欄位並保留既有引用，prompts 由 Python 產生 UTF-8 檔案及 prompt_file，不手動複製整份 args。多個任務寫在同一 tasks 中，全部驗證通過才寫入。已執行或已產生結果的階段不能使用此入口覆寫。

回傳的 pending_inputs 彙整所有未完成階段仍缺少的必要欄位；這是資料完整性摘要，不代表實際檔案與模型能力已驗證。依摘要只補缺欄，不重新讀取或複製完整計畫。

```json
{"tasks":{"TASK":{"video":{"parameters":{"seconds":4},"prompts":{"prompt_file":{"template":"video_i2v","values":{"description":"依實際圖片與需求填完整演出、固定鏡頭及結束行為","soundscape":"符合演出的環境及物理聲音","music":"N/A"}}}},"finish":{"prompts":{"prompt_file":{"template":"refine","values":{"preserve":"需保持的身份、風格、實體裝備及關係","effects":"移除實際殘留的效果並保留角色細節"}}}}}}}
```

video_i2v 的 values 為 description/soundscape/music；refine 為 preserve/effects；pose 為 target/preserve/background，必須填齊，不保留未替換變數。模型需要其他格式時可提供 `{"text":"完整實際提示詞"}`。這是內容入口，不代替動作類型、環境與效果的判斷，也不自動改 CFG 或其他工作流設定。需調整已產生候選的階段，使用 configure 並給新 output/job；修正失敗影格使用 repair。

鏡頭補償使用 `python scripts/execution_plan.py --plan work/execution.json enable-camera --task TASK --regions-file work/regions.json`，由程式建立 selection → camera_alignment → finish 的引用與審查接點。只用於地面來源，須在 finish 執行前啟用，不手改階段陣列。

## 任務與階段資料

計畫含 `workspace`、共用 `assets`、`tasks`。每個 task 有唯一 `id`、`effect_type`（`none`／`impact`／`trail`）、`depends_on` 與有順序的 `steps`。`kind` 區分參考與動畫。每階段有唯一 `id`、正式 `operation`、`args`。範本保留已選姿態、起始基準、動作類型與依賴；不要依動作名稱另外分流。

前階段資料以具型別的引用傳遞，例如：

```json
{"selection_file":{"from":"normal-idle.selection","key":"selection_file"},"effects_present":{"from":"normal-idle.selection","key":"review.values.effects_present"}}
```

`from` 是 `task.stage`，`key` 是結果欄位路徑，陣列索引使用數字。只讀取已完成階段，不自行搜尋相似檔案。正式 operation：`camera_alignment`、`pose_reference`、`image`、`geometry`、`video`、`source`、`selection`、`jump_selection`、`finish`、`jump_finish`、`corrections`、`frames`、`package`。這些介面串接既有功能，前後段模組不讀取角色計畫；協調層透過明確輸出同步角色索引。

一般資料流為姿態 → 共用尺度及版面 → Idle 影片 → 來源概覽 → 選幀 → 檢查 → Refine／去背與成品 → 檢查 → 打包。Idle 完成後擷取已選的完整來源畫布作後續輸入；不使用裁切後的小格。跳躍的原始選幀先確認，之後才腰部定位、共同處理及切成兩段，共用切點只處理一次。空中動作引用已保存的空中基準。

`selection.args` 支援 `start`、`end`、`lead_start`、`count`、`quality` 等既有參數。需鎖定人工選擇時，填入遞增唯一的 `indices` 與對應 `frame_durations_ms`，不寫 Python 重組取樣。`hold_end_pose` 的明確索引也必須提供 A／B／D，包含 B、D，且 X／Y 時長符合來源比例預算，不能藉明確索引略過前段判斷。X/Y 判斷與取樣規則仍依後段指引。

外部算法已算出 indices、只需展示其原始結果時，非 hold_end_pose 可明確設 `source_timing=true` 並省略 frame_durations_ms，由來源 PTS 中點覆蓋分配指定總長，採同一 20ms 量化程式。此入口不重選、不補幀，並記錄 timing_assignment；它是診斷展示的時間基準，不代表已完成節奏層。不能與明確逐格時間或 X/Y 階段混用。

素材在使用或生成時登錄為 role、絕對路徑、內容雜湊、位元組數，包含共用參考、依賴階段實際使用的素材、提示詞及各階段結果。打包直接消費登錄資料與成品報告，不掃描目錄、猜路徑或到最後重新蒐集。

## 執行與等待

```text
python scripts/execution_plan.py --plan work/execution.json run
python scripts/execution_plan.py --plan work/execution.json status
```

`run` 在本機依序執行，直到完成或需要設定／檢查；獨立任務可前進，有依賴者等待。狀態存在 `work/execution-plan/<計畫檔名>/state.json`；原命令重跑接續原狀態，完成階段核對輸入與輸出雜湊，不重新提交。輸入改變不能沿用舊任務目錄。工作流程式已負責提交、WebSocket 等待與必要 history 補查；Codex 不再同時輪詢 ComfyUI、佇列及成品。

工具回報背景程序時，只等待該程序；每次等待至工具允許且不超過 60 秒的上限，沒有新狀態就續等。不要每幾秒發出新查詢，也不要反覆讀完整日誌、JSON 或文件。以精簡完成／檢查／錯誤摘要決定下一步。中斷時沿用相同計畫與 job，不能因沒有即時畫面而重建任務。

Python 的 generate.wait_for_result 是影片及影像工作流共用的阻塞等待入口：同一次呼叫內處理 WebSocket 完成事件、遺漏事件的 history 補查、斷線後 history 輪詢及暫時連線錯誤；只有完成、工作流執行錯誤或逾時才返回，不印輪詢進度。history 補查間隔為連線正常時 60 秒、無 WebSocket 時 15 秒，均由 Python 計時；完成事件可立即提早結束等待。job.json 的 wait 保存實際查詢數、事件數、傳輸方式與逾時資料；逾時不取消或重新提交原 prompt_id，同 job 可接續。這些數字是本機傳輸策略，不是 Codex 應查詢 ComfyUI 的頻率。

執行工具可能將仍在運作的 Python 轉成背景程序，這不是 Python 要求 Codex 輪詢 ComfyUI。只使用工具提供的程序完成等待或完成通知接收結果；工具必須分段等待時，指定同一 session_id 並使用可用的長等待，外層 cell_id 則只接收同一 cell。這層工具限制不能由 Skill 的 Python 強制消除，也不代表需要再次呼叫 run、查佇列或掃描檔案。進度訊息只說明新結果、阻礙或下一個檢查目的，不反覆報告仍在等待。

參數不足時，先根據既有資料判斷，準備完整該階段 args JSON，再用正式命令更新：

```text
python scripts/execution_plan.py --plan work/execution.json configure --task TASK --stage STAGE --file work/stage-args.json
```

已執行階段變更參數需新的 job／output 目錄；完成階段不直接改寫，建立新的任務／階段。不能把原本失敗輸出當成新設定的結果。

## 檢查接點與版本分流

使用者要求查看未通過或待檢查的選幀結果時，可用 `execution_plan.py --plan PLAN preview-selection --task TASK --stage selection --output diagnostic.gif`。此入口直接以已保存的 selected_frames 與 frame_durations_ms 產生無限重播診斷 GIF，保留原始畫布與背景，不重選、不去背、不改 review 或任務狀態；須說明這是測試結果而非合格成品。它不是每次執行的固定步驟，也不能用假通過的 review 代替診斷展示。

選幀檢查的 values 同時保存 effects_present 與 refine_required 布林值。來源清楚、無需修復或去除人物上的效果時，refine_required=false，直接由專用遮罩去背；有重疊特效、色彩污染或需修復的模糊時才為 true。這是實際選幀的觀察判斷，不能只依有無特效名稱決定。finish／jump_finish 接收 refine_required；略過時必須提供 background_profile，成品記錄 image_edit_performed=false，不冒稱執行過影像編輯。Refine 後重新計算 Alpha，不套用原輪廓遮罩。

需要補充已明確取得的實際素材時，用 `declare-materials --task TASK --file MATERIALS_JSON` 登錄角色名稱到檔案絕對路徑的對應；不掃描目錄。只允許未完成任務，不可覆寫既有角色名稱。影片設定、實際提交的工作流與任務紀錄可透過此入口保存；打包驗證這些明確登錄的素材。影格分析自動登錄原尺寸遮罩與來源索引對照。

檢查先讀 diagnostic.checks 的數值摘要，再直接讀取已存在的影格表、選中影格、原圖或遮罩。pictures 與 detail_pictures 指向既有檔案，不預設製作額外總覽、比較圖、審查 GIF 或截圖；有具體疑點才補讀相關原檔，不逐幀交給 Codex 判讀整支影片。只有既有檔案與數值不足以釐清具體問題時，才產生最少必要的輔助素材或使用額外檢查工具，先說明它要解決的疑點；同一種輔助檢查不因某次有用就成為所有動作的固定步驟。正常選幀、遮罩與成品所需檔案仍由正式程式產生，這項節制針對額外審查成本，不是禁止必要處理。Refine 的數值比較仍扣除已記錄補邊，提供疑似位移、尺度與輪廓異常的來源索引；未標示不等於視覺通過。

幾何階段只有在輸入引用已通過姿態檢查的上游，或繼承該檢查的已驗證幾何結果，且輸出逐像素符合宣告的等比例縮放及定位時，才以 `geometry-check.json` 的機械證據自動完成。這不生成視覺 pass，也不略過初始姿態檢查。輸入需要影像編輯、缺乏已審核來源或幾何比對不符時，保留原人工檢查接點。

`

正常流程不啟動瀏覽器或播放審查伺服器，也不要求播放計時、表單或 playback_record。review 依既有檔案、逐格時間與機械檢查接受具體的視覺判斷；靜態檢查只能說明姿態、覆蓋、順序、起收與可見瑕疵，不能冒稱已觀看連續播放或已證明主觀流暢度。GIF 維持無限重播，數值檢查負責驗證逐格時間、影格順序及重播設定。

處理期間只用簡短文字回報目前階段與新發現，將圖檔讀取放在背景，不在聊天展示中間審查素材。最終交付依下方順序嵌入媒體與提供下載連結。

必須實際對照來源、對應姿態及先前合格成品檢查身體尺度；頭髮、武器、倒地後的寬高框不等於身高。相同縮回倍率只保證座標換算，不保證生成模型未改變身體比例。不得以檔案存在、Alpha 範圍或固定文字代替此項視覺結論。

檢查 JSON 的 `items` 必須與 request 的 `required_items` 完全相符，每項具 `status`（`pass`／`fail`／`pending`）、具體 `reason`、實際已檢視檔案的 `evidence` 路徑。必要項目不可 `n/a`。選幀檢查另存實際 `values.effects_present` 布林值，不能只由動作名稱或生成意圖推測。範例僅示意單個項目結構，須填全 request 要求：

```json
{"items":{"effects":{"status":"pass","reason":"依選中來源觀察到的具體結果填寫","evidence":"絕對路徑/selection.png"}},"values":{"effects_present":false}}
```

```text
python scripts/execution_plan.py --plan work/execution.json review --task TASK --stage STAGE --decision work/review.json
python scripts/execution_plan.py --plan work/execution.json run
```

檢查未通過時停在該階段，不會打包或解除依賴。沒有實際檢視的項目保留 pending，不預寫全 pass。程式檢查像素、透明、時間、GIF 無限重播及封存完整性；Codex 判斷意圖、動作、身份、尺度、遮擋與特效品質。兩者皆通過才完成任務。

`hold_end_pose` 的 X／Y 必須在選幀階段確定：檢視主要動作之前的候選，有演出則填 `lead_start=A`，沒有則填 `lead_start=B`，以 configure 保存實際參數並重新執行選幀。`sampling.lead_review_required=true` 時 review 不接受通過，不能在未確認 X 的情況下進入 Refine。這是所有保持結束姿態任務的共用接點。

一般、空中與跳躍後處理統一輸出單一 clean 版本。effects_present 記錄選中來源的實際狀況；能由 Alpha 排除的效果可直接去背。需 Refine 時在 finish 或 jump_finish 提供一份包含移除與角色保留要求的 prompt_file，完成後重新計算 Alpha。

## 針對未通過影格補救

依 [去特效兩關](spritesheet.md)診斷具體殘留與位置，在失敗 review 中填 `failed_frames`，例如 `{"clean":[61]}`。為列出的來源索引準備精準完整提示詞，修正規格檔格式：

```json
{"clean":{"61":{"prompt_file":"corrections/61.txt"}}}
```

```text
python scripts/execution_plan.py --plan work/execution.json repair --task TASK --stage finish --file work/repair.json --attempt fix-1
```

只重送指定的未通過原始處理輸入，重用其他合格結果；共用程式重建裁切、成品及跳躍兩段，再回到檢查。中斷修正沿用同一 attempt；新修正使用新的 attempt 與具體修正依據。空中腰部匹配有誤時使用既有 `overrides` 資料介面。必要檢查未通過時保留該階段的待修正狀態，修正後重新檢查，通過才接續後續階段。

## 文件接續、追加及交付

首次讀入口與 execution，按當前階段讀設定、角色計畫、圖片、提示詞、生成、後段或空中指引；讀過且上下文仍可用時不重讀全文。可登錄讀取雜湊：

```text
python scripts/execution_plan.py --plan work/execution.json documents INSTALL/SKILL.md INSTALL/references/execution.md --record-read
```

不帶 `--record-read` 只查新／變更。登錄不代表記得內容：上下文遺失時，先讀 `status`、當前 request 及對應指引必要章節；不從頭重跑或重讀全部文件。文件變更只補讀變更相關部分。

計畫建立後讀執行指引優先用 `documents PATH --show --section "完整章節標題"`，只輸出該章節並登錄其內容雜湊；再次呼叫未變章節只回 already_read。輸出預算預設 10000 字元，超出會要求縮小範圍且不登錄為已讀，避免工具截斷後繼續重讀。無章節參數才讀全檔。上下文遺失確實需重讀時加 --refresh；不是每輪固定加入。入口與尚無計畫時可直接讀檔，之後沿用已取得內容。

完成 run 直接回傳 deliveries，含 ZIP 路徑、CRC、封存清單一致性、版本、影格及提示詞數量；`delivery` 命令可重取已保存摘要，不重新打包或列出所有 ZIP 成員。依此摘要及已完成視覺審查交付，僅有具體缺件疑點時才展開相關封存明細。摘要中的 materials 是已登錄素材數，不代表程式已辨識每份素材的語意正確。

package 依已完成階段的實際輸入與姿態來源鏈產生 required_materials，核對必需角色、封存路徑及內容雜湊；素材不存在、未登錄或使用後改變時停止打包。直接影片後段不要求角色參考；從角色圖開始則必須保留實際參考及提示詞。這是資料流契約，不靠臨交付掃資料夾猜測缺件。

ZIP 收錄 BiRefNet 去背後的透明角色影格。選幀分析、參考幀背景處理及成品去背使用的獨立 Alpha 遮罩留在工作目錄。

新建地面 `return_to_start` 任務的 selection 預設 `seconds=1` 與 `playback_fps=25`。成品 `animation.json` 的 `playback.sequence` 是從 0 開始的影格表格號，每個項目佔一拍。程式保留主要姿勢，在所屬的來源時間區間內挑選補幀，並由序列產生 GIF 的逐格時間。若主要姿勢數已超過拍數，程式會延長播放至能容納全部主要姿勢。

新增動作先用 `character_plan.py add` 保存需求，再追加新任務；已存在任務的設定與狀態保留：

```text
python scripts/execution_plan.py --plan work/execution.json extend --character-plan work/character/plan.json
```

協調層隨階段寫回角色的參考、版面、Idle／空中基準與任務狀態，並在完成檢查與打包後登錄完成。素材包收錄本次動作實際使用的參考圖、姿態及影片輸入圖、提示詞、來源影片、全部來源影格、選中影格、透明成品影格、GIF 與影格表。

在聊天中依下列順序交付本次要求的動作：

1. 直接嵌入來源影片原檔，讓使用者在聊天中播放。
2. 直接嵌入GIF 預覽。
3. 在 GIF 下方直接嵌入 Sprite Sheet 圖片。
4. 最後提供素材 ZIP 的下載連結。

ZIP 交付後提示可直接說「再來我想要產生 XXX 動作」。

聊天展示前執行正式展示入口：

```text
python scripts/execution_plan.py --plan work/execution.json display --output outputs/chat-display
```

程式直接讀已完成階段的成品摘要，產生 `chat.md`、`index.html`、`display.json` 及聊天用 GIF。同批動畫使用共同大小的透明畫布；每張影格只按固定位置補邊，不縮放或逐幀重新定位。同一動作的有／無特效版依錨點對齊，不同動作的整組畫布居中放入共同展示畫布。所有 GIF 寬高相同，避免聊天欄位因長寬比不同而各自縮放。HTML 使用固定像素尺寸，不把每張圖片分別適應欄位寬度；窄視窗可水平捲動。

交付時使用 `chat.md` 中的聊天用 GIF 路徑並列展示，再展示原始影格表與素材 ZIP；展示檔不取代原始交付檔。程式保留逐格時間、無限重播與像素比例，且要求同批 `delivery_scale` 相同；倍率不同時須先確認尺度設定，不用補邊掩蓋內容已縮放的差異。這只修正展示方式，不修正來源影片的身體比例。

已有完整角色計畫或只有成品摘要時，也可直接使用共用展示程式：

```text
python scripts/display_previews.py --character-plan work/character/plan.json --output outputs/chat-display
python scripts/display_previews.py --manifest work/display-inputs.json --output outputs/chat-display
```

manifest 格式為 `{"animations":[{"id":"唯一識別字","label":"展示名稱","summary":"variants.json 的實際路徑"}]}`；相對 summary 路徑依 manifest 位置解析。不掃描資料夾猜成品，輸出使用新目錄。

選幀後的背景鏡頭補償接點、輸入區域格式與檢查條件見[背景鏡頭補償](camera-alignment.md)，只有確認需要時插入，不為所有動作增加檢查階段。
