# 初始姿勢圖

初始靜態姿勢預設由可用的 GPT Image 圖像工具產生；影片及所選影格的 Refine、去背與效果處理仍由本機 ComfyUI 執行。使用者明確指定其他提供者時遵從其要求。工具不可用時說明並確認可用方案，不悄悄改用其他模型。

自然與戰鬥站姿均可直接從角色參考圖產生，不強制先建立另一種姿態。只選戰鬥姿態不額外製作自然 Idle。一般站姿面朝右、90度側視、雙臂自然垂下；戰鬥站姿依目標支撐與防守關係建立，頭部及視線朝右、軀幹可斜側。兩腳接觸同一水平地面，原角色媒材風格、身份、服裝及裝備保留；真人未要求轉風格時保持真人質感。

先使用角色圖加文字；需要指定關節配置或文字調整仍不準時，才考慮姿勢模板，模板不取代角色體型與比例。目前正式登錄入口支援單張參考；多圖需先有完整多圖資料接點，不把未登錄圖片混入正常製作。

## 提示詞及正式登錄

提示詞骨架：將參考角色改成【目標站姿、支撐及肢體關係】；頭部及視線朝右，【自然站姿的側視／戰鬥姿態的軀幹角度】；保留身份、體型、服裝、配件與原媒材風格；完整全身、貼近人物構圖且只留小邊距。透明參考要求真正透明背景；保留地面模式則要求簡單牆面與明顯地面、接觸陰影，不同時要求透明背景。演出留白由後續 Python 建立，不在此要求寬幅或左右充足留白。欄位依當前可見內容填寫，不加入影片動作或後段效果處理。

初始姿態使用計畫的 prepare-pose 入口；一份 JSON 提供 reference 與 prompt。prompt 可用 pose 模板的 target、preserve、background，或提供完整 text。Python 寫入實際提示詞與請求，必須在呼叫圖像工具之前完成：

```text
python scripts/execution_plan.py --plan work/execution.json prepare-pose --task REFERENCE_TASK --file work/pose-request.json
```

```json
{"reference":"character.png","prompt":{"template":"pose","values":{"target":"實際目標站姿、朝向及支撐關係","preserve":"身份、比例、服裝配件與原風格","background":"所選的透明或簡單地面背景"}}}
```

使用回傳的 reference 與 prompt_text，透過 GPT Image 工具生成同一份實際提示詞要求的姿勢；透明背景使用工具的透明輸出選項。將工具回傳的實際本機產物登錄，不猜檔名：

```text
python scripts/pose_reference.py accept --job work/character/references/combat/pose --image ACTUAL_OUTPUT.png
```

`accept` 保存圖片、實際輸入、提示詞及雜湊，不代表視覺合格。計畫預設的 `pose_reference` 階段讀取 `manifest.json`，要求姿態、身份、身體尺度與背景檢查，通過才接入既有 geometry。所有素材經資料流傳至 ZIP，不在交付時重新蒐集或補寫提示詞。

局部修正只改有問題的部分。以新 job 呼叫 prepare，加 `--previous PREVIOUS_MANIFEST.json`，其 reference 必須為前次登錄的輸出；再呼叫工具、accept，使用 configure 的 `--file` 指向 accept 回傳的 `stage_args`，將未完成的 pose 階段改指向新 manifest。已完成階段以新任務處理。使用者另傳的處理圖視為新輸入，不能冒充前次產物。眼神錯誤先改眼神，不自動轉動頭部或重做全身。各次實際輸入及提示詞均由登錄保留。

完成後檢查頭部與視線分別朝向、姿態、關節、接地、身份、風格及完整性；背景按所選模式檢查透明或簡單地面，再依圖片預處理建立尺度與版面，展示姿勢供使用者確認。

使用者指定 ComfyUI 產生初始姿勢時，create 加 `--pose-provider comfyui`，沿用 image 階段及 process_image.py；不影響後段影格工作流。
