# NTHU Smart Campus Navigator

清大智慧校園導航系統是一個以 Streamlit 建立的校園步行路線工具。專案整合地點資料、OSRM walking 路線、校園自訂路網、強制路線規則與 Folium 地圖，讓使用者可以在不同路線模式之間切換，查看適合 demo 或人工維護資料的校園導航結果。

目前沒有串接天氣 API。雨天路線由使用者在側邊欄手動選擇。

## 主要功能

- Streamlit 互動式介面，選擇起點、終點與路線模式後顯示地圖和路線資訊。
- OSRM walking 路線，固定使用 `foot` profile，並以 `data/route_cache.json` 快取結果。
- 校園自訂路線，使用 `data/campus_edges.csv` 建立 NetworkX graph 並計算校園內部路線。
- 強制路線規則，使用 `data/forced_route_rules.json` 定義 OSRM、manual、straight 混合路段。
- 雨天路線模式，優先套用雨天專用強制規則，沒有符合規則時回到純 OSRM walking。
- 路線比較模式，獨立計算純 OSRM 路線與校園路線，再顯示差異。
- Folium 地圖顯示起終點 marker、路線 polyline 與比較模式的雙路線樣式。
- 地圖點選新增地點模式，可從 Folium 點擊取得座標，先寫入 pending 待審核清單。
- 側邊欄提供資料品質檢查、座標補齊、校園邊資料管理與強制路線規則管理。

## 路線模式

目前可見模式定義在 `src/route_modes.py`：

| 模式 ID | 顯示名稱 | 行為 |
| --- | --- | --- |
| `osrm` | OSRM 路線 | 只使用 OSRM walking。此模式不載入強制路線規則、不讀取校園 graph，也不執行 Dijkstra。 |
| `campus` | 校園路線 | 先檢查可適用的強制路線規則。若沒有命中，使用 `campus_edges.csv` 建立校園 graph 並跑 Dijkstra。若校園路線失敗，再使用 OSRM fallback。 |
| `rain_friendly` | 雨天路線 | 先檢查 `modes=["rain_friendly"]` 的雨天專用強制規則。若命中，使用 `route_with_forced_rule()`。若沒有命中，使用純 OSRM walking。此模式不會跑校園 Dijkstra。 |
| `compare` | 路線比較 | 獨立計算純 OSRM 與校園路線，保留兩邊結果並產生比較摘要。 |

雨天路線特別注意：

- 不會自動判斷天氣，也不會呼叫 weather API。
- 使用者必須手動選擇「雨天路線」。
- 只有命中的強制規則包含 `manual` segment 時，才會使用 `campus_edges.csv` 中的人工路段資料。
- 沒有雨天專用強制規則時，結果是純 OSRM walking，但 `mode` 會標記為 `rain_friendly`。

## 安裝

Windows PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

macOS / Linux：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 啟動

```bash
streamlit run app.py
```

或：

```bash
python -m streamlit run app.py
```

啟動後在瀏覽器開啟 Streamlit 顯示的本機網址，通常是 `http://localhost:8501`。

## 測試

```bash
python -m pytest
```

測試涵蓋 OSRM 快取與 fallback、校園 graph、強制路線、路線模式分離、資料管理和 Streamlit 基本啟動檢查。多數外部服務行為會透過 mock 或快取測試，不需要真的呼叫 Nominatim 或 OSRM。

## 專案結構

```text
.
├── app.py
├── README.md
├── requirements.txt
├── pytest.ini
├── data/
│   ├── places.csv
│   ├── campus_edges.csv
│   ├── forced_route_rules.json
│   ├── manual_places_pending.csv
│   ├── places_with_pending_preview.csv
│   ├── geocode_cache.json
│   └── route_cache.json
├── src/
│   ├── campus_graph.py
│   ├── data_admin.py
│   ├── forced_routes.py
│   ├── geocoding.py
│   ├── geo_utils.py
│   ├── map_view.py
│   ├── route_modes.py
│   ├── route_service.py
│   ├── routing_osrm.py
│   ├── ui_forced_routes.py
│   ├── ui_pending_places.py
│   ├── ui_route_info.py
│   └── utils.py
├── tests/
└── tools/
    └── merge_pending_places.py
```

## 四階段重構摘要

