# 前段提示詞參考

本文件供執行 Skill 的 Codex 使用，涵蓋姿態圖片與來源影片。後段 Refine、去特效與去背依[影格表指引](spritesheet.md)，不把那些處理要求提前混入來源影片。方括號是待填欄位，送出前換成具體內容；不把所有版型一次串入提示詞。

## 編寫原則

- 先確定輸入圖片、目標姿態／動作、環境、結束行為及是否需要特效，再選用版型。保留身份與外觀，不代表保留需要改變的姿勢。
- 直接描述目標狀態與可觀察的動作，以正向描述為主。只保留有用途的空間、形態與時序要求；不以堆疊形容詞、否定清單或不透明度百分比代替清楚的演出描述。未要求動作力度時，不自行加上暗示誇大特效的強度修飾。
- 同一效果的共用描述可以重用，作用部位、方向、路徑與節奏必須由當次需求及參考圖填入。通用規則不固定肢體或裝備，但實際提示詞不能只留下含糊的「作用端」：填入可辨識的部位及其空間位置。
- 以模型適用語言編寫，對使用者以其語言說明。Qwen 圖片編輯使用使用者指示的語言；H3 核心欄位以英文編寫。若已安裝 `h3-prompt-writing` 或 `qwen-image-2-1-prompter`，讀取與目前輸入模式相關的規範；未安裝時，本文件提供執行所需的基本結構，不強制另裝技能。其他模型依已對接工作流使用同等內容，不盲套 H3 欄位。
- 這些是實測支持的優先寫法，不是模型保證遵守的參數。形狀或亮度不同不自動表示失敗；仍需檢查動作、作用範圍、完整性與節奏。

## 姿態圖片：先選對參考

| 任務 | 優先輸入 | 處理方式 |
| --- | --- | --- |
| 已有符合需求的姿態參考 | 使用者提供或已確認的該姿態圖片 | 檢查並沿用，不為套版而重新生成。 |
| 建立不同的新姿態 | 同角色自然站立等中性基準圖 | 各姿態從共用基準分別建立，減少原手勢、身體架勢及接觸關係的牽制；不預設由上一種姿態逐次改造。 |
| 微調同一姿態 | 目前最接近目標的姿態圖 | 只改指定部分，保留已正確的結構。 |
| 由姿態延伸動畫 | 對應姿態的 Idle 或任務指定空中基準 | 按[影片生成](generation.md)選圖，不重新從中性圖生成每個動作。 |

中性指姿勢較少受特定演出牽制，不表示刪除角色原有裝備或更改外觀。沒有合適中性圖時，先評估現有圖能否直接完成目標；必要時準備同角色中性靜態參考。這是工作素材，不是額外的一般 Idle 製作選項。只選攻擊姿態時，仍只交付該姿態要求的動畫。

姿態來源與幾何基準分開處理：換參考不能改變已確認的角色尺度、畫布與站位；多姿態的共用幾何方式見[圖片預處理](image-processing.md)。保留身份與可辨識外觀；只新增或替換使用者要求的裝備，不因戰鬥姿態自行加裝備。

### 建立新姿態版型

以簡短的目標姿勢開頭，按需要補全身體與接觸關係。以下段落中的裝備句只在涉及裝備時使用：

> 將圖像中角色的動作改成[完整目標姿態]。[支撐與重心、肢體位置、身體朝向等必要關係]。[使用者要求的裝備及實際握持／接觸關係]。保留同一角色的身份、身體比例、服裝配件與原繪製風格，完整保留全身及裝備。角色面朝右，[與目前架勢相符的身體朝向]，輸出真正透明背景 PNG。

已建立共用幾何基準時，補上「保持已確認的畫布尺寸、角色尺度與腳下站位，保留姿態本身造成的高度差」。身體朝向依架勢自然呈現，可為斜側面；面朝右與固定側面鏡頭不等於全身必須嚴格正側面。不要只調整上半身而讓骨盆、雙腿與整體架勢互相矛盾。

