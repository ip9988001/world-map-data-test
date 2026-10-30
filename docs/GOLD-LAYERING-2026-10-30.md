# 二仓 Gold 层结构核实：单层融合 vs staging + 融合两层（2026-10-30）

> 判据只用**可执行事实**（函数名 + 文件行号 + 落盘路径）。不读注释、不猜意图。
> 核实对象：`ip9988001/world-map-data-test`，分支 `feat/schema-rev3-geom`（= `main` + rev3）。
> 核实过程中**没有**下载任何一仓原始资产，**没有**派任何州级 run。

## 一、落盘边界逐段清点（一仓资产 → gold 产物）

一条地址的完整路径上，一共 **7 个落盘边界**，其中只有 **2 个**是「源数据中间产物」，而且都只是
**按县空间分桶**，不是 schema 契约化的 staging 表：

| # | 边界 | 读什么 | 写什么 | 代码位置 | 是否可复用 |
|---|---|---|---|---|---|
| 1 | 一仓 Release → 本地 raw | `gh release download $RAW_TAG -R World-US-Map-Data -D data/raw/US-<ST> --clobber`（**无条件全量**） | `data/raw/US-<ST>/`（NAD 县片、TIGER addrfeat/county 边界/places、OA zip、Overture parquet、MANIFEST/STATUS） | `.github/workflows/gold-coalesce.yml:151` | ❌ 每次 run 重下 |
| 2 | OA 全州 zip → 按县分桶 | `data/raw/US-<ST>/OA-*.zip`（**读原始 zip**） | `data/cache/US-<ST>/<zip名>/oa-US-<fips>.ndjson.gz`（原始列 + lon/lat，**未归一化**） | `bucket_oa_statewide()` `gold_coalesce.py:362`，落盘 `:402/:411`，缓存命中 `:373-375`（`all(p.exists())`，**无内容签名**） | ✅ 但键只看文件是否存在 |
| 3 | Overture 全州 parquet → 按县分桶 | `data/raw/US-<ST>/*.parquet`（duckdb，**读原始 parquet**） | `data/cache/US-<ST>/overture/ovt-US-<fips>.ndjson.gz` + `_stats.json` | `bucket_overture()` `:476`，sig `:486`，命中 `:491-497`，stats `:555` | ✅ 键 = 输入**文件名**拼接（无 size/hash） |
| 4 | ZCTA 面（二仓自闭环） | TIGERweb（`zcta_fetch.py`） | `data/cache/US-<ST>/zcta-US-<ST>.ndjson.gz` | workflow `:196` → `load_zcta()` `:286/:1032` | ✅ |
| 5 | scope 上下文 | `data/raw/US-<ST>/MANIFEST.json` + roster + registry | `data/gold/US-<ST>/scope.json`（**只有资产文件名与行政常量，没有数据行**） | `gold_scope.py:155-331`（写 `:352`），workflow `:165-168` | ✅ 不含数据 |
| 6 | **融合** | NAD 县片（原始）、OA 桶、OVT 桶、TIGER addrfeat（原始）、县界 rings（原始）、places（原始） | `data/gold/US-<ST>/ADDR-US-<ST>-<fips>-<key>.ndjson.gz`（**终产物**） | `process_county()` `:680`；读 NAD `:690`、OA `:729`、OVT `:754`、TIGER `:778`；写 `:927-935`，sha256 `:938` | ❌ 无第二趟，无中间表 |
| 7 | 账本 | 内存 funnel | `MANIFEST.json` / `STATUS.json` / `preflight.json` | `main()` `:1088-1089` | — |

关键事实：**NAD / TIGER addrfeat / 县界 rings / places 完全没有中间层** —— 它们在 `process_county()`
里**每县每次都从 `data/raw/` 原始资产读**（`:690`、`:778`、`:984/:994`、`:1034`）。
`gold_coalesce.py` 里 grep `staging|silver|bronze|normalized_table` = **0 命中**。

## 二、三个可证伪问题

### a. 新增第五源（三仓 `src_kind=parcel_situs`）要重跑什么？要重读一仓原始的步骤有几个？

**答案：≥ 4 处必读一仓原始资产 ⇒ 没有独立 staging 层。**

