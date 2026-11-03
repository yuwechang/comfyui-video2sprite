# 環境與工作流對接

使用可用的 Python 3.10 以上執行 `scripts/setup.py check`。檢查摘要包含 Python、FFmpeg、ffprobe、套件與預設 ComfyUI 連線結果。

請使用者先啟動 ComfyUI。預設網址連不上時才詢問網址，以 `--url URL` 放在子命令前重新檢查。只處理缺少的依賴；套件清單位於 `requirements.txt`。

缺少 FFmpeg 或 ffprobe 時，說明本 Skill 依賴這兩個外部程式且不隨附，詢問是否協助安裝；同意後依使用者平台處理並重新檢查。Python 套件使用任務的 Python 環境，必要時建立本機虛擬環境，以該 Python 安裝套件並執行後續腳本。設定與輸出留在使用者工作資料夾，腳本與套件清單使用 Skill 安裝目錄的完整路徑。

依使用入口設定所需的 API 工作流：從角色圖片開始時對接影片生成與圖片處理；從影片開始時對接圖片處理。各自執行檢視，分別保存結果：

```text
python scripts/setup.py --url http://127.0.0.1:8188 inspect workflow.json --output .local/inspection.json
```

影片工作流：依節點連線與用途識別實際圖片輸入、正向提示詞、寬高、影片長度、種子及影片輸出；有第二張圖片時釐清用途與可省略方式，不為單圖工作流虛構第二個輸入。

圖片工作流：識別輸入圖片、編輯提示詞及可保存 PNG 的輸出。一般／攻擊姿態參考生成與逐張 Refine、去背重用相同設定；去背直接由圖片編輯提示詞要求，不以存在專用去背節點為前提。

節點與欄位存在不足以證明語意，先依連線與用途判讀，缺少必要資訊時詢問使用者。圖片處理能力按下述實測確認。

確認影片長度欄位使用秒或影格數、FPS 的來源、尺寸對齊值、影格數公式與合法範圍。工作流未表達的限制需另行確認。

確認後將對應寫入本機 JSON：`bindings` 內的 `image_1`、`positive_prompt`、`width`、`height`、`length`、`seed` 各為 `[{"node": "節點 ID", "input": "欄位名稱"}]`，有第二張輸入時另加 `image_2`，支援同一參數更新多處。若欄位是連線，追蹤至上游實際值欄位。另記錄 `output_node`、`image_2_mode`（第二張圖的用途及省略方式）與 `generation`。單圖工作流明確設定 `"image_2_mode": {"optional": true, "omit_inputs": []}`，不需 `image_2` binding；雙圖工作流允許省略第二張時，`omit_inputs` 列出工作副本需移除的節點輸入，例如 `[{"node": "12", "input": "last_frame"}]`。

若上游是運算節點，無法直接對應獨立數值，可在目標加入 `"mode": "replace_link"`，明確標記執行時在工作副本中將該輸入連線換成實際值。原始工作流保持不變。

`generation` 包含 `width_multiple`、`height_multiple`、`length_unit`（`frames` 或 `seconds`）、`fps`、`frame_step`、`frame_offset`、`frame_min`。合法影格數為 `frame_step * k + frame_offset` 且不小於 `frame_min`，k 為非負整數。這些值由實際工作流限制決定。另以 `max_pixels` 記錄本機生成畫布的像素預算，預設 1,000,000；預處理先依預算調整尺度，最後補齊尺寸倍數時允許少量超出。

執行以下命令驗證欄位並保存包含工作流的本機設定：

```text
python scripts/setup.py --url http://127.0.0.1:8188 bind workflow.json mapping.json --output .local/profile.json
```

設定驗證完成後，仍需實際生成確認影片可取得。此命令不提交生成任務。

圖片對應 JSON 的 `bindings` 只需 `image_1` 與 `positive_prompt`，格式同上；另指定 `output_node`。以圖片模式驗證與保存：

圖片工作流若有輸入尺寸倍數限制，在對應 JSON 加上 `input_alignment`，以 `width`、`height` 記錄各自倍數。後段逐張送入 Refine 與去背前，只在各張右側、底部補背景，處理後裁回原尺寸。

```text
python scripts/setup.py --url http://127.0.0.1:8188 bind image-workflow.json image-mapping.json --kind image --output .local/image-profile.json
```

圖片設定保存後，以現有完整角色圖片和[影格表與預覽](spritesheet.md)的 Refine、去特效與去背提示詞做實測，確認輸出可讀取、尺寸不變，且包含真正透明背景與有效角色內容；並檢視姿勢、尺度、位置及細節是否保留。PNG 副檔名、棋盤格外觀或僅存在 Alpha 通道都不足以證明去背成功。若未通過，先核對提示詞、輸出格式與實際結果，再針對缺少的工作流能力詢問使用者。

兩份本機設定包含使用者的工作流與對應，存於 `.local/`。
