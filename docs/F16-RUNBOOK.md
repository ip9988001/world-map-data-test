# F16 阻塞门禁 · bypass 运行手册（Runbook）

> 依据：muse-000152 第六节 ① ②（2026-11-22）。本文件是 `config/f16_blockers.json` +
> `scripts/gold_preflight.py --bypass-f16` 的**唯一人工流程规范**，与代码同等效力：
> 违反其中任一条的 bypass 一律无效，产物不得进 gold。
>
> 现行门禁语义（`scripts/gold_preflight.py::f16_gate`）：只有 `severity=="P0" and state!="closed"`
> 才拦截；退出码 0=封印 / 1=F16 阻塞或清单非法 / 2=上游未就绪。fail-closed：清单缺失、
> JSON 坏、schema 不对、blockers 空、条目缺 id、severity/state 越界、closed 无 evidence → 一律 rc=1。
>
> 当前 P0 未关三项：`W2-019`（street_key 三处硬错，15 州 gold 去重口径作废）、
> `W2-013`（缓存无内容指纹，静默复用旧桶）、`F16-LEDGER`（台账解析式判据未接）。

---

## 1. 谁能批 `bypass_f16=true`

- **只有一号（垚鑫鑫）本人可以批。**
- **二号无权自批自放**（二号可以提出「需要放行」的请求，但不能自己给批准）。
- **三号/任何自动化一律不得主动设置该输入**：workflow 的 `bypass_f16` 默认值必须保持 `false`，
  cron/schedule/其他 workflow 的 `workflow_call` 透传**不得**把它默认成 `true`。
- 批准必须留**一句原话**（例如：「本轮 NH 重跑先放行 W2-019，其余不算，2026-11-22T06:10Z，垚鑫鑫」），
  并原样引用进 PR 描述与 run 说明；**无原话引用 = 未批准**。

## 2. bypass 时 PR/run 描述必须留的五项（缺任一项则该次 bypass 无效）

1. `bypass_f16=true` 字样（逐字，便于机器检索）。
2. **被放行的阻塞编号**（`W2-019` / `W2-013` / `F16-LEDGER`，逐个列全，不许写「全部 P0」）。
3. **放行理由**（为什么必须先跑，例：NH 重查要用当前产物做上游探活，等 3 项全关会拖死 1b）。
4. **放行范围**（哪一轮 / 哪些州 / 哪些层 / 是否只跑一次）。
5. **批准人与批准时间（UTC）**（人名 + `YYYY-MM-DDTHH:MM:SSZ`）。

> 缺任一项 → 该次 run 的产物**不得进 gold**（不得合并、不得发 Release、不得当基线）；
> 事后补写不算补齐，只能重跑一次。

## 3. bypass 记录落到哪个账本

- **账本文件（仓内，append-only）**：`config/f16_bypass_ledger.jsonl`
  - 一行一条 JSON，字段固定（顺序不限，键名逐字）：
    ```json
    {"ts_utc":"2026-11-22T06:10:00Z","run_id":"44999999999","workflow":"gold-coalesce.yml",
     "operator":"pi-agent-3","approver":"垚鑫鑫","blockers":["W2-019","W2-013","F16-LEDGER"],
     "reason":"NH 重查上游探活需要当前产物","scope":"一轮 / NH / 全部地址层 / 只跑一次"}
    ```
  - 只许 append，不许改历史行；改历史行 = 伪造记录。
  - 谁来写：`operator`（发起 run 的人/代理）在 dispatch **之前** append；若当轮无写权限，
    必须在同一 PR 里补记并在 run 说明里写「账本行待补 → PR #NNN」。
  - 为什么没有沿用旧路径：仓里此前**没有** F16 豁免账本文件（`config/f16_blockers.json` 只是阻塞清单；
    `ledger` 字样只出现在 `F16-LEDGER` 这条待办的判据描述里），故在本文件新建并写死此路径。
- **同时保留现有机制（不删不改）**：
  - `gold_preflight.py::f16_record` 写入 `$GITHUB_STEP_SUMMARY` 的那段（含 `bypass_f16：**true**` 与未关闭编号）；
  - `--json-out` 产出里的 `f16: {bypassed, open_p0, counts}` 字段。
  - 即一次合法的 bypass 会同时留下**三处痕迹**：step summary、preflight.json、本账本。

## 4. 红线

- **bypass 只放行本次运行**：它不改变任何阻塞项的状态。
- **不许改 `config/f16_blockers.json` 里任何 `closed` 状态**来「配合」bypass；
  关阻塞只有一条路：修完 → 带 `evidence` 走 PR → 门禁自己变绿（`closed` 缺 `evidence` 时清单判非法，rc=1）。
- 不许把 `bypass_f16` 默认值改成 `true`，不许在 workflow 里加「自动判断可绕过」的分支。
- 一次 bypass 对应一次 run；跨轮复用同一句批准 = 无效。

## 5. 实操（照抄即可）

```bash
# 1) 先跑门禁，确认当前未关闭 P0 清单（不带 bypass，红了才是正常）
python3 scripts/gold_preflight.py --manifest <MANIFEST.json> --state NH --json-out /tmp/preflight.json

# 2) 拿到一号原话批准后，先记台账（append 一行）
cat >> config/f16_bypass_ledger.jsonl <<'JSON'
{"ts_utc":"2026-11-22T06:10:00Z","run_id":"PENDING","workflow":"gold-coalesce.yml","operator":"<who>","approver":"垚鑫鑫","blockers":["W2-019"],"reason":"<why>","scope":"<scope>"}
JSON

# 3) 手动 dispatch 并显式传 bypass_f16=true（dispatch 的 choice 默认仍是 "false"）
gh workflow run gold-coalesce.yml -R ip9988001/world-map-data-test \
  -f state=NH -f bypass_f16=true

# 4) run 结束后把真实 run_id 回填进账本（新增一行修正行，不改旧行）
```