- 必须改：`process_county()`（`:680`）里加一路 situs 读取 + 投票 + tier；`gold_scope.py`（`:155`）把三仓
  Release 资产登记进 scope；workflow 加一次三仓下载步骤。
- 必须重跑且**必读一仓原始**的步骤（4 处，全部在融合路径上）：
  1. `read_nad(raw_dir / county["nad_file"])` `:690` —— 每县 NAD 县片原始 ndjson
  2. `read_addrfeat(raw_dir / county["addrfeat"])` `:778` —— TIGER 号段原始 zip
  3. `load_esri_rings(raw_dir / c["county_geo"])` `:984/:994` —— 县界原始 GeoJSON
  4. `load_places(raw_dir / scope["assets"]["places"])` `:1034` —— places 原始 zip
- 另外 workflow `:151` 无条件整包重下（`--clobber`），等于「第五源一来，一仓全量再下一遍」。
- 唯一能命中缓存的是 OA/OVT 分桶（`:373-375`/`:491-497`）与 ZCTA —— 只覆盖 2 个源，救不了主路径。

### b. 同州第二次跑（数据无变化）能否完全命中缓存而不重读原始资产？

**答案：不能。** 现有缓存键逐一列出：

| 缓存 | 键 | 是否有**源内容**签名 |
|---|---|---|
| OA 分桶 `cache/<zip名>/oa-US-<fips>.ndjson.gz` | 目录名来自 zip 文件名 + `all(p.exists())`（`:373-375`） | ❌ 只判存在 |
| Overture 分桶 `cache/overture/ovt-US-<fips>.ndjson.gz` | `_stats.json.sig == ",".join(文件名)`（`:486`） | ❌ 只有文件名，没有 size/hash/mtime |
| ZCTA `cache/zcta-US-<ST>.ndjson.gz` | Actions cache `gold-cache-<ST>-v1`（workflow `:160`，州级、无源签名、不可变） | ❌ |
| **NAD / TIGER / 县界 / places** | **无缓存** | — （`:690/:778/:984/:1034` 每次直读 raw） |
| **gold 输出** | **无 skip/resume** —— `main()` `:1042-1051` 对全部县无条件重算 | — |

⇒ 同州同数据第二次跑：OA/OVT/ZCTA 三处能省一次全州扫描，但**一仓 raw 仍会被整包重下**
（workflow `:151`），NAD/TIGER/县界/places **仍从原始资产逐县读**。也就是说「不重读原始资产」不成立。
额外风险：OA 桶只判存在、OVT 桶只比文件名 ⇒ 上游**同名换内容**时会静默复用旧桶（口径会错而不报错）。

### c. 融合逻辑与源内清洗是否同一段代码、同一趟扫描？

**答案：是 ⇒ 判定为单层融合。**

- 源内清洗是**读的时候内联做**的：`read_nad()` `:329`（`:336-352` 判号/街道键/unit/经纬度归一）、
  `read_oa_bucket()` `:419`（`:426-431` 解析 number/street_key/unit）、`read_ovt_bucket()` `:562`。
- 融合是同一函数体内紧接着做的：3 元组键 `addr_key() = number|street_key|unit_key`（`:159-162`）
  → 同址合并 `:718-727` → OA/OVT 投票 `:746`/`:770` → TIGER 校验 → tier 判定 `:796-797`
  → 直接组装输出行 `:854-886` → 写盘 `:927-935`。
- 中间**没有任何**「已归一化的地址表」落盘：不存在 `data/stage/…`、不存在 per-source 契约产物。
- ⚠️ 口径纠正（影响第五源怎么投票，但不改变 A/B 判定）：去重键**不是五元组**
  `(state, zip, street, number, unit)`，而是 **3 元组** `number|street_key|unit_key`，州/县由 scope
  隐式限定（`process_county` 单县作用域）。`zip/city` 只参与代表行打分（`nad_score` `:715-717`
  的 `zip5/unit/city/UUID 长度`），**不进键**。
- 另外：NAD 是唯一「脊柱」——OA/OVT 的 key 不在 `nad_keys` 里就进 `unendorsed_orphan`（`:748`、`:772`）；
  第五源若想投票，必须能产出与 NAD 对齐的 `number|street_key|unit_key`，否则只能当孤儿。

