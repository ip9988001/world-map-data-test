# PHASE0 · Overture sources 字段抽检（CA / FL / TX / MA）

- 日期：2026-11-22
- 范围：**只读**。不改任何生产 `scripts/*.py`、不改 schema、不删任何 Release 资产、不跑 08/09/10b/几何、不触发二仓任何 run。
- 数据源：**二仓实际消费的那份** Overture，即一仓 Releases `raw-US-<ST>-v1` 里的 `OVERTURE-US-<ST>-<fips>-<key>.parquet`（`scripts/gold_scope.py:141-151` 的 `overture_files`，与 `gold_coalesce.py` 的 `read_parquet` 同一批文件）。
- 方法：真读 parquet（`pyarrow`，只取 `sources` / `address_levels` 两列），逐 feature 拆 `sources[]` 的 `dataset` / `provider` / `license` / `version`，**不是查文档**。

---

## 0. 一句话结论

**四州不同源，不能一刀切。**

| 州 | 抽检县 | 抽检行数 | `provider=nad` 占比 | NAD 行是否本州 | 判定：Overture 是否与 NAD 同源 |
|---|---|---|---|---|---|
| **TX** | 5 | 145,357 | **100.00%** | 145,357 / 145,357 | ✅ **完全同源 NAD**（TX 的 Overture 就是 NAD 的翻版，`version=20260930`） |
| **FL** | 5 | 192,605 | 0.44%（854 行） | 854 / 854 | ⚠️ **基本不同源**，少量 NAD 混入（仅 calhoun 一个县有） |
| **MA** | 5 | 351,494 | 2.50%（8,778 行） | **0 / 8,778** | ❌ **不同源**：NAD 行全是 NY/CT/VT 溢出（`address_levels[0]` 不是 MA），州内 100% OpenAddresses |
| **CA** | 5 | 265,953 | **0.00%** | — | ❌ **完全独立**（100% OpenAddresses，`LicenseRef-Public-Domain-US-CA-Law`） |
| 合计 | 20 | 955,409 | 16.22% | — | — |

一句话给 refactor：**若把 Overture 当「独立一票」，TX 是自证（NAD 计两次），CA 是真空票，FL/MA 要逐要素判**——正确做法是**按每个要素的 `sources[].dataset/provider` 逐条判同源**，而不是按州或全局开关。

---

## 1. 抽检方法（可复现）

```bash
# 1) 一仓 Release 里挑县级 parquet（各州 5 个县：2 个中等 + 3 个最小，覆盖城乡）
gh api repos/ip9988001/World-US-Map-Data/releases/tags/raw-US-CA-v1 \
  --jq '.assets[] | select(.name|test("OVERTURE")) | [.name,.size] | @tsv'
gh release download raw-US-CA-v1 --repo ip9988001/World-US-Map-Data \
  --pattern 'OVERTURE-US-CA-06009-calaveras.parquet' --dir /tmp/ovt
# …FL / MA / TX 同理（TX 在 raw-US-TX-v1-p1）

# 2) 真读 parquet，拆 sources[]
python3 - <<'PY'
import pyarrow.parquet as pq, collections
t = pq.read_table('/tmp/ovt/OVERTURE-US-TX-48003-andrews.parquet', columns=['sources','address_levels'])
srcs, lv = t.column('sources').to_pylist(), t.column('address_levels').to_pylist()
prov = collections.Counter(e['provider'] for s in srcs for e in s)
ds   = collections.Counter(e['dataset']  for s in srcs for e in s)
n    = len(srcs); nad = sum(1 for s in srcs for e in s if (e['dataset'] or '').upper()=='NAD')
print(n, 'rows →', dict(prov), '| NAD', nad, '%.2f%%' % (100*nad/n))
PY
```

抽检明细：CA `06009 calaveras / 06015 del_norte / 06017 el_dorado / 06049 modoc / 06091 sierra`；FL `12013 calhoun / 12019 clay / 12067 lafayette / 12123 taylor / 12125 union`；MA `25003 berkshire / 25007 dukes / 25011 franklin / 25015 hampshire / 25019 nantucket`；TX `48003 andrews / 48021 bastrop / 48033 borden / 48045 briscoe / 48101 cottle`。