本專案已將原本集中在 `app.py` 的路線計算與部分 Streamlit UI 逐步拆出，目標是讓 `app.py` 保留入口流程、相容 wrapper 與地圖互動，其他邏輯依職責放到 `src/` 模組。

| 階段 | 模組 | 重構內容 |
| --- | --- | --- |
| 第一階段 | `src/route_service.py` | 搬出 OSRM、Campus、Rain、Compare 路線計算與比較摘要邏輯。`app.py` 仍保留原本可被 tests import 的函式名稱，透過 wrapper 注入 OSRM client、forced route rule matcher、graph builder 與 route computer。 |
| 第二階段 | `src/ui_pending_places.py` | 搬出新增地點 pending review UI、Folium 點擊座標解析、表單清除與 pending CSV 寫入流程。`app.py` 仍保留 callback，負責清 cache 與維持 `st.session_state` 行為。 |
| 第三階段 | `src/ui_forced_routes.py` | 搬出強制路線規則側邊欄 UI，包含 mode 選擇、segment editor、規則新增、更新與刪除。`app.py` 只傳入資料路徑與 rules changed callback。 |
| 第四階段 | `src/ui_route_info.py` | 搬出右側路線資訊 UI，包含一般路線摘要、Compare 模式資訊、OSRM Debug、模式說明文字與 coordinate delta 顯示。`app.py` 仍保留 `render_compare_route_info()` 和 `coordinate_delta()` 的 import 名稱以維持相容。 |

重構期間保留的邊界：

- 不改變 OSRM / Campus / Rain / Compare 路線模式行為。
- 不改變 `route_service.py` 的路線計算邏輯。
- 不改變 `route_result`、`active_route` 或 compare result 的 dict 結構。
- 不改變既有 Streamlit UI 文字、`st.session_state` key、`st_folium` key、`returned_objects` 或地圖點選行為。
- 不讓 UI 模組 import `app.py`；需要的資料由 `app.py` 以參數傳入。

## 核心檔案

### `app.py`

Streamlit 主程式，負責：

- 載入 places、campus edges 和 forced route rules。
- 呈現側邊欄與地圖。
- 保留可供 tests import 的相容函式名稱，並把路線計算委派到 `src/route_service.py`。
- 根據路線模式 dispatch：
  - `get_osrm_route_for_places()`
  - `get_campus_route()`
  - `get_rain_route()`
  - `build_route_comparison()`
- 管理 demo mode、OSRM live request、cache 與資料管理 UI。
- 將新增地點審核、強制路線規則與右側路線資訊 UI 委派到 `src/ui_pending_places.py`、`src/ui_forced_routes.py`、`src/ui_route_info.py`。
- 在「新增地點模式」中接收 Folium `last_clicked` / `last_object_clicked`，並把點擊座標暫存到 `st.session_state["pending_clicked_location"]`。

### `src/route_service.py`

集中處理路線計算與模式分派，包含 OSRM、校園路線、雨天路線與比較模式。`app.py` 透過 wrapper 注入 OSRM client、forced route rule matcher 與 graph builder，讓 Streamlit 入口維持薄一點，同時保留原本可測試的函式名稱。

### `src/ui_pending_places.py`

負責新增地點 pending review UI，包含 Folium 點擊座標帶入、表單狀態清除與待審核資料寫入。

### `src/ui_forced_routes.py`

負責強制路線規則側邊欄 UI，包含規則新增、編輯、刪除、mode 選擇與 segment editor。

### `src/ui_route_info.py`

負責右側路線資訊 UI，包含一般路線摘要、比較模式資訊、OSRM Debug、模式說明文字與 route geometry coordinate delta 顯示。

### `src/route_modes.py`

集中定義路線模式 ID、顯示名稱與是否為進階模式。目前 visible modes 是：

```python
OSRM_MODE_ID = "osrm"
CAMPUS_MODE_ID = "campus"
RAIN_MODE_ID = "rain_friendly"
COMPARE_MODE_ID = "compare"
```

### `src/routing_osrm.py`

OSRM Route API client，負責：

- 固定 walking/foot profile。
- 將 app 使用的 `latitude, longitude` 轉成 OSRM URL 需要的 `longitude,latitude`。
- 將 OSRM GeoJSON `[lon, lat]` 轉成 Folium 使用的 `[lat, lon]`。
- 使用 `data/route_cache.json` 快取路線。
- 在 demo mode 中，若快取不存在且未允許 live OSRM，回傳明確錯誤。

