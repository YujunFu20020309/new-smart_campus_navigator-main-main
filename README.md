# NTHU Smart Campus Navigator

清大校園智慧導航系統是一個 Python 期末專題 Safety MVP。使用者可以在 Streamlit 介面選擇清大校園內的起點與終點，系統會優先使用本地 `places.csv` 與 `route_cache.json`，必要時才呼叫 Nominatim 或 OSRM，並用 Folium 顯示互動式地圖。

本專案不包含即時 GPS、完整室內導航，也不承諾涵蓋清大所有小路。Safety MVP 的目標是建立穩定、可展示、可擴充的校園導航雛形。

## 安裝方式

建議使用虛擬環境：

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

macOS / Linux 可使用：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 執行方式

請在專案資料夾執行：

```bash
streamlit run app.py
```

或：

```bash
python -m streamlit run app.py
```

## 測試方式

```bash
python -m pytest
```

測試不會真的呼叫 Nominatim 或 OSRM；外部 API 都使用 mock。

## 專案架構

```text
smart_campus_navigator/
├── app.py
├── requirements.txt
├── README.md
├── data/
│   ├── places.csv
│   ├── campus_edges.csv
│   ├── forced_route_rules.json
│   ├── geocode_cache.json
│   └── route_cache.json
├── src/
│   ├── __init__.py
│   ├── geocoding.py
│   ├── routing_osrm.py
│   ├── map_view.py
│   ├── campus_graph.py
│   ├── forced_routes.py
│   ├── route_modes.py
│   └── utils.py
└── tests/
    ├── test_geocoding.py
    ├── test_routing_osrm.py
    └── test_campus_graph.py
```

## Safety MVP 功能

- Streamlit 基本介面。
- 從 `data/places.csv` 讀取清大主要地點。
- 使用下拉選單選擇起點與終點。
- 起點與終點相同時顯示 warning。
- Folium 顯示清大校園附近互動式地圖。
- Marker 顯示有座標的校園地點、起點與終點。
- 校園道路路線先檢查可設定的強制路線規則，再使用 `data/campus_edges.csv` 與 NetworkX 本地 graph。
- OSRM Route API 查詢路線、距離、時間與 GeoJSON geometry。
- OSRM 固定使用 walking profile；前端不提供汽車或腳踏車模式。
- OSRM 座標順序處理：API 使用 `longitude,latitude`，Folium 使用 `latitude,longitude`。
- `route_cache.json` 快取已成功查詢的路線。
- route cache 只接受 walking v2 格式與 `foot:walking-v2:` key；舊版或非 walking cache 會被忽略。
- Nominatim 只在使用者按下「補齊缺失座標」時使用。
- `geocode_cache.json` 快取地理編碼結果。
- Demo mode 預設開啟，避免現場展示完全依賴即時 API。

## 校園道路路線與 OSRM 基本路線

本專案目前有三種路線模式：

- `osrm` OSRM 基本路線：只使用 OSRM walking Route API 與 OpenStreetMap 公共步行路網，直接顯示 OSRM geometry、distance、duration；不載入 `campus_edges.csv`，也不執行強制路線規則或本地 Dijkstra。
- `campus` 校園道路路線：先匹配 `forced_route_rules.json`；命中時依規則組合 walking OSRM、manual 與 straight segments。未命中才使用 `campus_edges.csv` 與 NetworkX 本地 Dijkstra，校園路線失敗時才使用 OSRM fallback。
- `compare` 路線比較：分別獨立計算純 OSRM 路線與校園路線，再同時繪製並比較距離、時間及校園特殊路段；兩條路線不共用後處理。

需要本地校園 graph 的原因是：OSRM 依賴公開路網資料，可能走到校外道路，或不符合清大校園內部行人道路圖。`campus_edges.csv` 可以把 Demo 控制在課程專案定義的校園道路上。

目前校園道路資料是課程專案用的簡化路網，只包含主要展示節點與路段，不承諾完整涵蓋清大所有小路，也不代表官方精確道路資料。若路口或建築物 marker 不準，請手動修正 `data/places.csv`。

## campus_edges.csv 維護方式

`data/campus_edges.csv` 欄位：