---

## 2. 逐县实测

| 州 | fips | county | 行数 | provider 分布 | NAD 行 | NAD % |
|---|---|---|---|---|---|---|
| CA | 06009 | calaveras | 90,376 | open_addresses 90,376 | 0 | 0.00 |
| CA | 06015 | del_norte | 12,476 | open_addresses 12,476 | 0 | 0.00 |
| CA | 06017 | el_dorado | 150,789 | open_addresses 150,789 | 0 | 0.00 |
| CA | 06049 | modoc | 4,696 | open_addresses 4,696 | 0 | 0.00 |
| CA | 06091 | sierra | 7,616 | open_addresses 7,616 | 0 | 0.00 |
| FL | 12013 | calhoun | 12,791 | open_addresses 11,937 + **nad 854** | 854 | 6.68 |
| FL | 12019 | clay | 154,446 | open_addresses 154,446 | 0 | 0.00 |
| FL | 12067 | lafayette | 8,639 | open_addresses 8,639 | 0 | 0.00 |
| FL | 12123 | taylor | 8,395 | open_addresses 8,395 | 0 | 0.00 |
| FL | 12125 | union | 8,334 | open_addresses 8,334 | 0 | 0.00 |
| MA | 25003 | berkshire | 93,844 | open_addresses 85,396 + **nad 8,448** | 8,448 | 9.00 |
| MA | 25007 | dukes | 30,731 | open_addresses 30,731 | 0 | 0.00 |
| MA | 25011 | franklin | 87,096 | open_addresses 86,766 + **nad 330** | 330 | 0.38 |
| MA | 25015 | hampshire | 125,734 | open_addresses 125,734 | 0 | 0.00 |
| MA | 25019 | nantucket | 14,089 | open_addresses 14,089 | 0 | 0.00 |
| TX | 48003 | andrews | 7,973 | **nad 7,973** | 7,973 | 100.00 |
| TX | 48021 | bastrop | 134,238 | **nad 134,238** | 134,238 | 100.00 |
| TX | 48033 | borden | 718 | **nad 718** | 718 | 100.00 |
| TX | 48045 | briscoe | 1,202 | **nad 1,202** | 1,202 | 100.00 |
| TX | 48101 | cottle | 1,226 | **nad 1,226** | 1,226 | 100.00 |

### 2.1 MA 的 NAD 行是外州溢出，不是 MA 地址（关键）

按 `address_levels[0].value`（Overture 的州码）拆开 8,778 条 NAD 行：

| 州 | 该州文件中 provider=nad 的行 | 其中 `address_levels[0]` == 本州 | 其余（溢出到） |
|---|---|---|---|
| MA | 8,778 | **0** | NY 8,176 / VT 392 / CT 210 |
| FL | 854 | 854 | — |
| TX | 145,357 | 145,357 | — |
| CA | 0 | — | — |

即：**MA 州内 Overture 100% 来自 OpenAddresses（`dataset=us/ma/statewide`、`license=LicenseRef-Proprietary`），NAD 只以邻州溢出行的形式出现在马萨诸塞的文件里。** 若只看「文件里有 nad」就会误判 MA 同源——必须连 `address_levels` 一起看。

### 2.2 每条 feature 只有一个来源元素（无「一址多源」）

955,409 行里 `len(sources) > 1` 的行 = **0**。所以 Overture 侧没有「同一地址被多源合并」的痕迹，不存在「多源互证」可用。

### 2.3 license / dataset 取值（溯源指纹）

| 州 | license 分布 | dataset 形态 | 备注 |
|---|---|---|---|
| CA | `LicenseRef-Public-Domain-US-CA-Law` 265,868 / `LicenseRef-Proprietary` 85 | `us/ca/<county>`（按县切） | 加州州法公开数据，经 OpenAddresses 聚合 |
| FL | `LicenseRef-Public-Domain-US-FL-Law` 191,751 / `LicenseRef-Public-Domain-US` 854 | `us/fl/<county>` + `NAD` | 同上 |
| MA | `LicenseRef-Proprietary` 342,716 / `LicenseRef-Public-Domain-US` 8,778 | `us/ma/statewide` + `NAD` | **州级单一 proprietary 源**，粗粒度，不是县级 |
| TX | `LicenseRef-Public-Domain-US` 145,357 | `NAD` | 100% NAD，`version=20260930`（比 MA 溢出行的 `20250924` 新） |

