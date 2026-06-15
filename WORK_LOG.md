# 工作日誌

## 記錄規則

- 最新更新放在最上面，由上到下代表由新到舊。
- 「完成者」請記錄實際完成該次修改者的 GitHub 名稱。
- 若後續確認更改沒有問題，對應條目即可作為正式工作紀錄保留。

## 2026-06-15 校園地點資料新增與文件同步

### 1. 完成者與完成時間

- 完成者：YujunFu20020309
- 完成時間：2026-06-15 17:35:58 UTC+08:00（Asia/Taipei）
- 記錄狀態：已完成資料檢查與文件同步。

### 2. 新增或調整的項目

- 更新 `data/places.csv`，新增 14 筆校園地點資料。
- 統一 `Technology_Management` 與第三行政大樓中英文名稱的斜線空格格式。
- 修正新增資料中可明確判定的拼字與命名：`nthu_garden`、`scientific_instrument_center`、`center_of_innovative_incubator`、`table_tennis_hall` 與 `NTHU Hall of Fame`。
- `README.md` 不需要因新增地點清單而增加逐筆說明；現有地點資料格式與操作文件已足夠。
- 同步修正 `README.md` 的公開網站模式說明，移除已不符合目前程式行為的提示 caption 敘述。
- `data/route_cache.json` 為既有本機執行快取，本次不納入提交。

### 3. 驗證結果

- 使用 PowerShell `Import-Csv` 成功解析 `data/places.csv`，共 53 筆資料。
- 地點 ID 無重複，必要 ID 與座標欄位無缺漏。
- `table_tennis_hall` 與 `nthu_hall_of_fame` 使用相同座標；因無法僅由資料判定哪一筆座標需調整，本次保留原始座標。
- 專案 `.venv` 目前指向不存在的 Python 3.12 安裝路徑，因此本次無法執行 pytest；CSV 結構檢查已完成。

## 2026-06-13 公開網站 sidebar 預設模式調整

### 1. 完成者與完成時間

- 完成者：YujunFu20020309
- 完成時間：2026-06-13 03:35:17 UTC+08:00（Asia/Taipei）
- 記錄狀態：待確認；若確認更改沒有問題，本文檔可作為正式工作紀錄保留。

### 2. 新增或刪減的項目

- 更新 `app.py` 的公開網站模式 sidebar 行為。
- 公開網站模式下，路線模式 selectbox 預設改為 `LOCAL_GRAPH_MODE_ID`，也就是校園道路路線 / 校園模式。
- 預設 index 由 `mode_options = list(route_modes.keys())` 動態查找 `LOCAL_GRAPH_MODE_ID` 位置，不硬寫 `index=0` 或 `index=1`。
- 公開網站模式下移除 sidebar 文字：「公開網站模式：若快取不存在，系統會自動呼叫 OSRM。」
- 保留公開網站模式下 `allow_live_osrm = True`。
- 保留本機開發模式下 Demo mode toggle 與「OSRM 快取不存在時允許呼叫 OSRM」checkbox。
- 未修改 `route_service.py`、`st_folium`、`st.session_state`、`route_result` 或 `active_route` 結構。

### 3. 後續需要確認或完善的部分

- 部署後確認公開網站 sidebar 預設選中校園道路路線 / 校園模式。
- 部署後確認公開網站 sidebar 不顯示 OSRM live request checkbox，也不顯示公開網站模式提示 caption。
- 本機未設定 `PUBLIC_SITE` 時，確認原本 Demo mode toggle 與 OSRM live request checkbox 仍正常顯示。

## 2026-06-13 README 公開網站模式說明更新

### 1. 完成者與完成時間

- 完成者：YujunFu20020309
- 完成時間：2026-06-13 01:58:50 UTC+08:00（Asia/Taipei）
- 記錄狀態：待確認；若確認更改沒有問題，本文檔可作為正式工作紀錄保留。

### 2. 新增或刪減的項目

- 更新 `README.md` 的線上展示網站說明，補充公開網站模式下會自動允許 OSRM live request。
- 更新 `README.md` 的主要功能列表，補充公開網站模式會隱藏本機開發用的 OSRM live request checkbox。
- 新增 `README.md` 章節「公開網站模式與 OSRM live request」，說明：
  - `PUBLIC_SITE` 的讀取來源與 truthy 值。
  - Streamlit Community Cloud 的 Settings -> Secrets 設定範例。
  - 公開網站模式與本機開發模式的 sidebar UI 差異。
  - 此 UI 設定不改變 OSRM / Campus / Rain / Compare 的 route calculation 行為。

### 3. 後續需要確認或完善的部分

- 部署到 Streamlit Community Cloud 後，確認 README 中的 `PUBLIC_SITE = true` 設定與實際 Secrets 設定一致。
- 確認公開網站 sidebar 不顯示「OSRM 快取不存在時允許呼叫 OSRM」checkbox。

## 2026-06-13 OSRM Public Site Mode UI 更新

### 1. 完成者與完成時間

- 完成者：YujunFu20020309
- 完成時間：2026-06-13 01:43:37 UTC+08:00（Asia/Taipei）
- 記錄狀態：待確認；若確認更改沒有問題，本文檔可作為正式工作紀錄保留。

### 2. 新增或刪減的項目

- 新增 `app.py` helper：
  - `_truthy_setting(value)`
  - `is_public_site_mode()`
- `is_public_site_mode()` 會依序讀取：
  - 環境變數 `PUBLIC_SITE`
  - Streamlit secrets 的 `st.secrets["PUBLIC_SITE"]`
  - 未設定時預設為本機開發模式，也就是 `False`
- `PUBLIC_SITE` 若設定為 `true`、`1`、`yes`、`on`，即視為公開網站模式。
- 公開網站模式下：
  - 不顯示 sidebar 的「OSRM 快取不存在時允許呼叫 OSRM」checkbox。
  - `allow_live_osrm` 直接設為 `True`。
  - 顯示提示文字：「公開網站模式：若快取不存在，系統會自動呼叫 OSRM。」
- 本機開發模式下：
  - 保留原本 `Demo mode` toggle。
  - 保留原本「OSRM 快取不存在時允許呼叫 OSRM」checkbox。
  - 保留原本 `value=not demo_mode` 行為與 UI 文字。
- 未修改項目：
  - 未修改 `route_service.py`。
  - 未修改 OSRM / Campus / Rain / Compare 路線計算邏輯。
  - 未修改 `st_folium`、`st.session_state`、`route_result` 或 `active_route` 結構。
  - 未修改任何 `data/*.csv` 或 `data/*.json`。

### 3. 驗證結果

- `python -m py_compile app.py`：通過
- `python -m pytest`：通過，`148 passed`

### 4. 後續需要確認或完善的部分

- Streamlit Cloud 部署時，需在 Settings -> Secrets 加入：

```toml
PUBLIC_SITE = true
```

- 部署後建議人工確認：
  - 公開網站 sidebar 不會顯示「OSRM 快取不存在時允許呼叫 OSRM」checkbox。
  - 公開網站在快取不存在時可自動呼叫 OSRM。
  - 本機未設定 `PUBLIC_SITE` 時仍可看到該 checkbox。
- 目前工作區另有 `data/route_cache.json` 的既有本機變更，未納入本次修改；後續可另外決定是否保留、提交或還原。