```text
from_id,to_id,distance_m,stairs,rain_friendly,road_name,description,geometry
```

- `from_id`、`to_id` 必須對應 `places.csv` 的 `id`。
- `distance_m` 可先填近似距離，之後可人工調整。
- `stairs`：`0` 代表無樓梯，`1` 代表有樓梯或明顯高低差。
- `rain_friendly`：`1` 代表雨天較友善，`0` 代表較不友善。
- `road_name` 可填清華大道、學思路、梅園路、齋群路、自強路、厚德路、載物路等。
- `geometry` 統一使用 `[longitude, latitude]`，例如 `[[120.9966, 24.7964], [120.9957, 24.7962]]`；繪製 Folium 地圖時才轉成 `[latitude, longitude]`。
- 啟用中的自創道路預設雙向；`one_way=1` 或 `bidirectional=0` 時才視為單向。

## 強制路線規則

`data/forced_route_rules.json` 儲存前端可修改的自創強制路線。每條規則包含起終點群組、是否雙向，以及依序執行的 segments：

- `osrm`：只使用 OSRM walking。
- `manual`：使用 `campus_edges.csv` 自創道路；需要反向時自動反轉 geometry。
- `straight`：直接使用兩端點組成直線，不呼叫 OSRM。

預設包含：

- 小紅橋強制路線：`start → OSRM → red_bridge_right → manual → red_bridge_left → straight → end`。
- Lakeside 強制路線：`start → OSRM → xuesi_load → manual → fengyun_load → straight → end`。

在 Streamlit sidebar 展開「強制路線規則 / 自創道路」，即可：

- 查看、新增、編輯、刪除、啟用或停用規則。
- 修改名稱、起終點群組與雙向設定。
- 使用表格新增、刪除與排序 `osrm`、`manual`、`straight` segments。
- 匯入或匯出 `forced_route_rules.json`。

如果人工修改任何地點座標，建議清空 `data/route_cache.json` 的 `routes`，再重新產生 OSRM Demo 路線快取；本地校園道路路線則會直接使用新的 `places.csv` 與 `campus_edges.csv`。

## 進階版預計功能

- 避開樓梯模式。
- 雨天友善模式。
- 多路線比較。
- Folium 多圖層或不同線條顯示不同模式路線。

進階版相關檔案已保留 skeleton，但 Safety MVP 不會啟用進階路線邏輯。

## 三大地圖工具用途

### Nominatim

`src/geocoding.py` 負責地理編碼。系統會先讀取 `places.csv`，只有 latitude 或 longitude 缺失時，且使用者按下「補齊缺失座標」，才使用 Nominatim 查詢。呼叫時會提供明確 User-Agent，並寫入 `data/geocode_cache.json`。

### OSRM

`src/routing_osrm.py` 負責 walking 路線查詢。即使呼叫端傳入其他 profile，系統仍固定使用 `foot`。`get_osrm_route()` 的輸入是 `latitude, longitude`，呼叫 OSRM 前會轉成 `longitude,latitude`。OSRM 回傳的 GeoJSON coordinates 會轉回 Folium 可用的 `latitude,longitude`。OSRM foot duration 合理時直接採用；若缺少 duration 或速度快得不像步行，則統一以 `1.4 m/s` 估算。

`OSRM_BASE_URL` 必須指向實際載入 foot profile 的 OSRM 服務；URL 中使用 `/route/v1/foot/`，但服務端仍需正確設定步行路網。

OSRM base URL 可用環境變數設定：

```bash
set OSRM_BASE_URL=https://router.project-osrm.org
```

PowerShell：

```powershell
$env:OSRM_BASE_URL="https://router.project-osrm.org"
```

### Folium

`src/map_view.py` 負責建立地圖、加入地點 Marker、起終點 Marker，以及 OSRM 路線 PolyLine。`app.py` 透過 `streamlit-folium` 嵌入地圖。OSRM 路線距離使用 API 回傳值；manual geometry 與 straight connector 使用座標 Haversine 距離。

## Demo mode 與快取

Demo mode 預設開啟。此模式下：

