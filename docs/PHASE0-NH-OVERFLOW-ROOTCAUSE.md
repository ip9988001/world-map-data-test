# PHASE0 · NH 溢出包 354,804 行定真因（只读排查）

- 排查时间：2026-11-22（UTC）
- 对象：`gold-US-NH-v1`（二仓产物）← `raw-US-NH-v1`（一仓输入，runner `39103107817`）
- 口径：**只读**。未改任何生产 `.py`、未改 schema、未删任何 Release/资产、未触发二仓任何 run。
- 一句话结论：**过滤器没坏**。354,804 行是**一仓 NAD 的「溢出包」**，其 `State` 字段实打实是 MA/ME/VT（0 行 NH），
  且 NH 10 个县的「主片」从来没被产出过（一仓账本 `shard_count=0`、`empty_counties` 10/10）。
  二仓 `overflow_by_county_field(0/354804)` 是**正确执行**了「按县名过滤」的结果，不是 bug。

---

## 一、复核现场（不抄，逐条重算）

### 1.1 354,804 由行级重算复现

数据源：一仓 Release `raw-US-NH-v1` 的 `NAD-US-NH-OUTOFSTATE.ndjson.gz`（48,832,338 B）。
逐行读 `State` 字段（354,804 行，无空值）：

```bash
gh release download raw-US-NH-v1 --repo ip9988001/World-US-Map-Data \
  --pattern "NAD-US-NH-OUTOFSTATE.ndjson.gz" --clobber
python3 - <<'PY'
import gzip,json,collections
c=collections.Counter(); n=0; blank=0
with gzip.open('NAD-US-NH-OUTOFSTATE.ndjson.gz','rt',encoding='utf-8') as f:
    for line in f:
        if not line.strip(): continue
        d=json.loads(line); n+=1
        s=(d.get('State') or '').strip().upper()
        if not s: blank+=1
        else: c[s]+=1
print(n, blank, dict(c), sum(c.values()))
PY
```

实测输出：

```
354804 0 {'MA': 140838, 'VT': 98291, 'ME': 115675} 354804
```

| 州 | 行数 |
|---|---|
| MA | 140,838 |
| ME | 115,675 |
| VT | 98,291 |
| **NH** | **0** |
| 合计 | **354,804** |

> 140,838 + 115,675 + 98,291 = **354,804** —— 与二仓 MANIFEST 的
> `source_manifest.quality.state_distribution` 完全一致（该字段就是对这个文件的只读统计）。

### 1.2 逐县 `nad_source` 原字符串（10 县全同）

```json
"nad_source": "overflow_by_county_field(0/354804)"
```

含义（`scripts/gold_coalesce.py:693-695`）：当上游只给了「溢出包」时，从溢出包里按 **县名字段**
过滤本县行，括号内 = `命中数/包内总行数`。10 个县全部 `0/354804`。

### 1.3 `oa_input` vs `oa_absorbed` 对照（逐县）

| 县 | 名称 | nad_input | oa_input | oa_malformed | oa_unendorsed_orphan | oa_dedup | **oa_absorbed** | output_rows |
|---|---|---|---|---|---|---|---|---|
| 33001 | Belknap | 0 | 40,057 | 40,057 | 0 | 0 | **0** | 0 |
| 33003 | Carroll | 0 | 50,843 | 50,843 | 0 | 0 | **0** | 0 |
| 33005 | Cheshire | 0 | 43,205 | 40,587 | 2,518 | 100 | **0** | 0 |
| 33007 | Coos | 0 | 24,935 | 24,935 | 0 | 0 | **0** | 0 |
| 33009 | Grafton | 0 | 59,887 | 59,887 | 0 | 0 | **0** | 0 |
| 33011 | Hillsborough | 0 | 168,706 | 134,895 | 29,875 | 3,936 | **0** | 0 |
| 33013 | Merrimack | 0 | 64,914 | 64,912 | 0 | 2 | **0** | 0 |
| 33015 | Rockingham | 0 | 127,406 | 122,192 | 4,960 | 254 | **0** | 0 |
| 33017 | Strafford | 0 | 46,078 | 46,078 | 0 | 0 | **0** | 0 |
| 33019 | Sullivan | 0 | 27,343 | 27,343 | 0 | 0 | **0** | 0 |
| — | **合计** | **0** | **653,374** | **611,729** | **37,353** | **4,292** | **0** | **0** |

守恒自检（二仓 `conservation.oa = true`，逐县成立）：

```
653,374 = oa_absorbed 0 + oa_malformed 611,729 + oa_unendorsed_orphan 37,353 + oa_dedup 4,292   ✅
```

