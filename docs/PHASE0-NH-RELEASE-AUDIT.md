# PHASE0 · NH Release 13 资产核验（`gold-US-NH-v1`）

- 日期：2026-11-22
- 范围：**只读**。不动 `scripts/gold_coalesce.py`、不改 schema、不删任何 Release 资产、不跑 08/09/10b/几何、不触发二仓任何 run。
- 对象：二仓 `ip9988001/world-map-data-test` · Release `gold-US-NH-v1`（release_id `419203027`，tag 创建于 `2026-10-21T05:45:22Z`）
- 上游：一仓 `raw-US-NH-v1`（一仓 runner `39103107817`）

---

## 0. 一句话结论

13 个资产**全部下载实测**：10 个地址层的 `.ndjson.gz` 解压后一律 **0 字节 / 0 行**，解压内容 sha256 全等于 `sha256("") = e3b0c442…`；而 `MANIFEST.json` 自述的 `output_rows=0` / `output_bytes` / `output_sha256` 与实物**逐一相符**——自述没有撒谎。

假绿出在**语义层**：`STATUS.json` 的 `ok: true`、`counties_done` 10 个、`conservation` 全 `true`，证明的是「漏斗加总成立」（0 = 0 + 0 + 0 + 0），不是「有地址数据」。**假绿成立，且有实物 0 字节支撑，另有代码级成因三处（§4）**。

判定：这 10 层 **全部不能进二仓融合**（0 行，无内容可融），不是「融合失败」，是上游没给数据 → 列入「待一仓补采」。

---

## 1. 核验方法（可复现）

```bash
# 1) 资产清单 + 自述元数据
gh api repos/ip9988001/world-map-data-test/releases/419203027/assets --paginate \
  --jq '.[] | [.id,.name,.size,.state,.created_at] | @tsv'

# 2) 全量下载（13 个，共 14,994 字节）
gh release download gold-US-NH-v1 --repo ip9988001/world-map-data-test --dir /tmp/nh13 --clobber

# 3) 逐个实测：压缩字节 / 解压字节 / 行数 / sha256（压缩 & 解压两份）
python3 - <<'PY'
import gzip, hashlib, glob
for f in sorted(glob.glob('/tmp/nh13/*')):
    raw = open(f, 'rb').read()
    dec = gzip.decompress(raw) if f.endswith('.gz') else raw
    lines = dec.count(b'\n') + (0 if not dec or dec.endswith(b'\n') else 1)
    print(f.split('/')[-1], len(raw), len(dec), lines,
          hashlib.sha256(raw).hexdigest()[:12], hashlib.sha256(dec).hexdigest()[:12])
PY
```

判定口径（沿用三仓 `collect/ledger_rebuild.py` 的「资产即真值」原则）：**行数只认解压后逐行计数**，不接受任何 `STATUS.json` / `*.json` 里的自述数字；自述只用来做对照。

---

## 2. 13 个资产 · 自述 vs 实物 对照表

| # | asset | 自述 bytes（MANIFEST/API） | 实测 bytes | 实测解压 bytes | 实测行数 | sha256(实测前 12) | 自述 sha256 与实测 |
|---|---|---|---|---|---|---|---|
| 1 | `ADDR-US-NH-33001-belknap.ndjson.gz` | 57 | 57 | **0** | **0** | `e705a2f1ceb7` | ✅ 一致 |
| 2 | `ADDR-US-NH-33003-carroll.ndjson.gz` | 57 | 57 | **0** | **0** | `aa60c8f6fe12` | ✅ 一致 |
| 3 | `ADDR-US-NH-33005-cheshire.ndjson.gz` | 58 | 58 | **0** | **0** | `e0276310c038` | ✅ 一致 |
| 4 | `ADDR-US-NH-33007-coos.ndjson.gz` | 54 | 54 | **0** | **0** | `725fccc8b27c` | ✅ 一致 |
| 5 | `ADDR-US-NH-33009-grafton.ndjson.gz` | 57 | 57 | **0** | **0** | `d82b0a5152bf` | ✅ 一致 |
| 6 | `ADDR-US-NH-33011-hillsborough.ndjson.gz` | 62 | 62 | **0** | **0** | `91a5c70019c7` | ✅ 一致 |
| 7 | `ADDR-US-NH-33013-merrimack.ndjson.gz` | 59 | 59 | **0** | **0** | `b3757480f9b1` | ✅ 一致 |
| 8 | `ADDR-US-NH-33015-rockingham.ndjson.gz` | 60 | 60 | **0** | **0** | `a67b9cbbca8d` | ✅ 一致 |
| 9 | `ADDR-US-NH-33017-strafford.ndjson.gz` | 59 | 59 | **0** | **0** | `eebf900d17b8` | ✅ 一致 |
| 10 | `ADDR-US-NH-33019-sullivan.ndjson.gz` | 58 | 58 | **0** | **0** | `8133f7e42cc3` | ✅ 一致 |
| 11 | `MANIFEST.json` | 12368 | 12368 | 12368 | 482 | `549a89fbdfb8` | —（元数据） |
| 12 | `RELEASE_NOTES.md` | 1178 | 1178 | 1178 | 27 | `6e34bb28be33` | —（元数据） |
| 13 | `STATUS.json` | 867 | 867 | 867 | 68 | `1d81ad29d289` | —（元数据） |

