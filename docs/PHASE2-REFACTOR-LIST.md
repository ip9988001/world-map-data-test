# Phase 2 refactor 清单

> 出处：muse-000151（Phase 1a 修订单 T3）。本文件**只落条目、不写实现**。
> 每条统一字段：`state` / `owner` / `why` / `evidence`。
> 实现一律落在 `scripts/gold_fuse.py`（Phase 2 融合引擎），**不在 Phase 1b/1c 的 writer 里顺手改**——
> 现在改会把「写入层改造」和「计票口径重写」两件事混在同一批 diff 里，回归时无法二分定位。

格式约定：`state: pending` = 未开工；`owner: phase2` = Phase 2 融合引擎负责。

---

## D5-1 · 计票前先做 Provenance Family 归一化

- **state**: `pending`
- **owner**: `phase2`
- **why**: muse-000151 批示；实测依据 `docs/PHASE0-OVERTURE-SOURCES-PROBE.md`
  （20 县 955,409 行：TX 100% provider=nad，MA 州内 0%，FL 0.44%，CA 0%）。
  按「来源表数量」计票会把同一份 NAD 数两遍（Overture 镜像 NAD 再算一票），是自证。
- **内容**：
  - `gold_fuse.py` **不按「来源表数量」计票**，先做 Provenance Family 归一化：
    - Overture 行 `sources` 含 `nad` → **NAD 族**
    - 含 `open_addresses` → **OA 族**
    - 含未知 dataset → **告警并降级为补全源**（只补字段，**不参与投票**）
  - **同族内多条命中只计 1 票**（同一族的 N 条命中 ≠ N 张独立票）。
- **验收锚点**：同源州（如 TX）在归一化后 confidence_level 不得因 Overture 抬到 L1。

## D5-2 · Tier S 重定义（按族重算，不按表算）

- **state**: `pending`
- **owner**: `phase2`
- **why**: muse-000151 批示；旧「独立源 >= 2」是**按表**数的，与 D5-1 的族口径冲突。
- **内容**：
  - **Tier S 定义 = 精确点位源（NAD / OA / StateGIS）+ TIGER 独立校验**。
  - 旧「独立源 >= 2」**按族重算**，不许按表算；Overture 任何情况下 0 票（只留溯源）。
  - 与 SCHEMA `tiers.confidence_level` 的 L1/L2/L3 定义必须同步（族口径是 L1 的计票基础）。

## D4-② 修正 · 判定粒度改为「记录（Feature）级」，不按州设总开关

- **state**: `pending`
- **owner**: `phase2`
- **why**: muse-000151 批示。反例：**FL 存在单县混 NAD 的混合州**——同一州内有的县
  Overture 全镜像 NAD、有的县一条都没有。按州一刀切（整州「算/不算独立票」）必错：
  要么白送一票，要么白丢一票。
- **内容**：
  - 判定粒度 = **记录（Feature）级**，逐条看该要素自己的 `sources[]`；
  - **不设州级总开关**（禁止 `state_allowlist` / `state_overture_independent=true` 这类字段）。

## F16-CARRY · F16 门禁的三项 P0 未关项（承接，不在 Phase 2 前关）

- **state**: `pending`
- **owner**: `phase2`
- **why**: `config/f16_blockers.json` 里 P0 未关的三条必须有人接：**W2-019**（`street_key`
  三处硬错，15 州 gold 去重口径作废）、**W2-013**（缓存无内容指纹，静默复用旧桶）、
  **F16-LEDGER**（台账解析式判据未接）。Phase 1a 只落了门禁与清单，修的是 Phase 2。
- **内容**：三条各自修完 → 在 `config/f16_blockers.json` 把 `state` 改 `closed` 并附 `evidence`；
  门禁（`scripts/gold_preflight.py --bypass-f16` 之外的正路）才会放行。
- **entrypoint**: `config/f16_blockers.json` / `scripts/gold_preflight.py::f16_gate`