### `src/campus_graph.py`

讀取 `campus_edges.csv` 並建立 NetworkX graph。校園路線模式會使用它計算 Dijkstra 路線。雨天路線目前不直接跑此 Dijkstra 流程。

### `src/forced_routes.py`

處理強制路線規則：

- `load_forced_route_rules()`
- `save_forced_route_rules()`
- `match_forced_route_rule()`
- `route_with_forced_rule()`

`match_forced_route_rule()` 支援可選的 `mode_id`：

- 規則沒有 `modes` 欄位時，維持舊行為，所有相關模式都可以匹配。
- 規則有 `modes` 欄位時，只有 `mode_id` 包含在 `modes` 中才會匹配。
- 例如 `"modes": ["rain_friendly"]` 只會套用在雨天路線。

### `src/map_view.py`

負責建立 Folium map，包含 marker、polyline、比較模式路線樣式，以及地圖上顯示的 route layer。

### `src/data_admin.py`

提供 places、campus edges 與 pending places 的資料清理、驗證與儲存工具，供 Streamlit 側邊欄管理 UI 使用。

地圖點選新增地點會使用 `append_pending_place()`，只寫入 `data/manual_places_pending.csv`，不會直接修改正式的 `data/places.csv`。

### `tools/merge_pending_places.py`

產生人工審核用的合併預覽檔。預設只輸出 `data/places_with_pending_preview.csv`，不會自動修改 `data/places.csv`。

```bash
python tools/merge_pending_places.py
```

## 資料檔案

### `data/places.csv`

正式地點資料。這是人工驗證後的目的地資料，不應由地圖點選新增流程直接寫入。

常用欄位包含：

- `id`：地點唯一識別碼。
- `name` / `display_name`：顯示名稱。
- `category`：地點類型，例如 building、gate、road_node、waypoint。
- `latitude` / `longitude`：座標。
- `is_destination`：是否出現在起點/終點選單。
- `show_marker`：是否在地圖上顯示 marker。

一般建議：

- 建築物、校門、主要地標可設為 `is_destination=1` 和 `show_marker=1`。
- graph 用的中繼點、路口、waypoint 通常設為 `is_destination=0` 和 `show_marker=0`。
- 手動確認過的座標可使用 `source=manual` 和 `notes=verified`，避免被自動補座標流程覆蓋。

### `data/manual_places_pending.csv`

地圖點選新增地點的待審核清單。使用者在前端點地圖並送出表單後，資料會先寫入這個檔案，而不是正式 `places.csv`。

欄位與 `places.csv` 相容，並額外保留 `type`：

```text
id,name,display_name,category,latitude,longitude,source,notes,is_destination,show_marker,type
```

固定欄位：

- `source`：固定為 `manual_ui_pending`。
- `notes`：固定為 `pending_review`。

新增前會檢查：

- `id` 不可空白。
- `id` 不可與 `data/places.csv` 既有 id 重複。
- `id` 不可與 `data/manual_places_pending.csv` 既有 id 重複。
- `latitude` / `longitude` 必須存在。
- 座標必須在清大校園合理範圍內。
- `category` 必須是允許值之一：`building`, `gate`, `library`, `cafeteria`, `dorm`, `landmark`。

### `data/places_with_pending_preview.csv`

由 `tools/merge_pending_places.py` 產生的人工審核預覽檔，用來查看正式地點加上 pending 地點後的結果。這個檔案是 preview，不是正式資料來源。

### `data/campus_edges.csv`

校園路網邊資料。常用欄位包含：

- `from_id` / `to_id`：必須對應 `places.csv` 的 `id`。
- `distance_m`：路段距離，若有 geometry 可由 polyline 估算。
- `stairs`：是否包含階梯。
- `rain_friendly`：是否適合雨天行走。
- `road_name` / `description`：路段描述。
- `geometry`：以 `[longitude, latitude]` 儲存的 polyline JSON。
- `routing_source`：例如 manual、osrm、straight。
- `verified`：是否已人工確認。
- `ignore_osrm`：是否不要用 OSRM 自動補線。
- `enabled`：是否啟用此 edge。
- `bidirectional` / `one_way`：控制是否可反向通行。

### `data/forced_route_rules.json`