合计：13 个资产 / 14,994 压缩字节 / **解压总字节 14,413（= 3 个元数据文件，地址层贡献 0 字节）**。地址层 10 个，实测行数全 0。

### 2.1 0 字节是「硬」的，不是解压失败

取 `ADDR-US-NH-33007-coos.ndjson.gz`（54 B）原始字节：

```
1f8b 0808 00000000 00ff   # gzip 头：mtime=0（代码刻意设的，保可复现），FLG=0x08 带 FNAME
"ADDR-US-NH-33007-coos.ndjson\0"
00 00 00 ff ff           # 空 stored block
03 00                    # 终止块
00000000                 # CRC32 = 0
00000000                 # ISIZE = 0  ← 解压后 0 字节，写死在这里
```

`ISIZE=0` + `CRC=0` + 10 个解压 sha256 全等于 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`（空内容 sha256）→ 空包无争议。**10 个层全部有实测行数（=0），验收项满足。**

### 2.2 自述侧逐字段对账

| 字段 | 自述值 | 与实物 |
|---|---|---|
| `MANIFEST.totals.output_rows` | 0 | 一致（实测 0） |
| `MANIFEST.counties[].output_bytes` | 57 / 57 / 58 / 54 / 57 / 62 / 59 / 60 / 59 / 58 | 逐一致 10/10 |
| `MANIFEST.counties[].output_sha256` | 10 个 sha256 | 逐一相符 10/10 |
| `MANIFEST.counties[].nad_source` | 每县都是 `overflow_by_county_field(0/354804)` | 一致（分子 0） |
| `RELEASE_NOTES.md` | 「合计：0 行 / 10 县」 | 一致 |
| `STATUS.json` | `ok: true`，`counties_done` 10 个，`conservation` 全 `true` | **不为假的是"数字"，为假的是"绿"**（§4） |

结论：这条链上**唯一没说真话的地方是「绿」这个语义**——所有数字都摆在那里，但 `ok:true` 会被下游当成「这州可以用了」。

---

## 3. 三个自述文件里的自证陷阱

1. `MANIFEST.coverage` = `{"total_counties":10,"nad_backed_counties":10,"zero_nad_counties":0,"note":"coverage 相对上游（一仓 NAD）声明，不是地理真值"}` —— `10/10 NAD-backed` 与「NH 实际 0 行」同时成立，因为分子分母都来自上游声明。
2. `MANIFEST.source_manifest.reference_check.three_number_check.matches = true` —— 公式「县并集 + 溢出 == 州官方 count」在「县并集 = 0、溢出 = 354,804」时依然咬合，且溢出行按 `state_distribution` 全是 MA 140,838 + ME 115,675 + VT 98,291（**NH 0 行**）。咬合通过 ≠ 有 NH 数据。
3. `RELEASE_NOTES` 的 `coverage：10/10 counties (NAD-backed) + 0 counties 0 upstream coverage` —— 「0 counties 0 upstream coverage」正是「没有县缺上游」的说法，而事实是 10 个县全部 0 行。

---

## 4. 假绿成因（代码级，`scripts/gold_coalesce.py`，只读定位，未改）

| # | 位置 | 代码 | 问题 |
|---|---|---|---|
| 1 | `:909-919` | `checks = {"nad": nad_input == output_rows + nad_malformed + nad_out_of_bounds + nad_dedup, ...}`；`conservation_ok = all(checks.values())` | 是**恒等式**，`0 = 0+0+0+0` 天然成立；输入全 0 时守恒必为真，与「有没有数据」无关 |
| 2 | `:1054` → `:1091` | `ok = all(r["conservation_ok"] …)` → `STATUS.json {"ok": ok, "counties_done": [全部县]}` | `ok:true` 只表达「算术对上」，`counties_done` 是「跑过」不是「跑出东西」 |
| 3 | `:1081` | `"nad_backed_counties": len(results)` | 直接等于**处理过的县数**，与 NAD 有没有行无关；而 `:675` 的 note 写「coverage.nad_backed_counties 不含这些县」——**注释承诺 ≠ 代码实现**（10 县 0 行也报 10/10） |
| 4 | `:901-908` | `oa_malformed = sum(...)`，OA 侧 `oa_input == oa_absorbed + orphan + malformed + dedup` | OA 侧同样成立：653,374 行输入全被判 malformed/orphan，守恒仍 `true` |

→ 排雷建议（**本次不改，只登记**）：二仓发布门禁必须加一条**非算术**判据，例如 `totals.output_rows > 0`，或 `output_rows / 上游声明的州 count` 低于阈值即 fail；否则任何州只要上游空，都会以「全绿零行」发版。

---

## 5. 判定：能不能进二仓融合（只登记，**未做任何融合动作**）

| 层（release asset） | 实测行数 | 判定 | 理由 |
|---|---|---|---|
| `ADDR-US-NH-33001-belknap` | 0 | ❌ 不能进融合 | 空包（0 字节 / 0 行） |
| `ADDR-US-NH-33003-carroll` | 0 | ❌ 不能进融合 | 同上 |
| `ADDR-US-NH-33005-cheshire` | 0 | ❌ 不能进融合 | 同上 |
| `ADDR-US-NH-33007-coos` | 0 | ❌ 不能进融合 | 同上 |
| `ADDR-US-NH-33009-grafton` | 0 | ❌ 不能进融合 | 同上 |
| `ADDR-US-NH-33011-hillsborough` | 0 | ❌ 不能进融合 | 同上 |
| `ADDR-US-NH-33013-merrimack` | 0 | ❌ 不能进融合 | 同上 |
| `ADDR-US-NH-33015-rockingham` | 0 | ❌ 不能进融合 | 同上 |
| `ADDR-US-NH-33017-strafford` | 0 | ❌ 不能进融合 | 同上 |
| `ADDR-US-NH-33019-sullivan` | 0 | ❌ 不能进融合 | 同上 |

**能进二仓融合：0 层。不能进：10 层。待补数据：10 层（全部卡在同一处上游）。**

待补数据的具体动作（不在本单范围，仅登记）：

1. 一仓 NAD：`state=NH` 过滤后命中 0 行，说明当前上游是「州 bbox 扫描 + 溢出」而非「按州过滤」，NH 要靠补采进入（真因见 `docs/PHASE0-NH-OVERFLOW-ROOTCAUSE.md`）。
2. 一仓 OA：`OA-US-NH-statewide.zip` 的 `us/nh/statewide.csv` 610,582 行里 `NUMBER/STREET/CITY/REGION/POSTCODE` 全空 → OA 独立票也补不上（下文 §6 的 37,353 行 orphan 是唯一残留线索）。
3. 补采后需**重跑二仓该州**，不是「补一个县」——10 个县同因。

---

## 6. 附录：OA 侧漏斗（不是 0，但也不可用）

`MANIFEST.totals`：`oa_input 653,374` / `ovt_input 266` / `ovt_out_of_state 409,023` / `output_rows 0`。
OA 守恒：`653,374 = malformed 611,729 + orphan 37,353 + dedup 4,292 + absorbed 0`。

| 县 | oa_input | oa_malformed | oa_unendorsed_orphan | oa_dedup | oa_absorbed | 输出行 |
|---|---|---|---|---|---|---|
| 33001 Belknap | 40,057 | 40,057 | 0 | 0 | 0 | 0 |
| 33003 Carroll | 50,843 | 50,843 | 0 | 0 | 0 | 0 |
| 33005 Cheshire | 43,205 | 40,587 | 2,518 | 100 | 0 | 0 |
| 33007 Coos | 24,935 | 24,935 | 0 | 0 | 0 | 0 |
| 33009 Grafton | 59,887 | 59,887 | 0 | 0 | 0 | 0 |
| 33011 Hillsborough | 168,706 | 134,895 | 29,758 | 4,053 | 0 | 0 |
| 33013 Merrimack | 64,914 | 64,912 | 2 | 0 | 0 | 0 |
| 33015 Rockingham | 127,406 | 122,192 | 5,075 | 139 | 0 | 0 |
| 33017 Strafford | 46,078 | 46,078 | 0 | 0 | 0 | 0 |
| 33019 Sullivan | 27,343 | 27,343 | 0 | 0 | 0 | 0 |
| **合计** | **653,374** | **611,729** | **37,353** | **4,292** | **0** | **0** |

读法：`oa_absorbed` 恒 0（OA 只当「独立票」，`if k in nad_keys: oa_votes[k]+=1`，`nad_keys` 空 ⇒ 无票可投）；37,353 行是**格式合格但无 NAD 主干认领**的 OA 行，将来一仓 NAD 补上后这批可重算，本次不计入任何可用地址数。

---

## 7. 三仓台账补登（本单第二产物）

**文件**：`ip9988001/world-map-data-33` → `collect/ledger/gold_nh_v1_rebuilt.json`（+ `collect/tests/test_gold_nh_ledger.py` 契约测试）

口径：**不新造格式**，直接沿用三仓既有的「资产即真值」台账 `collect-ledger-rebuild/v1`（`collect/ledger_rebuild.py` 产出的 `step04b_rebuilt.json` 同款），并把每条 record 补齐到 `collect-ledger/v1`（`collect/full_shard.py` 产出的片账本）必备字段，因此两种读取器都能直接吃。

| 项 | 值 |
|---|---|
| `schema` | `collect-ledger-rebuild/v1` |
| `stage` | `goldNH` |
| `tag_prefix` | `gold-US-NH-v1` |
| `layers_n` / `records` | 13（10 地址层 + 3 元数据） |
| `ok` / `empty` / `partial` / `failed` | 3 / **10** / 0 / 0 |
| `declared` / `rows`（只算地址层） | 0 / 0 |
| `assets_total` / `bytes_total` / `bytes_dec_total` | 13 / 14,994 / 14,413 |
| `assets_meta_lines` | 577（482 + 27 + 68） |
| `verdict.can_fuse_into_gold` | `[]`（空） |
| `verdict.cannot_fuse` / `pending_upstream` | 10 / 10 |

每条 record 的关键字段（例：`ADDR-US-NH-33011-hillsborough`）：

```json
{"layer": "US-NH-33011-hillsborough", "declared": 0, "declared_src": "MANIFEST.counties[].output_rows（release 自述）",
 "rows": 0, "rows_src": "asset_gunzip_line_count（实测）", "bytes": 62, "bytes_dec": 0,
 "sha256_actual": "91a5c70019c76323...", "sha256_claimed": "91a5c70019c76323...",
 "status": "empty", "reason": "release 自述 0 行、实测 gunzip 后 0 行…→ 不可融合，只能等一仓补采",
 "release_only": true, "source_truth": "github release asset（gunzip 实测）"}