## 三、判词

**B —— 单层融合。** 加第五源必须重跑该州全流程（含重读/重下一仓原始资产），重读成本 > 0。

证据链一句话：`process_county()`（`gold_coalesce.py:680`）一个函数内完成「读原始 NAD `:690` → 读 OA 桶
`:729` → 读 OVT 桶 `:754` → 读原始 TIGER `:778` → 归一化 → 3 元组去重 → 投票 → tier → 写 gold `:927`」，
中间只存在「按县空间分桶」（`:402`/`:543`）与「scope 上下文」（`gold_scope.py:352`），**没有 schema 契约化的
staging 表**；且 workflow `:151` 每次无条件整包重下一仓资产。

## 四、要改成 A，需要动哪几处（只列清单，本次不动手）

1. **新增 `scripts/gold_stage.py`**：每源独立落 per-county 契约表 `data/stage/<src_kind>/US-<ST>-<fips>.ndjson.gz`，
   字段固定（`num/skey/ukey/lon/lat/zip5/city/unit/src_kind/src_layer_id/src_oid/src_upstream`），
   一源一份，互不覆盖。
2. **staging 写 `_MANIFEST.json`**：行数 + **源文件内容签名**（name+size+sha256/mtime）+ `stage_rev` + 生成时间。
3. **缓存判定换成签名比对**：`bucket_oa_statewide()` `:373-375` 的 existence-only、`bucket_overture()` `:486`
   的文件名 sig，都要升级成内容签名（否则同名换内容会静默复用旧桶）。
4. **归一化搬进 staging**：`read_nad()` `:336-352`、`read_oa_bucket()` `:426-431` 的清洗逻辑移入 stage 层，
   融合层禁止再做归一化。
5. **融合层只读 staging**：`process_county()` 里 `:690/:729/:754/:778` 四处读原始资产替换为
   `read_staged(src, fips)`；删掉对 `raw_dir` 的依赖（融合层不再认识一仓路径）。
6. **workflow 拆两个 job**：`stage`（下载 raw → 落 stage，缓存键含源签名）+ `fuse`（只读 stage → gold）。
   删掉 fuse 路径上的 `:151` 整包重下。
7. **gold MANIFEST 记录 `stage_rev` + 各源签名**：这样「加第五源只重跑 fuse」有可验证的输入指纹。
8. **补 writer**（现状缺口，见下）：`process_county()` 的 row 字典 `:854-886` 目前只写 **32 主字段 + 19 provenance**，
   rev2 的 `src_kind/src_layer_id/src_layer_url/src_parcel_id` 与 rev3 的 `rings_ref/geom_bbox` **一个都没写**
   （全仓 grep `src_kind|rings_ref|geom_bbox` 在 `*.py` 里 0 命中）——不补这个，即使只重跑融合层也产不出合规行。

## 五、对已产出 15 州的影响

15 州：`AL AR CO CT DC DE IA ME MT ND NH RI SD VT WY`（`gold-US-<ST>-v1`，四源基线对照组，本次保留不动）。

判词 B 下：第五源进来后，这 15 州**不需要重采**，但**必须重跑全流程**。

- 「不需要重采」：一仓原始资产仍在一仓 Release（`collect-step04/05/07/10` tag 都在），重跑只是
  **重新下载 + 重算**，不调用任何上游 API 采集。
- 「必须重跑全流程」：单层融合没有可增量 join 的 staging 表，唯一能 join 的中间产物是按县分桶的**原始列**
  （`:402`/`:543`），而 gold 行已把 `raw` 折叠成 32+19 字段。所以**不能**拿现有 gold v1 + 第五源做增量合并。
- 成本口径：≈ 该州一次完整 coalesce 的时间（下载 raw + 全州分桶 + 全县融合），不是一次全量采集的时间。
- 前置缺口：即使重跑，也**必须先补 writer**（`src_kind/src_parcel_id/rings_ref/geom_bbox` 未实现），
  否则第五源的行填不出溯源列，gold 仍不满足 rev2/rev3 契约。