### 微調既有姿態版型

> 將圖像中的[需修改部分]改為[目標狀態及必要接觸關係]。保留[已正確且應維持的部分]，保持角色身份、外觀、繪製風格及已確認的畫布、尺度與站位。輸出真正透明背景 PNG。

先看整體姿態、肢體數量、手部與裝備接觸、裝備完整性及背景，再確認幾何基準。手靠近裝備不等於已握住。若結果持續沿用不合適的原姿勢，回到選圖表重新評估輸入，不在同一張圖上反覆加限制硬修；局部細節錯誤才針對性微調。起始圖未合格且未依圖片流程確認前，不提交依賴它的影片批次。

## 影片：內容與模型格式分開

### 共用內容順序

1. 由輸入圖確定畫風、角色身份、外觀與裝備；描述全身構圖、身體朝向、固定鏡頭、原背景及尺度。
2. 描述本任務的起始姿態、準備、主要動作、自然隨動與結束行為。方向、路徑與節奏要能被觀察，不以一串抽象動作名稱代替。
3. 需要原地動作時插入站位段；需要特效時將對應效果段直接寫入有效攻擊階段。
4. 依 `loop`、`return_to_start` 或 `hold_end_pose` 填入結束段；依本節決定是否使用獨立重複演出。

### H3 圖生影片版型

先依工作流實際連接決定 I2VA（首圖）、FL2VA（首尾圖）或 L2VA（尾圖），不能只在文字提到圖片就當作已連接。單一固定全身鏡頭使用 `[Shot 1]`，畫風與構圖放在該段開頭，再按順序描述動作。不為套格式加入剪接、對白或音樂。

I2VA 的第一行：

```text
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.
```

FL2VA 的第一行：

```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the [實際來源秒數，兩位小數]-second mark of the target video.
```

L2VA 的第一行：

```text
How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the [實際來源秒數，兩位小數]-second mark of the target video.
```

對齊文字後空一行，再依序寫以下三個欄位。H3 純文字生成省略圖片對齊行，內容仍依序使用三個欄位；沒有圖片時不得引用 Picture 1。

```text
integrated_multimodal_description: [Shot 1] A continuous full-body [reference-derived visual style] animation preserves the identity, appearance, equipment, proportions, scale and composition of Picture 1. The character faces right in [the confirmed stance orientation]. The camera holds a static shot, and the original plain gray background remains stationary throughout. [Starting state, preparation, main action and recovery or ending, in chronological order; insert the applicable stance, effect and repetition blocks within that sequence.] Hair, clothing and accessories follow the movement naturally. The complete character and all physical equipment remain inside the frame. [Relevant physical action sounds, if applicable.]

overall_soundscape: [Brief description of physical action sounds and ambience consistent with the scene.]

non_diegetic_music: N/A
```

版型以本流程準備的灰底首圖為前提；圖像／背景或工作流不同時替換對應描述，不假稱不存在的背景。L2VA 主體段應改成「從合理起始狀態逐步接近 Picture 1 的結束姿態」，不能照抄首圖起始段。`overall_soundscape` 只在使用者要求全程完全無聲時使用 `N/A`；沒有背景配樂則 `non_diegetic_music: N/A`。

首尾對齊秒數使用工作流合法影格數除以 fps 的實際值，不直接照填請求秒數；依 `scripts/generate.py` 現有 `align_frames` 與 profile 的 `generation` 規則換算，不另外發明一套長度公式。動作以先後順序與節奏描述，不預設逐秒硬切、不固定留結尾等待秒數。依素材需要與工作流能力選來源長度，不為每個新動作從多種秒數逐一盲試。

### 原地動作站位段

僅用於本來就應在同一站位內完成的動作；移動與空中動作依任務環境處理，不套固定腳印。

> The original support positions in Picture 1 anchor the standing area throughout. Weight shifts, body turns, knee flexion and natural pivots occur within that stance. The character recovers to the pictured guard and original standing area after each complete action.