样本（各州首行 `sources[0]`）：

```
CA  dataset=us/ca/amador     provider=open_addresses license=…-US-CA-Law      version=931508
FL  dataset=us/fl/calhoun    provider=open_addresses license=…-US-FL-Law      version=931077
MA  dataset=us/ma/statewide  provider=open_addresses license=LicenseRef-Proprietary version=909299
TX  dataset=NAD              provider=nad            license=…-Public-Domain-US version=20260930
```

---

## 3. 对「能不能当独立一票」的结论（refactor 输入，未改代码）

### 3.1 现状：不计票，但仍影响档位

- `scripts/gold_coalesce.py:7` 写「独立源计票：NAD / TIGER / OA 三票；**Overture 上游溯源 NAD，不计独立票**」。
- 实现上 `ovt_votes` 只在 `k in nad_keys` 时累加（`:770-774`），所以 Overture **不能凭空造地址**，不会重复计入地址总数——这一半是对的。
- 但它**会抬档位**：`:796-797` `tier = "S" if verify=="range" and (oa_votes[k] or ovt_votes[k]) else "A" if (oa_votes[k] or ovt_votes[k] or verify in ("range","street"))...`。TX 的 Overture 与 NAD 逐行同源，却仍能把 tier 抬到 S/A → **实质是「同源自证加分」**，只是没有重复计地址数。
- 另：`:888` 已把 `overture_upstream`（= `sources[1].dataset`）逐行写进产物，溯源信息是有的，可直接用于判同源。

### 3.2 本次实测修正了「Overture 上游溯源 NAD」这句全局断言

实测四州里**只有 TX 成立**（100%），CA 0%、FL 0.44%、MA 州内 0%。所以：

| 用法 | TX | FL | MA | CA |
|---|---|---|---|---|
| 当独立票（独立造地址） | ❌ 自证 | ✅ 可用 | ✅ 可用 | ✅ 可用 |
| 当「同源确认」（抬 S/A 档） | ❌ 自证，必须排除 | ⚠️ 99.6% 可用，854 行需排除 | ✅ 可用（州内无 NAD 行） | ✅ 可用 |

### 3.3 建议规则（供 stage→fuse→backfill→publish 拆分时落地，本次不动）

1. **同源判定按要素，不按州**：`sources[].dataset.upper() == "NAD"`（或 `provider == "nad"`）的 Overture 行，其 `ovt_vote` 必须当**NAD 自己那一票的重复**处理——要么丢弃、要么合并进 NAD 的 endorse 计数，但**绝不能与 NAD 计成两票/两档**。
2. 现成字段够用：`gold_coalesce.py` 的 OVT 缓存里已有 `upstream`（= `sources[1].dataset`，`:440-459` / `:548`），加一条 `if (r["upstream"] or "").upper() == "NAD": continue` 类守卫即可，无需改 schema。
3. `sources[1]` 只取首元素这件事本身是隐患：本次 955,409 行 `len(sources)>1` = 0，暂时无害；但一旦 Overture 上游开始合并多源，`sources[1]` 会悄悄丢掉第 2..n 个来源 → refactor 时应改为遍历全部元素判同源。
4. 分州风险登记：**TX 高风险（全自证）**、FL 低（仅 calhoun 6.68%）、MA 极低但**若按文件判会误判 9%**（berkshire 的 NAD 全是 NY 溢出）、CA 无风险。

---

## 4. 本次边界（没做的事）

- 未改 `scripts/gold_coalesce.py`（`:7` 的断言错误只登记，不改）、未改 schema、未改 workflow。
- 未跑 08/09/10b/几何，未触发任何 run，未往二仓融合任何数据。
- 只读一仓 Release 的 20 个 parquet（共 88 MB），未改任何 Release 资产。
- 抽检是**县级样本**（20 县 / 955,409 行），不是全州全量；结论按「样本实测 + 一致性极高（TX 5/5 县 100%、CA 5/5 县 0%）」给出，若要写进代码判据，建议再跑一次全州脚本级统计（另单）。