### 1.4 总数块（二仓 MANIFEST `totals`）

```json
{"counties":10,"output_rows":0,"nad_input":0,"oa_input":653374,
 "ovt_input":266,"ovt_out_of_state":409023,"oa_in_zero_nad_counties":0,"conservation_ok":true}
```

`source_manifest.quality.state_in_scope_pct = 0.0`（`state_in_scope_rows = null`）。

---

## 二、候选①「过滤器没坏，是包内 0 行 NH、真因在上游缺主片」→ **成立（真因）**

三条独立证据：

### 2.1 同一个过滤器，喂非 NH 县名能命中 → 过滤器本身没坏

对溢出包按 `County` 字段计数（行级）：

```
NH 10 县县名命中数：{'Belknap':0,'Carroll':0,'Cheshire':0,'Coos':0,'Grafton':0,
                    'Hillsborough':0,'Merrimack':0,'Rockingham':0,'Strafford':0,'Sullivan':0}
非 NH 县名（Top10）：Essex 143,395 · York 78,319 · Windsor 21,116 · Oxford 18,966 ·
                    Orleans 18,126 · Caledonia 17,491 · Cumberland 14,940 · Orange 13,304 ·
                    Washington 13,060 · Windham 6,857
State 字段直方图：MA 140,838 / VT 98,291 / ME 115,675；State == "NH" 的 0 行
```

→ 过滤逻辑「`county` 字段 == 本县县名」能正常匹配（Essex/York 等命中十几万行），只是**包里没有一行属于 NH 的县**。

### 2.2 一仓账本自己写着「县片 0 片、10 县全空」

一仓 `raw-US-NH-v1` 的 `MANIFEST.json`（4.5 万字节）里，`ledger[nad]` / `sources[nad]` 原文关键字段：

```json
{"source":"nad","status":"ok","mode":"ids+county_shards","shard_count":0,
 "empty_counties":["33001","33003","33005","33007","33009","33011","33013","33015","33017","33019"],
 "failed_counties":[],
 "overflow_rows":354804,"overflow_ids":354804,"boundary_duplicate_rows":0,
 "total_rows":354804,"coverage_pct":100.0,
 "state_distribution":{"MA":140838,"ME":115675,"VT":98291},
 "state_in_scope_pct":0.0,"truncated":false}
```

`shards[]` 只有一条，`kind = "overflow"`、`county_key = "OUTOFSTATE"`：

```json
{"kind":"overflow","county_fips":null,"county_key":"OUTOFSTATE","rows":354804,"expected_rows":354804,
 "state_distribution":{"MA":140838,"ME":115675,"VT":98291}, ...}
```

一仓自己也留了警告（`completeness.nad.coverage_pct_superseded_note`）：

> 该 coverage_pct 由「县片行数 + 溢出包行数」比对上游 state count 得出；实测溢出包内落在本州县界内的点
> **仅 0 / 354,804（0.0%）**，故此值不可作为本州覆盖率解读

### 2.3 「主片到底有没有产出过」→ **没有**（不下载全量即已定案）

只用 **Release 资产清单 + 一仓 MANIFEST/账本** 即可回答：

| 检查 | 结果 |
|---|---|
| 一仓 Release `raw-US-NH-v1` 是否有「州内主片」资产（`NAD-US-NH.ndjson.gz` / `NAD-US-NH-NH*.ndjson.gz`） | **没有**；NAD 侧只有 `NAD-US-NH-OUTOFSTATE.ndjson.gz` + 列/图层元数据 |
| 一仓 NAD 分片数 `shard_count` | **0** |
| 一仓 NAD 空县 `empty_counties` | **10 / 10**（全部 NH 县） |
| 一仓 NAD `overflow_rows` / `total_rows` | 354,804 / 354,804（全部来自溢出包） |
| 二仓拿到的 `nad_input` | **0**（10 县全 0） |

→ 「上游打包缺主片」是事实，不是推测：**NH 主片一行都没产出过**，产出过的只有溢出包。

---

## 三、候选②「OA 653,374 行 absorbed=0 全丢 → 下游把 NAD 当唯一锚点、无 NAD 就整县归零」→ **不是真因（是后果）**

### 3.1 代码事实：OA 在这套口径里**只能投票**，本来就不能独立成行

`scripts/gold_coalesce.py`（输出行只由 NAD 行生成）：

```python
# 输出行 = nad_clean → by_key → rep（OA/VT/TIGER 只作为附加字段与置信度票）
for r in oa_rows:
    k = addr_key(r["num"], r["skey"], r["ukey"])
    if k in nad_keys:            # ← 只有 NAD 有这户，OA 才算一票
        oa_votes[k] += 1
    else:
        oa_bad["unendorsed_orphan"] += 1
funnel["oa_absorbed"] = sum(oa_votes.values())
```