強制路線規則使用 JSON 儲存。基本格式：

```json
{
  "id": "example_rule",
  "name": "Example forced route",
  "enabled": true,
  "bidirectional": true,
  "modes": ["rain_friendly"],
  "from_place_ids": ["main_gate"],
  "to_place_ids": ["main_library"],
  "forward_segments": [
    {"type": "osrm", "from": "start", "to": "some_waypoint"},
    {"type": "manual", "from": "some_waypoint", "to": "end"}
  ]
}
```

欄位說明：

- `enabled`：只有 `true` 的規則會被匹配。
- `bidirectional`：若為 `true`，起終點反向時也可以匹配。
- `modes`：可選欄位。省略時代表所有原本可使用 forced rules 的模式都可匹配。
- `from_place_ids` / `to_place_ids`：規則的起終點集合。
- `forward_segments`：正向路線段落。

segment type：

- `osrm`：該段使用 OSRM walking。
- `manual`：該段使用 `campus_edges.csv` 的人工路段 geometry。
- `straight`：用起終點直線連接，距離以 Haversine 估算。

目前資料中保留既有校園強制規則，並新增了一筆停用的雨天範例規則：

- `rain_example_rule`
- `enabled: false`
- `modes: ["rain_friendly"]`
- 用於示範雨天專用 forced route 規則格式。

## 強制路線管理 UI

在 Streamlit 側邊欄中，選擇「校園路線」或「雨天路線」時可以管理強制路線規則。

新增或編輯規則時，「適用模式」選項會影響 JSON：

| UI 選項 | 儲存結果 |
| --- | --- |
| 全部模式 | 不儲存 `modes` 欄位 |
| 校園路線 | `"modes": ["campus"]` |
| 雨天路線 | `"modes": ["rain_friendly"]` |

舊規則若沒有 `modes` 欄位會繼續照舊運作。

## 地圖點選新增地點

這個流程是安全的待審核新增流程，不會直接寫入 `data/places.csv`。

使用方式：

1. 啟動 Streamlit 並開啟 `http://localhost:8501`。
2. 在 sidebar 打開「新增地點模式」。
3. 在 Folium 地圖上用左鍵點選要新增的位置。
4. 右側會顯示點擊座標：
   - `latitude`
   - `longitude`
5. 右側表單填入：
   - `id`
   - `name`
   - `display_name`
   - `category`
   - `type`
   - `is_destination`
   - `show_marker`
   - `notes`
6. 按下「加入待審核地點」。

送出後資料會寫入：

```text
data/manual_places_pending.csv
```

不會寫入：

```text
data/places.csv
```

`latitude` 和 `longitude` 預設使用地圖點擊座標，不讓使用者直接亂填。若真的需要微調，可以勾選「進階手動修正座標」。

`type` 是補充分類欄位，不直接影響路線計算。可以填入人工審核時有用的資訊，例如 `entrance`、`exit`、`bike_parking`、`rain_shelter`，不確定時可留空。

成功加入 pending 後，系統會：

- 顯示成功訊息。
- 清除 pending form 狀態。
- 清除 Streamlit cache。
- 提醒使用者這只是 pending，不是正式 `places.csv`。

### 人工審核與合併預覽

待審核資料要人工確認後才可以進正式地點資料。

建議流程：

1. 檢查 `data/manual_places_pending.csv`。
2. 確認 id、名稱、分類、座標都正確。
3. 產生預覽檔：

```bash
python tools/merge_pending_places.py
```

4. 檢查輸出的 `data/places_with_pending_preview.csv`。
5. 確認無誤後，再人工合併到正式 `data/places.csv`。

`merge_pending_places.py` 預設不會自動合併，目的是避免尚未審核的地點污染正式資料。

## Demo Mode 與快取

側邊欄的 Demo mode 預設開啟，目標是避免 demo 現場因網路不穩導致 OSRM 或 Nominatim 呼叫失敗。

- Demo mode 開啟時，若 OSRM route cache 已存在，會直接使用快取。
- 若快取不存在，且未勾選允許 live OSRM，路線會回傳提示錯誤。
- 若需要重新呼叫 OSRM，可勾選「OSRM 快取不存在時允許呼叫 OSRM」或「忽略快取，重新呼叫 OSRM」。

`data/route_cache.json` 使用 walking v2 key 格式，OSRM profile 固定為 `foot`。

