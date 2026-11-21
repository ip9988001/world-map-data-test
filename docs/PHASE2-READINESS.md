# Phase 2 就绪检查单

> 出处：muse-000151（Phase 1a 修订单 T4）。**本文件只落检查单，不派单、不执行。**
> 所有条目默认 `state: pending`；每条都写「怎么算做完」（判据），不写「尽力」。
> 关联：`docs/PHASE2-REFACTOR-LIST.md`（D5-1 / D5-2 / D4-② / F16-CARRY）。

---

## 一、开工前 7 项必锁（未定稿不许开工）

| # | 项 | 状态 | 必须定稿到什么程度 |
|---|---|---|---|
| READY-1.1 | **rev4 最终定稿** | `pending` | `schema/SCHEMA.json` rev4 四列（completeness_tier / confidence_level / backfilled_fields / missing_reason）+ `coverage` 段冻结；`check_schema_rev.py --want-rev 4` rc=0；**开工前必须定稿** |
| READY-1.2 | **信源族归一化表与 Tier 重定义** | `pending` | Provenance Family → 票数映射表 + Tier S/A/B/C 与 L1/L2/L3 的对应表（见 refactor D5-1/D5-2）；**开工前必须定稿** |
| READY-1.3 | **Canonical Address Key** | `pending` | 归一化函数（大小写/缩写/方向/序数/unit 拆分）+ 碰撞率实测；`addr_id` 的哈希输入字段顺序固定；**开工前必须定稿** |
| READY-1.4 | **四段引擎段间契约** | `pending` | stage → fuse → backfill → publish 四段的输入/输出 schema、失败语义、幂等键（同一输入同 sha256）；**开工前必须定稿** |
| READY-1.5 | **县码基准表与特殊行政区映射** | `pending` | `config/baseline/counties_census.json`（3,144 县，已落）+ CT planning region（09110-09190）/ VA 独立市 / 领地排除口径；**开工前必须定稿** |
| READY-1.6 | **替代脊柱抽象接口** | `pending` | 脊柱（house_number + street）不可用时走哪条路（parcel / 点层 / TIGER 号段）的接口与降级阶梯；**开工前必须定稿** |
| READY-1.7 | **发布前硬阻断闸门与内存红线** | `pending` | 硬门禁清单（守恒 / addr_id 唯一率 100% / 坐标在县 bbox / F16 P0 关）+ 单进程内存红线（超限即 exit，不 swap 硬扛）；**开工前必须定稿** |

## 二、提前到 1b 之前的硬输入（先做，只读）

| # | 项 | 状态 | 做法与判据 |
|---|---|---|---|
| READY-2.1 | **全量空包普查** | `pending` | **只读**：扫全部现有产物（各 Release 的 ADDR-* / STATUS / MANIFEST），解压后统计字节数 / 行数 / `declared`；产出「0 字节资产」「0 行层」清单。判据：每个资产都有 `bytes / rows / declared` 三数，空包点名到层。**1b 与 Phase 2 的硬输入，先做** |
| READY-2.2 | **全美 Overture 血缘扫描** | `pending` | DuckDB 扫 Overture 全量 `GROUP BY region, dataset`（禁止 INSTALL spatial，几何走 cast AS VARCHAR）；产出族分布表（NAD 族 / OA 族 / 未知）。判据：每州每县的 nad 族占比可查。**1b 与 Phase 2 的硬输入，先做** |

## 三、第 8 项（发布闸门）两处补强

| # | 项 | 状态 | 补什么 |
|---|---|---|---|
| READY-3.1 | **未命中路径默认阻塞** | `pending` | 闸门遇到「不在白名单里的路径/未知分支」一律**阻塞**（fail-closed）；只有显式白名单放行。判据：造一条未知分支 → 闸门 exit≠0 |
| READY-3.2 | **合并前即时 re-check** | `pending` | 现在「合并前 30 分钟窗口」压到 **5–10 分钟**：merge 动作前当场重跑 `check_schema_rev` + 守恒 + F16 门禁，用当次结果说话，不吃旧绿。判据：re-check 脚本输出带时间戳且被写进合并回执 |

