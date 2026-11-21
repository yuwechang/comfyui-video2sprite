# 真人動作的正式姿態選幀

適用可由 Pose Landmarker 穩定追蹤的真人 CFR 影片，以及 return_to_start／hold_end_pose。Loop、跳躍分段、非真人或 VFR 尚未經本入口驗證，不自動切入、不在失敗時靜默換算法。外觀法仍由 sampling_method 明確選擇，研究比較見 pose-method-benchmark.md；正常製作不要逐個呼叫研究腳本或手搬索引。

## 環境與一次請求

在可用的 Python 環境安裝 requirements-pose.txt；需要隔離時建立獨立環境，pose.python 指向該環境的 Python。使用官方 Pose Landmarker Full task：
https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task

模型及環境放工作資料夾或使用者的模型目錄，不寫入技能，也不硬編開發機路徑。已存在時核對可讀取後重用；未經使用者授權不安裝套件或下載模型。前景使用技能的 BiRefNet Alpha 工作流，設定方式見 setup.md。

未執行的 selection 以正式 request 設定：

```json
{"tasks":{"TASK":{"selection":{"parameters":{"sampling_method":"pose","seconds":null,"pose":{"model":"ABSOLUTE_POSE_TASK_PATH","python":"ABSOLUTE_PYTHON_PATH"},"foreground":{"profile":"ABSOLUTE_ALPHA_PROFILE","job":"UNIQUE_ANALYSIS_JOB"}}}}}}
```

python 可省略，代表執行技能的環境。seconds=null 時，Python 依自動選段的來源 PTS 算出播放時長；明確指定時長則依同一預算縮放。不要指定 count、indices 或 frame_durations_ms 來幫算法通過。沿用同角色已驗證的環境與模型設定。

## Python 負責的完整流程

execution_plan run 內一次完成 Alpha、來源選段、主要姿態、節奏補幀、來源影格擷取及時間表，不由 Codex 串接研究命令。return_to_start 逐段擇優；hold_end_pose 保留多個主要階段直到收招，不只取活動最大的末段。A/B/D 與 X 的定義見 spritesheet.md；X 仍使用既有細微動態取樣，姿態算法只作用在 Y，不改變 X 的格數規則或時間預算。

主要姿態用遞迴最大重建誤差，依誤差改善與複雜度曲線轉折自動停止；主要格固定後，再用依來源時間加權的停格誤差收益，計算過渡格及逐格時間。沒有固定格數、手選保護姿態或逐影片門檻。來源時間以共用 20ms 格點分配，GIF 無限重播。

visibility 低於 0.5 的關節不採信座標。比較只用共同可見關節，缺失部分由同一區間的原始人物 RGB／Alpha 誤差補充；不以遮擋的肢體數量拒絕整段，也不把無共同關節算成零變化。共用畫布範圍，不逐幀對齊或放大，不補造隱藏姿勢。高信心錯誤、錯誤 Alpha 或完全不可見的動作仍可能影響品質；數值完成不代替動作與裝備檢查。

pose-analysis 保存來源、模型、Alpha、演算法與時間契約，及主要格、補幀、低可信格、影像證據和時間表。中斷可重用同一份工作；輸入或程式內容改變則使用新 output。只讓 Python 等待子程序，Codex 不輪詢工作流。輸入不完整、證據缺失或環境不支援時明確停止，不悄悄降門檻或換算法。

## 審查

先讀取 selection 的 sample_indices、sampling.major_indices、added_indices、phases 與逐格時間，再直接看已有來源／輸出。只在具體疑點時增加最少的輔助檢查。需要觀看待審結果時用 preview-selection，不假造通過紀錄。檢查主要階段、過渡、節奏、起收、手腳與裝備連接；正式審查通過後才接續 Refine／去背與打包。