## 座標與 geometry 注意事項

- `places.csv` 使用 `latitude`、`longitude` 欄位。
- OSRM API URL 使用 `longitude,latitude`。
- OSRM GeoJSON geometry 使用 `[longitude, latitude]`。
- Folium polyline 使用 `[latitude, longitude]`。
- `campus_edges.csv` 的 `geometry` 欄位以 `[longitude, latitude]` 儲存，程式會在顯示地圖時轉換成 Folium 格式。

如果地圖線段位置看起來顛倒或跑到校外，優先檢查座標順序。

## 校園資料維護建議

新增地點：

1. 一般使用者從「新增地點模式」點地圖新增，資料會先進 `data/manual_places_pending.csv`。
2. 管理者人工審核 pending 資料後，再合併到 `data/places.csv`。
3. 正式修改 `data/places.csv` 前，請確認 `id`、座標、分類與 marker 設定。
4. 建築或地標設定 `is_destination=1`，純路網節點設定 `is_destination=0`。

正式地點維護：

1. 只有人工確認後，才直接編輯或儲存 `data/places.csv`。
2. 確認 `id` 唯一且穩定。
3. 填入有效座標。
4. 手動確認過的座標建議使用 `source=manual` 和 `notes=verified`。

新增校園 edge：

1. 確認 `from_id` 和 `to_id` 已存在於 `places.csv`。
2. 若要人工控制路線，填入 `geometry`。
3. 若是單向路段，設定 `one_way=1` 或 `bidirectional=0`。
4. 若不希望自動使用 OSRM 補 geometry，設定 `ignore_osrm=1`。
5. 儲存後重新計算路線。

新增雨天專用強制路線：

1. 在側邊欄選擇「雨天路線」。
2. 開啟強制路線規則管理。
3. 新增規則並把「適用模式」設為「雨天路線」。
4. 使用 `osrm`、`manual`、`straight` 組合 `forward_segments`。
5. 若使用 `manual` segment，請確認對應 edge 已存在於 `campus_edges.csv`。

## 常見問題

### OSRM 路線無法生成

- 檢查 demo mode 是否阻擋 live OSRM。
- 檢查 `route_cache.json` 是否有該組路線快取。
- 確認起點與終點都有有效座標。
- 必要時允許 live OSRM 或忽略快取重新呼叫。

### 校園路線 fallback 到 OSRM

代表強制規則沒有命中，且本地校園 graph 沒有成功找到路徑。請檢查：

- `campus_edges.csv` 是否有連通路段。
- edge 是否 `enabled`。
- 單向或雙向設定是否正確。
- `places.csv` 是否缺少 graph 節點。

### 雨天路線沒有走自訂路段

雨天路線只有在命中雨天專用 forced rule 時才會走自訂段落。請檢查：

- 規則是否 `enabled=true`。
- 規則是否包含 `"modes": ["rain_friendly"]`。
- 起終點是否落在 `from_place_ids` / `to_place_ids`。
- 若使用 `manual` segment，對應 edge 是否存在且啟用。

### 地圖線段位置錯誤

通常是座標順序問題。請確認資料檔中的 geometry 使用 `[longitude, latitude]`，而不是 `[latitude, longitude]`。

### 地圖左鍵點選沒有出現新增表單

- 確認 sidebar 已打開「新增地點模式」。
- 點選地圖空白處後，等待 Streamlit 重新執行。
- 若畫面仍沒有更新，重新整理瀏覽器頁面。
- Folium 元件會回傳 `last_clicked` 或 `last_object_clicked`，點到 marker 或圖層物件附近時也應能讀取座標。

## 開發備註

- 不要在 OSRM 模式中加入 forced route 或 campus Dijkstra，這個模式應維持純 OSRM。
- 不要在雨天模式中加入天氣 API，目前雨天模式是手動選擇。
- 不要讓雨天模式在沒有 forced rule 時跑 campus Dijkstra，應回到純 OSRM walking。
- Compare 模式應保持 OSRM 與 campus 兩條路線獨立計算，避免互相污染結果。
- 既有 forced route 規則沒有 `modes` 欄位時，必須維持 backward compatibility。
- 地圖點選新增地點不可直接寫入 `data/places.csv`，必須先寫入 `data/manual_places_pending.csv` 待人工審核。