## 四、NH 重查 Step 0（先探活，再动手）

- **state**: `pending`
- **Step 0 探活（不许跳过）**：先查上游 NAD `State='NH'` 总行数及按 County 分组（`outStatistics`），
  确认上游到底有没有 NH 数据，再谈重跑。

| # | 步骤 | 状态 | 口径 |
|---|---|---|---|
| READY-4.1 | 上游探活 | `pending` | `State='NH'` 总行数 + `GROUP BY County`（outStatistics） |
| READY-4.2 | 取数通道优先级 | `pending` | ①官方静态整包（GeoParquet / FileGDB / CSV）②REST |
| READY-4.3 | REST 翻页纪律 | `pending` | **禁深翻 resultOffset**；用 `returnIdsOnly` 拉 OBJECTID 清单 + 游标分页 |
| READY-4.4 | 查询叠加条件 | `pending` | `State='NH'` **叠加县多边形**，另补 `County IS NULL` 兜底（防县字段空的行整批丢） |
| READY-4.5 | 落盘与断点 | `pending` | 按县 `.part` + `checkpoint_<fips>.json`；`raw_fetched == declared_upstream` 且四重对账 |
| READY-4.6 | 规模底线校验 | `pending` | NH 全州约 **64 万住房单元**（基准表实测 648,472）做底线校验：量级差一个数量级即判失败 |

## 五、gate 加固与超时分流

- **state**: `pending`
- **加固**：
  - READY-5.1 三态检测（活着 / 卡死 / 已完成）+ 心跳停滞告警
  - READY-5.2 结构化 JSON `ALL DONE`（机器可判，不靠人读日志）
  - READY-5.3 `flock` 锁防重入（同 workflow 不许并发两份）
  - READY-5.4 s1–s4 链式熔断（上游失败即断下游，不空转）
  - READY-5.5 gate.sh 托管（统一入口，不许各自手搓轮询）
- **超时分流**：
  - **A**：任务活着且进度慢 → **等**（不打断）
  - **B**：卡死且报错 → **先闭 t5 再修 t4**（先止血再修因）
  - **C**：仅 t4 限速且 t5 已闭合、三号空闲 → 可经**二号显式批准**手动放行 s1–s4

## 六、派单铁律代码化 wrapper

- **state**: `pending`
- **owner**: `phase2`（与 `/root/pi-work/bin/dispatch-guard.sh` 对齐）
- **内容**：
  - READY-6.1 **硬拦截低超时**：wrapper 拒绝 `timeout` 低于基线的派单（防止 60s 超时反复假失败）
  - READY-6.2 **校验结构化回执**：只认带 `run_id / status / head_sha / layers` 的结构化回执，
    文本「已派」不算；无回执即判派单失败
- **判据**：绕过 wrapper 直接 `gh workflow run` 的键在 CI 里不可用（或事后必被审计标记）

## 七、约束与风险（禁做项，不随阶段解锁）

| # | 项 | 状态 | 约束与判据 |
|---|---|---|---|
| READY-7.1 | **简化几何禁用于面积/长度计算** | `frozen`（红线，不适用 pending 流程） | 简化几何（simplified geometry）**禁用于面积/长度计算**；任何面积/长度计算必须改用未化简的 **cb（cartographic boundary）或 PL 文件**。依据 muse-000157 二；几何包选源留痕见 `config/baseline/county_geom_manifest.json`（仓内 `counties_geom.json.gz` 的 `max_allowable_offset_deg=0.001`、`coordinate_decimals=5` 即已化简，只够做 D2 点-in-县判定）。判据：面积/长度计算代码若引用 `config/baseline/counties_geom.json.gz` 或任何 `*_500k` / 化简几何源即判违规，必须改引未化简 cb 或 PL 文件 |

**详见 `docs/F16-RUNBOOK.md` → 末尾「几何选源红线」一节**（muse-000157 第二条原文 + 留痕≠授权的边界说明 + 判据）。
