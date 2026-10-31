# 二仓重启 checklist（2026-10-31 立）

> 背景：二仓自 2026-10-2x 起停摆（等第五源）。停摆期间不做「没人跑的新代码」，但**重启前必须补齐的项列在这里**，按顺序做，不许跳。

- [ ] **1. 接 F16 故障清单门禁 + 先读三份清单**（前置，别的都不许先跑）
  - 把三仓 `collect/preflight_dispatch.py` 的 `parse_failure_ledger()` / `judge_failure_ledger()` 接到本仓 `scripts/gold_preflight.py`
    （台账路径 = 本仓 `docs/WORKFLOW-FAILURE-LEDGER.md`；**复用同一份实现**，不要另写一份，否则两份判据会分叉）。
  - 判据（与三仓一致，2026-10-31 版）：复发 ≥2 且未规避 → FAIL；复发 ≥2 且已规避 → WARN（打印修复 sha + 验证方式）；
    未规避且复发 = 1 → WARN；台账缺失 / 表解析失败 → FAIL；`--ledger-waive 编号=理由`，空理由拒绝执行。
  - **先读三份清单**：本仓 `docs/WORKFLOW-FAILURE-LEDGER.md` + 一仓 `World-US-Map-Data/docs/WORKFLOW-FAILURE-LEDGER.md` + 三仓 `world-map-data-33/docs/WORKFLOW-FAILURE-LEDGER.md`。
  - 完成判据：`python3 scripts/gold_preflight.py --ledger-category 账本与口径` 能打出 `ledger_hits[]`，且空理由 waive 返回 rc=2。

- [ ] 2. 第五源接入：schema 判词与 `current_state` 护栏（见 `docs/GOLD-LAYERING-2026-10-30.md`）先过一遍，再跑 gold-coalesce。
- [ ] 3. 缓存内容寻址未修（`W2-013`）：`gold-cache-<ST>-v1` / OA 包名目录 / Overture 固定单目录 三者都没有 size/hash/mtime，
      重启首跑前要么修掉，要么在派单里写清「本次不会换同名包」并留证据。
- [ ] 4. 首个 run 用 `publish=0` 干跑一遍，确认 `MANIFEST.json` / `STATUS.json` 语义没变再发布。
