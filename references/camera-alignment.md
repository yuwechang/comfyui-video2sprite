# 地面背景的垂直鏡頭補償

這是後段可選處理，僅用於已觀察到垂直鏡頭漂移、且有可靠固定背景參照的影片。輸入是已選影格及明確背景區域，不依賴前段計畫或特定背景生成方式。無漂移時省略；無可靠背景時不能以人物腰部、鞋底或輪廓中心代替。此功能不與空中腰部定位組合。

順序：選段取樣 → 檢查所選影格 → 背景垂直補償 → 補償檢查 → 第一次共同裁切 → Refine／去背及版本分流 → 第二次共同裁切、合併與交付。只分析選中的影格，不改來源索引、取樣策略、播放時間或縮回倍率。

Codex 在第一張選中原尺寸影格標示至少兩個背景 ROI，分處不同水平位置、橫向不重疊，跨過同一靜止水平交界。每區至少 12×12 px，避開所有選中格中的角色、陰影、特效及可動物件。交界不必是牆地交界，但必須是同一固定背景特徵。可另提供未參與估計的 validation_regions，檢查獨立區域的殘差。

```json
{"regions":[[X0,Y0,X1,Y1],[X2,Y2,X3,Y3]],"validation_regions":[[X4,Y4,X5,Y5]]}
```

```text
python scripts/camera_alignment.py --selection-file work/action/selection/selection.json --regions-file work/action/background-regions.json --output work/action/camera-aligned
```

程式使用橫向亮度中位數及縱向梯度，對照第一張選中格，跨區域一致後才採用位移。預設搜尋上限 32 個來源像素、區域差異上限 3 px；弱交界、明暗極性改變、區域不一致或到達搜尋上限時停止回報，不當作零位移繼續。這些是操作預設，不是成功保證。

`dy` 為整張影格的反向平移量。共用擴大的透明畫布容納平移，不裁去原內容、不旋轉、不縮放、不逐格置中，不固定腰部或腳底。因此保留角色相對背景的屈膝、重心與出腿變化。僅處理垂直平移，不修正縮放、旋轉、透視或模型改畫比例；仍需視覺檢查。

正式計畫使用 execution_plan.py 的 enable-camera 入口串接 selection → camera_alignment → finish，參數與範例依[執行計畫](execution.md#一份請求設定未執行階段)，不手動插入階段或改引用。alignment、coverage、body_scale 檢查通過後才能接續，不覆寫原始選幀或影片。

背景區域可先用 `python scripts/region_proposals.py --selection-file selection.json --output work/background-regions.json` 產生跨所選影格排除前景後的獨立背景帶候選及標示圖。候選會先做數值一致性檢查，但 requires_confirmation 仍為 true；須確認確為靜止背景，不能因數值吻合就套用。無足夠空間或可靠交界時會回 needs_input，改依圖片明確指定。

輸出 selection.json、alignment.json、aligned-來源索引.png、同畫布的原版／補償版 GIF 及補償後總覽。先看各區域估計及獨立區域殘差，再比較 GIF，確認背景穩定而角色的動作起伏保留。靜態總覽不能冒充已觀看實際播放；數值通過不等於動作、身份或尺度合格。

finish 保存 camera_alignment 的純資料報告，source_origin 錨點納入共用補邊的位移。正式素材登錄保存原始選中格、補償格與對齊報告。需要雙版本時從同一批補償後輸入分支，不重新取樣或分別追蹤。
