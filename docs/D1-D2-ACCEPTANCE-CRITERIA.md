# D1 / D2 验收判据（权威口径）

**本版取代 2026-11-22 前旧版（001175 版）；旧版不再并存、不再引用。**

- 定稿：2026-11-22（muse-000151 Phase 1a 修订单 T2）
- 仓内原先**无**权威处：`docs/`、`rules/`、`修复车间/` 全文检索无 D1/D2 判据记载（唯一命中是
  `GEMINI专用/…/05-四源字段对照总表.md` 里的「反向表 D1」，那是 TIGER 字段归属表，与此无关）。
  故本文件为新建的唯一定稿处。
- 唯一实现：`scripts/coverage_counters.py`（`d1_verdict()` / `county_boundary_check()` /
  `coverage_counters()` / `nad_substantive_threshold()`）。自测：`tests/test_d1_d2.py`。
- 契约引用：`schema/SCHEMA.json` 的顶层 `coverage` 段（`coverage_status` / `verification` /
  `counties_expected` / `status_fields`）。

> 一句话：**D1 管「这一层算不算 ok」，D2 管「覆盖率几成、按谁当分母」。**
> 两条都必须能点名到具体县/层，且都有「没数据不许当通过」的分支。

---

## D1 · 单层/单县数据是否 ok

判定式（逐字实现，不许自行扩写）：

```
ok = rows > 0
     and 守恒通过（该层的分源漏斗恒等式全部成立）
     and |raw_fetched - declared| / declared <= 0.005
```

- 完整率公差 **0.5%**（`TOLERANCE = 0.005`）。差值原因必须落进产物字段
  （`raw_fetched` / `declared` / `completeness_delta` / `completeness_ratio`），**不许只写在脑子里**。
- 旧版里「declared 大于零就直接放行」的那条或-分支**已删除**：只要完整率越界或 rows=0，
  就不得判 ok（NH 2026-11-21：10 个地址层全 0 字节，旧判据照样判「完整」）。

### 分支表（穷举，无第五种）

| 条件 | ok | coverage_status | verification | 附加动作 |
|---|---|---|---|---|
| rows>0，declared>0，守恒通过，完整率 ≤0.5% | true | `ok` | `verified` | 记 delta/ratio |
| rows>0，declared>0，完整率 >0.5% 或守恒失败 | false | `failed` | `verified` | warn 点名层/县 |
| rows>0，declared 缺失或 =0 | 可为 true | `ok` / `failed`（看守恒） | **`unverified`** | **必须**产出一条点名县或州的 warn；不许静默当 100% 完整 |
| rows=0，declared=0，**有**上游确认证据 | false | `empty_upstream_confirmed` | `verified` | 证据写进 `upstream_evidence` |
| rows=0，declared=0，**无**证据 / 与上游矛盾 | false | `empty_anomaly` | `verified`(declared=0) / `unverified`(缺失) | warn |
| rows=0，declared>0 | false | `failed` | `verified` | warn：上游说有数据我们一条没出 |

- **旧单值 `empty` 作废**：它把「上游确实没有」和「我们没抓到/抓坏了」混成一个字。
  历史产物（如 `docs/PHASE0-NH-RELEASE-AUDIT.md` 的 `{ok:3, empty:10}`）**只读不改、不回溯重算**；
  新产物一律出上面四种值之一。
- `verification` 是 **warn 级标记**（`verified` / `unverified`），**不是** `coverage_status` 的第五个值，
  不许塞进那个枚举（`check_schema_rev.py` 会断言）。

### D1 测试用例（`tests/test_d1_d2.py` 逐条落地）

| # | 输入 | 期望 |
|---|---|---|
| ① | rows=0，declared=0，全守恒，有上游证据 | ok=false，`empty_upstream_confirmed` |
| ② | 同 ① 但无证据 | `empty_anomaly`（不是 `empty`），带 warn |
| ③ | rows=1200，declared=1200，全守恒 | ok=true，`verified`，ratio=0 |
| ④ | rows=500，declared=0 | ok=true 可成立，但 `verification=unverified` + warn 留痕 |
| ⑤ | rows=99,000，declared=100,000 | ok=false，ratio=0.01，delta=1000 |
| ⑥（附加） | rows=0，declared=777 | ok=false，`failed` |

---

## D2 · 覆盖率怎么算

### 分母唯一

- 分母 = **`counties_expected`** = `config/baseline/counties_census.json` 按目标州过滤后的县行数
  （全美 3,144 县 = 50 州 + DC；领地不入表也不入分母）。
- `counties_done` / `counties_declared` **只作观测，绝不当分母**。它们是「我们干了多少」的自述数：
  上游缺县、资产缺失、addrfeat 缺失都会让它们变小，分母跟着变小 → 覆盖率永远 100%（自证）。
- 基准表的 `sha256`（只覆盖 `counties` 数组的规范化序列化）写在 SCHEMA 里，
  `python3 scripts/build_counties_baseline.py --check` 可离线复算。

### 计数前两道清洗（顺序不许颠倒）