`nad_keys` 为空（nad_input=0）⇒ 任何 OA 行都不可能被吸收。发布口径也写明「NAD 主干 + TIGER 60m 号段校验 +
OA 独立票；Overture 仅溯源不计票」（`RELEASE_NOTES.md`）。

### 3.2 数字事实：`absorbed=0` 里还混着两个「OA 自己不可用」的原因

- **611,729 / 653,374（93.6%）** 连 `number`/`street` 都解析不出（`oa_malformed`）。
  根因在一仓 OA 包本身：`OA-US-NH-statewide.zip` 的 `us/nh/statewide.csv` **610,582 行里
  NUMBER / STREET / CITY / REGION / POSTCODE 全为空**，只有 LON/LAT：

  ```
  rows 610582 empty NUMBER 610582 empty STREET 610582 empty CITY 610582 empty REGION 610582
  样例：{'LON':'-71.1860961','LAT':'44.4698989','NUMBER':'','STREET':'','CITY':'','REGION':'','POSTCODE':''}
  ```

  5 个 city 包才有真地址（auburn 2,318 / hampstead 3,490 / nashua 29,556 / jaffrey 2,853 / milford 4,596）。
- **37,353 行**是「地址可用但无处投票」（`oa_unendorsed_orphan`）：这 37,353 行才是「因 NAD=0 而失去归宿」的部分，
  **只占 5.7%**，不足以解释「整县归零」；归零的直接原因是 `nad_input=0`（候选①）。

### 3.3 反证小结

| 主张 | 检验 | 结论 |
|---|---|---|
| 「OA 全丢是根因」 | 若成立，州内应有 NAD 行被 OA 投票；实际 `nad_input=0`、10/10 县空 | ✗ 不成立（因果反了） |
| 「下游只用 NAD 当锚点」 | 代码确认 OA 只投票（`if k in nad_keys`） | ✓ 是设计事实，但它是**放大器**：让①的后果变成 0 行 |
| 「OA 本来能救」 | 93.6% 的 OA 行无 number/street；吸收上限也只有 37,353 行 | ✗ 救不了，即使 NAD 正常这 611,729 行也进不了库 |

**真因排序**：① 一仓 NAD 主片未产出（0/354804 命中、shard_count=0） → ② 二仓 OA 只投票（放大器，非根因）。

---

## 四、连带发现（不是本次真因，但必须在 Phase 0 记账）

1. **一仓 NAD 覆盖率门禁是「自证陷阱」**：`coverage_pct = (Σ县片 + 溢出) / 州 count`，
   而这一轮 `州 count` 恰好**全部**落在溢出包里，于是 354,804/354,804 = 100% 通过；
   真正该报警的「州内命中 0%」只写在 `coverage_pct_superseded_note` 里，没有挡任何东西。
   → 建议后续把「`state_in_scope_pct == 0` 且 `shard_count == 0` 且 `overflow_rows == official_count`」做成**硬 FAIL**。
2. **一仓 OA 包空壳**：`OA-US-NH-statewide.zip` 只有经纬度（610,582 行地址字段全空），
   city 包字段正常。金库侧若靠 OA 做票/补字段，必须先校验「number/street 非空率」。
3. **二仓 `coverage.nad_backed_counties = 10/10`** 是「相对上游声明」的覆盖，不是地理真值；
   NH 这轮实际是 0 有效县。下游读 `coverage` 时必须同时看 `state_in_scope_pct`。

---

## 五、复现清单（全部只读）

```bash
# 1) 一仓：资产清单 + 账本（不下载数据即可判定「主片没产出过」）
gh release view raw-US-NH-v1 --repo ip9988001/World-US-Map-Data --json assets
gh release download raw-US-NH-v1 --repo ip9988001/World-US-Map-Data --pattern MANIFEST.json
# 2) 二仓：逐县 nad_source / oa 漏斗
gh release download gold-US-NH-v1 --repo ip9988001/world-map-data-test --pattern MANIFEST.json
# 3) 行级重算 354,804（见 1.1 的脚本）
```

证据留存：`NAD-US-NH-OUTOFSTATE.ndjson.gz`（48.8 MB，sha256_gz `762f6e17…55a4c3`）、
`GOLD-MANIFEST.json`（12,368 B）、`raw MANIFEST.json`（45,404 B）。

---

## 六、只读声明

本轮**没有**改任何生产 `.py`、**没有**改 schema、**没有**删/建任何 Release 或资产、**没有**触发二仓任何 run。
本文件是唯一新增产物（docs 之下）。