- 會優先使用 `places.csv` 的座標。
- 會優先使用 `route_cache.json` 中的既有路線。
- 若某組起終點沒有快取，不會自動呼叫 OSRM。
- 使用者必須勾選「快取不存在時允許呼叫 OSRM」後再計算，才會呼叫 OSRM。
- OSRM 成功回傳後會自動寫入 `route_cache.json`，下次可離線展示同一組路線。

目前 `route_cache.json` 已清空舊版與非步行結果。勾選「快取不存在時允許呼叫 OSRM」後，系統只會以 foot profile 重新產生 walking v2 快取。

## 現場 Demo SOP

1. 進入專案資料夾。
2. 安裝套件：`python -m pip install -r requirements.txt`。
3. 啟動：`streamlit run app.py`。
4. 確認側邊欄 Demo mode 開啟。
5. 選擇起點與終點。
6. 按下「計算路線」。
7. 展示 Folium 地圖上的地點 Marker、起點、終點與路線。
8. 展示總距離、預估時間、模式與是否使用快取。
9. 說明三大 API：
   - Nominatim：地名轉座標，並使用快取。
   - OSRM：計算距離、時間與 route geometry，並使用快取。
   - Folium：產生互動式地圖。
10. 若 OSRM 失敗或無網路，改用已快取路線展示。

## 如何事先產生路線快取

1. 啟動 Streamlit。
2. 關閉或保留 Demo mode 皆可。
3. 勾選「快取不存在時允許呼叫 OSRM」。
4. 選擇 README 建議的三組起終點。
5. 各按一次「計算路線」。
6. 成功後 `data/route_cache.json` 會保存 OSRM 回傳結果。

## 常見錯誤排除

- `ModuleNotFoundError`：尚未安裝套件，請執行 `python -m pip install -r requirements.txt`。
- 地點不出現在地圖：該地點 latitude 或 longitude 缺失，或座標格式無法轉成數字。
- Nominatim 查詢失敗：確認網路可用，並設定明確 `NOMINATIM_USER_AGENT`。
- OSRM 查詢失敗：確認網路可用，或先使用已存在的 `route_cache.json`。
- Demo mode 顯示沒有快取：勾選「快取不存在時允許呼叫 OSRM」產生一次快取，或改選已快取路線。
- route geometry 為空：OSRM 沒有回傳可畫線的 LineString，請換一組座標或檢查 API 回應。

## 座標人工校正與快取注意事項

如果地圖上的 marker 位置不準，請直接人工修正 `data/places.csv`：

1. 找到要修正的地點 `id`。
2. 修改 `latitude` 和 `longitude`。
3. 將 `source` 設為 `manual`，或在 `notes` 加上 `verified`。
4. 儲存後重新啟動 Streamlit。

`source=manual` 或 `notes` 包含 `verified` 的地點，`update_missing_coordinates()` 不會用 Nominatim 覆蓋座標。

本專案會用保守範圍檢查座標是否大致位於清大校園附近：

- latitude：24.785 到 24.805
- longitude：120.985 到 121.010

如果 app 顯示座標超出範圍，請人工檢查 `data/places.csv`。缺座標地點可以保留空白，不會讓資料讀取或 app crash。

人工修改任何地點座標後，舊的 OSRM `data/route_cache.json` 可能仍使用舊座標。建議清空 `routes` 後重新產生 Demo 快取，例如保留檔案結構：

```json
{
  "version": 2,
  "provider": "osrm",
  "profile": "foot",
  "transport_mode": "walking",
  "routes": {},
  "sample_routes_to_generate": []
}
```

## places.csv 顯示與選擇欄位

`data/places.csv` 支援以下兩個欄位：

- `is_destination`：`1` 表示可出現在使用者的起點/終點下拉選單；`0` 表示只作為內部路網節點。
- `show_marker`：`1` 表示預設在 Folium 地圖顯示一般 marker；`0` 表示預設隱藏一般 marker。

如果 `places.csv` 缺少這兩個欄位，程式會依 `category` 自動補預設值：

- `building`、`gate`、`landmark`：`is_destination=1`、`show_marker=1`
- `intersection`、`road_node`、`waypoint`：`is_destination=0`、`show_marker=0`

`intersection`、`road_node`、`waypoint` 不會出現在起點/終點下拉選單，但仍保留在完整 places 資料中，供 NetworkX campus graph 計算路線。