1. **州码匹配**：行 `state` 与目标州不符 → 剔除，计数落 `excluded_state_mismatch`。
2. **县界空间校验**：点落在县多边形内（射线法，bbox 只做预筛）才算该县 →
   落在县外剔除，计数落 `excluded_out_of_county_geometry`。

先剔州再判县：溢出包（MA/VT/ME 的行混进 NH）不先剔掉，就会拿别州的点去问 NH 的县多边形，
既慢又会把边界噪声算成 NH 的行（`counties_with_any_rows` 虚增）。

### 县界几何从哪来（muse-000153：实现真校验，不许写 skipped）

**唯一几何来源：仓内全国县界小包** `config/baseline/counties_geom.json.gz`
（`{fips: [rings]}`，3,144 县全覆盖，5 位小数，gzip 头 mtime=0 → 可复算）
+ `config/baseline/county_geom_manifest.json`（vintage / source_url / sha256 / bytes / per-state 审计）。
生成器 `scripts/fetch_county_geom.py`（`--check` 可离线复算）。

选源过程（判据 = 全 3,144 县都有几何）：

| 次序 | 来源 | 实测 | 结论 |
|---|---|---|---|
| ① 一仓资产 | `World-US-Map-Data` 各 `raw-US-<ST>-v1` 里的 `TIGER-US-<ST>-county-<FIPS5>.geojson` | **51 州 / 3,138 县**，缺 6 个独立市：`24510` `29510` `51600` `51620` `51760` `51770` | 覆盖不全 → 不可单独用 |
| ② 全国小包 | `cb_2024_us_county_500k.zip`（www2.census.gov） | 本环境 **Cloudflare 403**（curl 全套浏览器头 + scrapling 都被拦） | 拿不到 |
| ③ 全国小包替代 | **TIGERweb** `State_County/MapServer/1`（Counties 图层，官方，`maxAllowableOffset=0.001` 服务端化简） | **51 州 / 3,144 县**，含 CT 09110-09190、MD/VA 独立市，与基准表逐 fips 对齐 | **采用** |

- `source_url`: `https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query`
- `geometry_sha256`: `d1f104a6eff7bdd05523b391de53ffc60c32bee045bea81f0719a074c5434e39`（整个 gz 文件；表体指纹见 manifest `combined.body_sha256`）
- `county_count`: **3144**，`missing`: **0**
- 缺几何 → `county_boundary_check` 返回 `missing_geometry`：该县行不计数、记 `missing_geom`、
  整轮 `coverage_status=failed` + `verification=unverified`。**禁止**返回 `skipped` 静默放过，
  也不许为凑校验去下载全量 TIGER/线层几何（本包仅 1.9 MB）。
- 自测里还保留仓内原始 Esri 样本 `data/dover/task001/tiger_boundary_kent_10' AND COUNTY.json`，
  用来证明 `rings_from_esri_json()`（Esri `geometry.rings` → rings）这条路也对。

### 6 个必须同时出的计数（键名逐字）

`counties_expected` / `counties_done` / `counties_declared` /
`counties_with_any_rows` / `counties_with_nad_rows` / `counties_nad_substantive`

配套计数：`excluded_state_mismatch` / `excluded_geom`（县外点）/ `missing_geom`（缺几何的县数，>0 即 failed）。
（派单原文列了 7 个名字，其中 `counties_done` 重复一次；去重口径见 SCHEMA `coverage.status_fields._dispatch_note`。）

### `counties_nad_substantive` 判定

```
县内 NAD 行数 >= max(10, ceil(0.01 × 分母))
分母：优先该县**总融合行数**；该县融合行数为 0 时退回该县 housing_units（基准表列）
```

- 10 行是绝对下限（1 行不算 NAD 背书）；1% 是相对下限（大县 500 行占 30 万行 0.17%，
  只覆盖一个角，不能让整县挂 NAD 背书）。
- 分母两种都缺 → 不计数也不当通过，落 null + warn。

### D2 测试用例（`tests/test_d1_d2.py` 逐条落地）

| # | 场景 | 期望 |
|---|---|---|
| ① | 10 县在 counties_done，只有 3 县有 NAD 行 | `counties_with_nad_rows=3`，`counties_with_any_rows=10`，分母仍 = 基准表 10 |
| ② | 某县 NAD 9 行 | 不进 `counties_nad_substantive`（阈值 10） |
| ③ | 同县 500 行、阈值 600 | 不进；补到 600 行（总融合行数不变）→ 进 |
| ④ | 溢出包全 MA/VT/ME 的行喂给 NH | 全部落 `excluded_state_mismatch`，`counties_with_any_rows` 不得虚增 |
| ⑤ | 真几何四类断言 | 县内点留 / 县外点剔（`excluded_geom=1`）/ `state_abbr` 不符先剔（`excluded_state_mismatch=1`，`counties_with_any_rows` 不虚增）/ 缺几何 → `missing_geometry` + `coverage_status=failed` + `verification=unverified`（**不是 skipped**） |
