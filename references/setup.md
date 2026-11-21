# 環境與工作流對接

## 成品專用去背

Refine／去特效之後，使用 Skill 內建的 assets/workflows/birefnet-alpha.json：BiRefNet → GrowMask → MaskToImage → SaveImage；取得原尺寸遮罩後由 Python 合併原圖與 Alpha；不包含裁切、縮放或生成式節點。GrowMask 預設 -1，可依原尺寸邊緣檢查調整；不能假設所有素材的一像素內縮都不損失細節。此設定與選段分析用的 Python 模型相互獨立。

使用者不需要自行提供去背工作流 JSON。確認 ComfyUI 安裝背景移除節點與 birefnet.safetensors 模型後，執行 `python scripts/background_removal.py configure --url URL --model MODEL_FILENAME --grow-mask -1 --output .local/background-profile.json`。configure 載入隨 Skill 安裝的固定模板，依本機節點公布的模型清單驗證名稱，在任務目錄建立設定副本；不硬編使用者電腦路徑。直接測試用 `background_removal.py run --profile PROFILE --image IMAGE --job JOB`。逐張共用 process_image 的等待、錯誤與接續機制，不額外查詢佇列。

execution 的 finish／jump_finish 使用 background_profile，建立計畫時預填 .local/background-profile.json；使用 request 可改成已驗證設定路徑。程式在影像編輯後套用專用去背，檢查輸入輸出尺寸及 RGB 完全相同，僅 Alpha 改變。保存去背前圖、工作紀錄及設定供檢查與打包；更換設定使用新任務目錄，不覆寫已驗收成品。圖像工作流不必輸出 Alpha，最終 Alpha 由專用去背提供。白色為前景、黑色為背景，遮罩不反轉、不重複套用 GrowMask；Python 合併保持灰階透明度。

保留特效版需另外確認遮罩沒有移除要保留的光暈、尾跡與半透明效果；人物模型可能排除這些內容，不能因尺寸、RGB 檢查通過就判定特效保留合格。GrowMask 與低 Alpha 清理皆須依實際輸出檢查細節。

## 選段分析用的本機人物遮罩

正常選段使用內建 Alpha 設定，foreground 傳入 profile（設定檔絕對路徑）與 job（獨立工作目錄）。程式逐張取得原尺寸遮罩後再縮小分析特徵，保存來源索引、遮罩與工作紀錄；不在縮小圖上先做一像素內縮。Refine 改變輪廓後須重算成品遮罩，不套用舊遮罩。下面 Python 直接執行 ONNX 的方式只供明確要求獨立模型執行時使用，正常流程不需要另裝 rembg。

測試只有圖片輸入、沒有文字輸入的 ComfyUI 遮罩工作流時，process_image.py 可省略 --prompt-file；profile 只設定實際存在的 image_1 binding 與 output_node，不建立假的提示詞欄位。比對原尺寸遮罩時，輸出遮罩轉圖節點，不以裁切、縮放後的展示圖評估站位或輪廓。

模型遮罩由獨立 Python 執行，不透過 ComfyUI，不修改來源影片或替代最終成品的 Refine。使用已確認的 Python 3.11 以上建立任務虛擬環境後，以該環境的 Python 執行 `-m pip install -r requirements-segmentation.txt`；此清單包含 rembg、ONNX Runtime GPU 及 CUDA/cuDNN 執行套件。首次使用 BiRefNet 會下載權重至明確指定的 model_dir，後續重用；不要寫入 Skill 安裝目錄。GPU 模式需要相容的 NVIDIA 顯示卡與驅動，並明確提供 gpu_memory_mb 作為 CUDA 記憶體池預算；依可用顯存與模型實測設定，不以自動吃滿顯存或無限制配置作為預設。預算不足會報錯，不悄悄降低遮罩品質或改用 CPU。CPU 模式必須明確選擇，不自動降級。

以 `scripts/subject_mask.py IMAGE --output OUTPUT --model-dir MODEL_DIR --device cuda --gpu-memory-mb MEMORY_MB` 測試實際圖片；預設使用通用 birefnet-general，以涵蓋不同角色風格。輸出 mask.png、cutout.png、comparison.png 及 result.json，紀錄模型雜湊、啟用的運算提供者、記憶體預算與推論時間。檢查人物全身、腳部與背景交界；有遮罩閃爍或刪除人物時不能當作選段成功。相同 Python 環境須另外安裝一般 requirements.txt，才能執行完整任務。

