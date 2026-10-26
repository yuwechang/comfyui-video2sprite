# ComfyUI Video to Sprite

供 Codex 使用的角色動畫 Skill。上傳角色圖片、描述動作，即可透過本機 ComfyUI 製作透明背景動畫影格表及 GIF 預覽；也能提供已生成的影片，接續選幀與交付處理。

Codex 負責理解需求、準備提示詞與檢視結果；本機 Python 負責版面、縮放、等待任務、選幀、裁切、拼接及檢查；ComfyUI 負責圖片處理與影片生成。

<table>
  <tr><th align="center">角色參考圖</th><th align="center">走路循環成品</th></tr>
  <tr>
    <td align="center"><img src="examples/right-profile-walk/images/character-reference.png" alt="上傳的角色參考圖" height="270"></td>
    <td align="center"><img src="examples/right-profile-walk/result/preview.gif" alt="透明背景走路循環" height="249"><br>8 格 · 0.8 秒 · 透明背景</td>
  </tr>
</table>

**[查看完整製作過程與下載範例素材 →](examples/right-profile-walk/README.md)**

從自然站立參考、動作首幀、灰底影片到透明影格表，逐階段展示實際成果與素材重用方式。

## 複製這句話給 Codex

將下面整段貼給 Codex：

```text
請幫我安裝這個 Codex Skill：https://github.com/yuwechang/comfyui-video2sprite 。請依儲存庫的安裝指引完成安裝與環境檢查，缺少必要資訊時再詢問我。
```

Codex 會依 [安裝與更新指引](references/install.md) 下載安裝、檢查 Python 套件與 FFmpeg／ffprobe。缺少外部程式時，會詢問是否協助安裝。你不需要手動複製資料夾、設定安裝路徑或操作 Python。

## 你需要準備的東西

- 可存取本機檔案及 ComfyUI 的 Codex 環境。
- 已能正常執行的 ComfyUI、模型與節點；使用前先啟動 ComfyUI。
- API 格式的工作流 JSON：影片生成與圖片處理各一份。只處理既有影片時，先提供圖片工作流即可。

Skill 不隨附模型、節點、FFmpeg 或 ffprobe。環境與套件檢查交由 Codex 處理，只補上缺少的項目。

## 第一次使用

告訴 Codex 要把素材與成品放在哪個工作資料夾，提供工作流 JSON。它會先測試預設 ComfyUI 網址 `http://127.0.0.1:8188`；連不上才詢問實際網址，接著協助辨識節點並保存對應。

設定完成後直接上傳角色圖片，描述要做的動作。需要確認的角色參考與首幀會展示給你；能使用 UI 問答時，就用選項或文字回覆。

### 影片工作流

需能對應圖片輸入、正向提示詞、寬、高、影片長度、種子，以及可下載的影片輸出。兩張圖片的用途及第二張能否省略，依工作流設定記錄；單首幀任務可使用已對接的省略方式。

同時確認 FPS、尺寸倍數、合法影格數與範圍。生成畫布像素預算預設為 **1,000,000**，可在本機設定調整；最後對齊工作流尺寸倍數時允許少量超出。可負荷的解析度與影片長度取決於本機設備及工作流。

### 圖片工作流

需能輸入圖片與編輯提示詞，保存結果，並支援角色姿勢調整及真正的透明 PNG 去背。整張影格表去背時，需保持輸入的尺寸、格子位置與角色尺度。圖片輸入有尺寸倍數限制時，首次設定一併記錄。

本專案實測使用 **MiniMax H3** 生成影片、**Qwen Image 2.1** 處理圖片。這是可參考的搭配；Skill 透過節點對應接入工作流，不綁定這些模型。模型權重、節點與 API 工作流由使用者準備，安裝 Skill 不會一併安裝它們。

## 開始製作

上傳角色圖片，並告訴 Codex：

> 使用 comfyui-video2sprite，製作面朝右、正側視角的走路循環動畫，角色基準大小為 256×256。

必要時會先準備自然站立參考圖與動作首幀，展示給你確認。基準大小用來建立角色尺度；最終每格依完整動作共同裁切，可以是長方形，也可能因伸展動作超過基準框。

成品預設從 8 格開始，按動作需要調整。每個動作獨立交付：

- `spritesheet.png`：透明背景影格表，每格尺寸一致，依左至右、上至下排列。
- `preview.gif`：從最終影格表製作的透明循環預覽。
- `animation.json`：成品尺寸、取樣與播放時間等資料。

圖片與影片由本機 ComfyUI 執行。提示詞準備、對話與視覺檢視仍會使用 Codex 額度。

## 使用已有影片

提供影片並描述要保留的動作區間、播放時間與尺寸需求，即可接續選幀、共同裁切、拼接、去背及 GIF 製作。

適用的影片應具備：

- 完整角色與所需動作，手腳、頭髮及配件沒有被畫面截斷。
- 簡單且可辨識的背景，與角色有足夠區別，避免複雜場景、字幕或遮擋物。
- 足夠清楚的動作影格，以供選取。

影片不必先留出本 Skill 的演出空間；裁切範圍依選中影格計算。背景可在不同影格略有色差，但複雜場景不屬於目前保證能處理的範圍。

若生成結果不滿意，可請 Codex 提供已準備的輸入圖與實際提示詞，自己在 ComfyUI 測試；取得合適影片後再提供給 Codex，接續後半流程。

## 本機資料與更新

工作流與節點對應存於工作資料夾的 `.local/`；任務中間資料在 `work/`，交付成品在 `outputs/`。它們與 Skill 安裝目錄分開，不需要隨 Skill 分發。

更新時也可以直接告訴 Codex：

```text
請依這個儲存庫的安裝與更新指引，更新 comfyui-video2sprite，保留我的工作流設定、素材與成品：https://github.com/yuwechang/comfyui-video2sprite
```

安裝與更新位置依 [OpenAI 官方技能文件](https://learn.chatgpt.com/docs/build-skills) 處理。
首次工作流設定的欄位與驗證方式見 [環境與工作流對接](references/setup.md)。
