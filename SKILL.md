---
name: comfyui-video2sprite
description: 使用本機 ComfyUI 將角色圖片與動作描述製作成動畫影格表及 GIF；首次使用時檢查環境並對接 API 工作流。
---

# ComfyUI Video to Sprite

需要使用者選擇或確認時，優先使用可用的 UI 問答工具，允許文字補充；圖片仍在對話中展示。工具不可用時，以一般文字詢問。

`scripts/`、`references/` 與 `requirements.txt` 以本 Skill 安裝目錄解析；執行腳本時使用其完整路徑，以使用者工作資料夾為工作目錄，將 `.local/`、`work/`、`outputs/` 留在該處。指引中的相對腳本路徑依此換算。

首次使用或環境變更時，讀取 [環境與工作流對接](references/setup.md)。

使用者要求安裝或更新時，讀取 [安裝與更新](references/install.md)，由 Codex 執行下載、安裝與依賴檢查。

使用者提供影片時，檢視並選取動作區間，直接讀取 [影格表與預覽](references/spritesheet.md)。

準備影片輸入圖片時，讀取 [圖片預處理](references/image-processing.md)，建立使用者確認的自然站立參考、固定站位與演出版面，保留縮回倍率。直接以站立版面生成動作；再讀取 [影片生成](references/generation.md)。

取得影片後，判斷動作屬於連續循環、非連續循環或不可循環，再讀取 [影格表與預覽](references/spritesheet.md)，由 Python 自動選段及等距取樣，以明確的統一縮放倍率完成處理與交付；判定不明確時才由 Codex 檢視指定區間。多個動作分別建立任務目錄與成品。