動作需要換步時，改為描述換步後如何回到原站位，不用腳印限制取消必要動作。鏡頭固定與站位穩定分開描述；不以鎖死所有關節的方式防滑。

### 結束與重複演出段

| 動作類型 | 結束描述 |
| --- | --- |
| `loop` | 描述連續週期運動，末尾回到可銜接開頭的同一動作相位；不在每個週期間加入待機或收招停頓。 |
| `return_to_start` | 完成主要動作並完整回復本任務起始姿態；地面或空中的起始基準依任務決定。 |
| `hold_end_pose` | 描述必要演出與主要動作，最後保持目標姿態，不加回到起始的指令。 |

`return_to_start` 的來源長度足以容納多次短動作時，可用獨立重複充分利用影片，而非將單次出招刻意拖滿整段：

> The character performs [a small requested number of] independent repetitions of this complete action-and-recovery sequence. Each repetition starts from and completely returns to the pictured starting pose before the next begins. The final complete repetition recovers to [the task's ending reference].

填入合理的少量次數，次數是來源演出引導，不是成品規格或精確計數保證。使用者未要求連招時，每次完整回復後才再次出招；不要用不合理的大次數擠滿時長。沒有完整回復的半次演出不能當作完整動作候選。需要長時間停留、不可回復或循環運動時不套此段。來源包含一段完整可用動作即可進入既有後段選段，不因沒達指定重複數而重生整支影片。

只有工作流確實支援首尾幀、且任務應返回同一姿態時，才可把同一起始圖接入首尾；仍需檢查中途演出。不可將同圖首尾套到應停在不同姿態的動作。來源重複演出不改變成品的動作類型，GIF 重播另依交付指引。

## 特效：先選類型，再寫入有效攻擊段

| 選擇 | 適用意圖 | 編寫方式 |
| --- | --- | --- |
| 無附加效果 | 不需攻擊效果的動作，或使用者要求無特效 | 省略效果段，直接描述動作與場景；不額外灌入特效名詞的禁止清單。來源仍可能自行加效果，必須檢查。 |
| 打擊 | 在短暫作用處表現接觸／衝擊 | 優先小型白色空壓脈衝，局部空心輪廓；不要求有完整長距離尾跡。 |
| 尾跡 | 用走過的攻擊路徑表現運動 | 只跟隨有效攻擊的作用部位路徑；形態服從路徑，不讓整件裝備任何移動都發射效果。 |

兩者是提示詞組裝選擇，不新增程式參數、問卷或新的後段類型。使用者指定其他效果時依其需求；沒有必要不把兩段一起套用。

### 打擊效果版型

先從參考與動作指定 `[作用部位]` 及合理的 `[局部尺寸]`；尺寸相對作用處可辨識的寬度描述，避免拿整個角色或畫布當效果尺度。有效攻擊到達作用瞬間時插入：

> At [the brief impact phase], a small, faint white air-pressure pulse appears only in a compact pocket of air immediately ahead of [the acting part]. This pocket is the sole location of the effect. A narrow crescent surrounds an open center, about [local size relative to the acting part] across. It is low-contrast and highly transparent, with the background visible through it. The effect immediately thins out and vanishes as [the action recovers].

以空心、局部範圍及短促消散表現打擊，保持主體內容可見。白色深淺主要以視覺透明感描述，不用黑色陰影或實心填滿來壓暗；「淡、透明」仍是引導，不保證指定亮度。這是空壓脈衝的優先參考，不必強求每個種子有相同輪廓。

### 尾跡效果版型

先確定真正攻擊的 `[作用部位]`、方向與路徑，以及何時開始、何時完成。長形或多作用部位的裝備要在當次提示詞中具體指認本次使用的位置；除非動作本身要求，不把所有端點或回提移動都列為攻擊。

> Only during [the effective attacking stroke], a short white [trail shape matching the attack path] traces the path immediately behind [the moving acting part]. Its slender outer contour carries a softly feathered translucent inner layer. The background shows through it increasingly clearly toward the inner edge and trailing tip as both dissolve into transparency. The brief trail fades out as [the attacking stroke finishes].

弧形攻擊可填窄弧形／crescent；其它軌跡依實際運動描述，不強迫形成環或旋轉，也不宣稱尚未測過的軌跡已穩定。外緣較清楚、內層與尾端淡出是目標；可能仍有實白區，不以形狀變尖誤認透明淡出。

### 階段綁定的完整結構

> From [the pictured starting stance], the character prepares by [the necessary preparatory movement], with [the physical acting part or equipment] clearly visible. The character then performs [the main attack, direction and readable path]. [Insert the chosen effect block here, tied to this effective attack.] Once the attack completes and its effect dissipates, the character [recovers through clear air to the starting stance, or reaches the required ending pose].

把效果放在主動作敘述內，不在整段最後另寫「武器移動時有尾跡」。準備、攻擊與回復依動作意圖、方向及連續節奏區分，不以單張肢體高度判定，也不把慢準備／快攻擊當成所有動作的固定節奏。

角色及實體裝備的保留段可共用：

> The character and physical equipment remain clearly readable, retaining their original colors, details and silhouettes. The character masks the effect where the effect lies behind the body in the depicted action.

通常讓效果在角色後方，避免覆蓋而遺失內容；真實路徑造成的短暫前後交疊仍按動作判讀。不要為保持同一渲染層而破壞合理的空間關係。來源內容清楚的薄透明交疊可交由後段處理；不透明效果取代的肢體與裝備內容不能保證補回。

## 檢查與有依據的調整

先用本機數值分析、來源概覽與正常速度預覽找問題，只在有疑義的動作交界補看少量連續原尺寸影格。不逐幀依賴 Codex 視覺讀完整影片，也不為檢查來源提前 Refine 全部影格。

| 觀察到的問題 | 優先檢查與調整 |
| --- | --- |
| 新姿態仍沿用不合適的原手勢／接觸 | 回到選圖策略，從中性基準建立；局部修改才沿用現姿態。 |
| 未看清握持就生成影片 | 停在起始圖確認；先放大接觸處，不把檔案完成當成視覺通過。 |
| 動作過慢、出招久停、連續未回復 | 檢查動作順序、節奏與完整回復描述；適合時使用獨立重複，不先盲試一串影片長度。 |
| 效果在準備或收招也出現 | 看完整方向與節奏，確認不是快速攻擊起始；確實越段時調整階段綁定與作用部位。 |
| 大面積效果、環繞或額外地面效果 | 檢查作用位置、局部尺寸、消散及是否有暗示擴張的措辭。合理提示詞偶發失控時可先換種子，不因一次失控無限加詞。 |
| 角色後滑或站位漂移 | 對照原圖留白、腳下位置、實際步伐及尺度；正常換步、屈膝與轉腳不是滑移。依本來的動作決定是否加原地段。 |
| 特效遮擋、武器變形或肢體消失 | 檢查同一完整候選段能否保留可辨識內容；不能把多段優點拼成一段合格來源，也不以後段必能重建為理由放行。 |

修改須對應觀察到的原因；別把每次種子差異都當成提示詞錯誤，也別只用「換種子」掩蓋持續的同一問題。若更改提示詞或參考圖，保存實際輸入並使用新任務目錄；接續同一次提交才沿用原任務。

要求穩定度測試時，先固定驗收標準，保留相同提示詞、圖片、工作流及參數，只換互不重複的隨機種子。記錄已完成數、每支具體問題與實際種子；同種子可做前後對照，刻意挑選的困難種子不混作隨機成功率。單次成功不足以宣稱穩定，不把多次出招當作多個獨立影片樣本；小樣本結果不宣稱跨角色、跨動作保證。使用者未要求穩定度測試時，不為每個正常製作任務自動增加多種子批次。