```

要点：

- `status` **只取既有枚举**（`ok/empty/skipped_done/partial/failed`），空包一律 `empty`，绝不写 `ok`。
- `declared` / `rows` 顶层只算 10 个地址层（均 0）；3 个元数据文件的行数放在 `asset_lines` 与 `assets_meta_lines`，避免污染地址数加总。
- `layer` 用的是 release 资产名派生 id（`US-NH-33011-hillsborough`），带 `release_only: true` 标记，与三仓 ArcGIS 服务层 id（`..._FeatureServer_0`）不混。
- `assets_index` 逐资产留痕：`asset_id / size / bytes_gz / bytes_dec / lines / gzip_ok / sha256 / sha256_dec`。

**可读性验收**（三仓工作副本实跑）：

```bash
cd ip9988001/world-map-data-33
python3 -m unittest collect.tests.test_gold_nh_ledger -v
# Ran 6 tests ... OK   （顶层键与 step04b_rebuilt.json 同构 / 13 资产全实测 /
#                      record 合 collect-ledger/v1 / 0 行层不许 ok / 08 聚合口径加总 / verdict 空)
```

08 阶段聚合口径（`step_full_report.py` 的 rank+dedup）套上去的结果：聚合后 13 层，`{ok:3, empty:10}`，`declared 和 = 0`，`rows 和 = 0`，`gap > 0 的层：无`，`failed/partial：无`。

---

## 8. 本次边界（没做的事）

- 未修改 `scripts/gold_coalesce.py`、未改 schema（`schema_version` 仍 2.0）、未新增字段。
- 未删除/覆盖 Release `gold-US-NH-v1` 的任何资产（13 个原样，附件 `download_count` 之外无写操作）。
- 未跑 08/09/10b/几何，未触发二仓任何 workflow run。
- 台账登记见三仓 `collect/ledger/gold_nh_v1_rebuilt.json`（本单另一产物，只登记，不消费；08/09 阶段未跑、未改 workflow、未派单）。