選段階段的 foreground 需包含 CUDA 的 gpu_memory_mb 預算，並可明確傳入 `{ "model_dir": "模型目錄絕對路徑", "device": "cuda", "model": "birefnet-general" }`。自動選段在縮小分析圖之前計算模型遮罩，逐張遮罩保存在 selection 輸出的 analysis-masks；不手工修改影格或以手選區間掩蓋遮罩失敗。獨立命令 `select_segment.py VIDEO --motion-type loop --foreground-profile PROFILE_JSON --mask-output OUTPUT --output RESULT_JSON` 使用相同實作。沒有傳入 foreground 時仍使用簡單背景分析，不能宣稱該次使用了模型。

先確認本次使用者工作資料夾：已明確指定或已建立的沿用，只在未知時詢問。以實際路徑告知素材與成品將保存的位置，不把 Skill 安裝目錄當成任務目錄。已有本機連線及工作流設定時先讀取、檢查並沿用，只補問缺少或失效的資訊，不要求使用者重新填寫整套設定。

使用可用的 Python 3.10 以上執行 `scripts/setup.py check`。檢查摘要包含 Python、FFmpeg、ffprobe、套件與預設 ComfyUI 連線結果。

請使用者先啟動 ComfyUI。預設網址連不上時才詢問網址，以 `--url URL` 放在子命令前重新檢查。只處理缺少的依賴；套件清單位於 `requirements.txt`。

缺少 FFmpeg 或 ffprobe 時，說明本 Skill 依賴這兩個外部程式且不隨附，詢問是否協助安裝；同意後依使用者平台處理並重新檢查。Python 套件使用任務的 Python 環境，必要時建立本機虛擬環境，以該 Python 安裝套件並執行後續腳本。設定與輸出留在使用者工作資料夾，腳本與套件清單使用 Skill 安裝目錄的完整路徑。

依使用入口設定所需的 API 工作流：從角色圖片開始時對接影片生成與圖片處理；從影片開始時對接圖片處理。各自執行檢視，分別保存結果：

```text
python scripts/setup.py --url http://127.0.0.1:8188 inspect workflow.json --output .local/inspection.json
```

影片工作流：依節點連線與用途識別實際圖片輸入、正向提示詞、寬高、影片長度、種子及影片輸出；有第二張圖片時釐清用途與可省略方式，不為單圖工作流虛構第二個輸入。

圖片工作流：識別輸入圖片、編輯提示詞及可保存 PNG 的輸出，供逐張 Refine 與去特效使用。初始姿態預設由 GPT Image 準備；只有使用者選擇 ComfyUI 產生姿態時才重用此圖片設定。成品去背使用獨立 BiRefNet 遮罩工作流，依下節設定；不由生成式提示詞去背。

節點與欄位存在不足以證明語意，先依連線與用途判讀，缺少必要資訊時詢問使用者。圖片處理能力按下述實測確認。

確認影片長度欄位使用秒或影格數、FPS 的來源、尺寸對齊值、影格數公式與合法範圍。工作流未表達的限制需另行確認。

確認後將對應寫入本機 JSON：`bindings` 內的 `image_1`、`positive_prompt`、`width`、`height`、`length`、`seed` 各為 `[{"node": "節點 ID", "input": "欄位名稱"}]`，有第二張輸入時另加 `image_2`，支援同一參數更新多處。若欄位是連線，追蹤至上游實際值欄位。另記錄 `output_node`、`image_2_mode`（第二張圖的用途及省略方式）與 `generation`。單圖工作流明確設定 `"image_2_mode": {"optional": true, "omit_inputs": []}`，不需 `image_2` binding；雙圖工作流允許省略第二張時，`omit_inputs` 列出工作副本需移除的節點輸入，例如 `[{"node": "12", "input": "last_frame"}]`。

若上游是運算節點，無法直接對應獨立數值，可在目標加入 `"mode": "replace_link"`，明確標記執行時在工作副本中將該輸入連線換成實際值。原始工作流保持不變。

多圖參考可依順序增加 image_3、image_4 等 binding。正式 video 階段用 image、image2 及 extra_images 陣列依序傳入；generate.py 命令列使用 --extra-images。程式逐圖上傳、核對所有已綁定參考圖均有提供，並把額外參考的內容雜湊納入任務契約。不要留下工作流樣本圖假裝已提供參考。這些欄位只控制實際媒體連接，參考用途、順序與時序仍須依模型格式寫入提示詞；參考圖片不等於硬性首中尾關鍵幀。

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

圖片設定保存後，以現有完整角色圖片和[影格表與預覽](spritesheet.md)的 Refine、去特效提示詞與獨立去背設定做串接實測，確認輸出可讀取、尺寸不變，且包含真正透明背景與有效角色內容；並檢視姿勢、尺度、位置及細節是否保留。PNG 副檔名、棋盤格外觀或僅存在 Alpha 通道都不足以證明去背成功。若未通過，先核對提示詞、輸出格式與實際結果，再針對缺少的工作流能力詢問使用者。

兩份本機設定包含使用者的工作流與對應，存於 `.local/`。
