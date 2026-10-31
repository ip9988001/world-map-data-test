# WORKFLOW 故障清单 · 世界地图二仓（world-map-data-test）

> 立规：2026-10-31。用户原话：**每个仓建一份 workflow 故障清单，写之前必查、跑后必补。**
> 本文是该仓 workflow 的**唯一故障台账**（唯一真值）。别处写的「踩坑记录」一律以本文为准并回链到编号。
>
> **本表条目以代码 / 文档可复核证据为准，记忆与传闻不入表**（复核不了的标「待复核」，不进结论）。
>
> ### TODO（二仓重启前必做，重启 checklist 第 1 项）
> 1. **接 F16 门禁**：把 `collect/preflight_dispatch.py`（三仓 `docs/failure-ledger` 分支）的 **F16 故障清单判据**接到本仓 `gold_preflight.py`
>    （台账路径 = 本仓 `docs/WORKFLOW-FAILURE-LEDGER.md`；建议直接 import 或复制 `parse_failure_ledger` / `judge_failure_ledger`，不要另写一份）。
>    判据：复发≥2 且未规避 → FAIL；复发≥2 且已规避 → WARN；台账缺失 / 表解析失败 → FAIL；`--ledger-waive 编号=理由` 空理由拒绝执行。
> 2. **先读三份清单**：本仓本文 + 一仓 `World-US-Map-Data/docs/WORKFLOW-FAILURE-LEDGER.md` + 三仓 `world-map-data-33/docs/WORKFLOW-FAILURE-LEDGER.md`（二仓吃的就是两头的产物）。
> 3. 为什么现在不接：二仓自 2026-10-2x 起停摆（等第五源），接了没有触发场景，只会变成没人跑的代码。**重启前必须补。**
>
> 三条铁律：
> 1. **写之前必查**：派单前先查本文 + 本次涉及的类别，派单里写 `故障清单已查：<编号列表 | 无>`，没有这行视为无效派单。
> 2. **跑后必补**：新踩的坑**当天**补进本文（含错误原文关键行、证据路径、修法、验证方式、关联提交），**不许事后凭记忆补**。
> 3. **补完提交**：commit message 写 `ledger: +N <类别>`（例如 `ledger: +1 缓存与签名`）。
>
> 类别固定 10 个：`并发队列` `artifact与下载` `git提交` `账本与口径` `checkpoint与断点` `切分与体积` `采集器逻辑` `上游不可达` `缓存与签名` `测试与CI`。
> 二仓没有 checkpoint 机制（不采集、只加工），`checkpoint与断点` 一栏**允许长期为空**，不用硬凑。

## 0. 本仓 workflow 骨架速查（写之前先看这一段）

- **主力 `gold-coalesce.yml`**：`workflow_call`（被 matrix 调）+ `workflow_dispatch`；输入 `state` `tag` `counties` `publish` `分卷模式 auto`；**单 Job 顺序跑多县**，共用一份 Overture/OA/ZCTA 本地缓存（Actions cache key **`gold-cache-<ST>-v1`**）；产物 = 本仓 Release `gold-US-<ST>-v1`：`ADDR-US-<ST>-<fips>-<county_key>.ndjson.gz` + `MANIFEST.json` + `STATUS.json`。
- **`gold-coalesce-matrix.yml`**：多州矩阵，按 `tag 前缀（默认 raw-US-）+ <ST>-v1` 拼一仓 tag。
- **专项**：`dover-fetch.yml` / `dover-full-release.yml` / `task001.yml` / `task003-golden.yml` / `task004-statewide.yml`（人工 dispatch，产物各不相同）。
- **输入端**：只读一仓 Release `raw-US-<ST>-v1`（可 `-pN` 分卷，`auto` 自动发现并合并）；**绝不改动一仓**。
- **自检**：**没有 ci-smoke、没有 check_docs**（这是事实，见 W2-015）。验收只能：`python3 -m unittest discover -s tests`、`python3 -m compileall scripts bots`、`python3 -c "import yaml;yaml.safe_load(...)"` 逐 workflow 解析。
- **发布铁律**：分源独立记账（NAD/OA/OVT 三本账各自守恒），任一不守恒 → `exit 1` 不发版；`STATUS.phase` 有 `collecting / complete / complete_partial` 三种语义。

## 1. 台账

| 编号 | 发现日期 | 类别 | 症状（错误原文关键行） | 根因 | 影响（数据/账本/时间/假红） | 修法 | 验证方式 | 关联提交 | 复发次数 |
|---|---|---|---|---|---|---|---|---|---|
| W2-001 | 2026-10-2x | 采集器逻辑 | G1：溢出型州（NH）生产崩 `TypeError: unsupported format string passed to NoneType.__format__` | `nad_rows` 为 `None` 时仍用 `f"{nr:>7}"` 格式化 | 数据：整州跑不完；时间：一次全州重跑 | `isinstance(nr, int)` 才格式化，否则占位 `—` | 用「溢出型州」（`nad_rows=None`）跑通单州；`gold_scope.py:359` 分支被覆盖 | 见 `scripts/gold_scope.py:357` 注释（修 G1） | 0 |
| W2-002 | 2026-10-2x | 账本与口径 | G2：AK「county 与 overflow 都空」，而 Release 里 **23 个县片都在** | scope 只读 `MANIFEST.assets`，不从实物（`shards[]`）重建 | 账本：整州被判 0 县；数据在但取不到 | 以 `shards[]` 为准补县片（`county_fips`/`fips`/文件名三种写法都认） | 对 AK：`scope.json` 县数 = Release 县片数；`preflight.json` 无「县片 0」 | 见 `scripts/gold_scope.py:161-175`（修 G2） | 0 |
| W2-003 | 2026-10-2x | 账本与口径 | G3：ID 的 `assets` 漏记 addrfeat（**实物 43 个在**）→ 旧逻辑整州拒跑 | 把「账本没写」当「实物没有」 | 数据：整州不跑（最贵的假红） | 缺 addrfeat 只 WARN（`addrfeat N 个 < 县片 M 个（缺失县会被 scope 跳过）`），不拒跑；以实物为准 | `gold_preflight.py` 对 ID 出 WARN 而非 exit 1；该州能出 gold | 见 `scripts/gold_preflight.py:40,139-141` | 0 |
| W2-004 | 2026-10-2x | 测试与CI | G4：preflight C4 把州级三数 `matches=False` 直接判失败，与一仓「州级三数仅参考」口径冲突 | 门禁口径与上游口径不一致 | 假红：一仓自己都说仅参考，二仓却卡死 | C4 降级为 WARN（`一仓口径下仅参考，不阻断`） | 构造 `matches=False` 的州，preflight 仍 `ok` | 见 `scripts/gold_preflight.py:100-105`（修 G4） | 0 |
| W2-005 | 2026-10-21 | 采集器逻辑 | G5：`index_assets()` 里 `a["overture"] = name` 覆盖赋值 → 按县分片形态下**只剩最后一个县**，其余县静默拿不到 Overture | 循环里覆盖式赋值，没区分「州级单文件」与「按县分片」 | 数据：除最后一个县外全部缺 Overture（静默）；账本：OVT 计数偏低但守恒不报 | 分片入 `overture_files[]`；州级单文件优先占 `overture`，只有县片时仅用于「有没有」判空 | 多县州跑完 `overture_files` 数 = Release 分片数；每县 OVT 行数 > 0 | 见 `scripts/gold_scope.py:143-152`（★ 2026-10-21 修 G5） | 0 |
| W2-006 | 2026-10-2x | artifact与下载 | G6：只认 `raw-US-<ST>-v1`、不认 `-pN` 分卷 → 德州**只拉第一卷**（`TX-p2` 的 4,958,127 行没进来） | tag 精确匹配而不是前缀 + 分卷枚举 | 数据：整卷缺失（且看着成功） | `分卷模式 auto`：发现 `raw-US-<ST>-v1-p*` 并合并；留空 = 单卷旧行为 | 德州跑完 `MANIFEST` 里卷数 ≥ 2；行数与各卷之和一致 | 见 `gold-coalesce.yml` 的 `分卷模式` 输入 | 0 |
| W2-007 | 2026-10-21 | 账本与口径 | G7：不读一仓 `STATUS.phase=complete_partial` 与 `failed_counties` 硬语义 → 把「上游显式放行缺县」当故障，或把「还在采」当完成 | 只看到「齐/不齐」，没读 phase 与失败县清单 | 账本：结论反了（该跑的没跑 / 不该跑的跑了） | 读 `phase`：`collecting` → 等（exit 2 路径）；`complete_partial` → WARN 并带 `failed_counties`；`complete` → 放行 | 构造三个 phase 的 MANIFEST，三种结论都对 | 见 `scripts/gold_preflight.py:71-85`（修 G7） | 0 |
| W2-008 | 2026-10-21 | 测试与CI | G8：exit 2（上游未就绪）被当 failure 报警，哨兵半夜响 | 只判「0 / 非 0」 | 假红：等一等的事被当故障 | `rc=2` → `ready=false` 跳过后续，**不报红、不上哨兵** | 上游还在采时跑一次：`ready=false` 且 job 绿 | 见 `gold-coalesce.yml:120-125`（★ 2026-10-21 修 G8） | 0 |
| W2-009 | 2026-10-2x | 测试与CI | G9：无离线自测 → 改一行脚本只能靠真跑全州验证 | 没有测试骨架 | 时间：每次改动都烧一次全州；质量：回归靠运气 | 加 `tests/test_gold_offline.py`（离线夹具 + 纯函数断言） | `python3 -m unittest discover -s tests` 全绿，且不联网 | 见 `tests/test_gold_offline.py` | 0 |
| W2-010 | 2026-10-2x | 采集器逻辑 | G10：文件名硬切认县（`parts[3]` / `parts[-1]`），清单里明明有 fips 字段却不用 | 只按命名约定解析，约定一变就错位 | 数据：县与文件错配（按县写错桶） | 优先读清单里的 fips 字段，文件名解析只作兜底；解析不出必须报错不许猜 | 造一个命名不符合约定但带 fips 的清单，仍能正确分县 | 未修（现状：`scripts/gold_scope.py:124,129,134` 仍是 `parts[3]`/`parts[-1]`） | 0 |
| W2-011 | 2026-10-2x | 采集器逻辑 | G11：`zero_nad_counties[].oa_rows` 恒 `None`（假字段）→ 报表里「0-NAD 县的 OA 行数」永远是 0 | 字段只被读、没被写 | 账本：假字段误导判断（以为 0-NAD 县没有 OA 行） | 扫描时把每县的 `zero_counts` 回填 `c["oa_rows"]` | 0-NAD 县报表里 `oa_rows` 与实际分桶行数一致 | 见 `scripts/gold_coalesce.py:1016-1017`（回填） | 0 |
| W2-012 | 2026-10-2x | 采集器逻辑 | G12：失败州只能整批重跑，没有「只跑失败州」入口 | 没有按 Release 实物反推状态的工具 | 时间：一次失败要全矩阵重跑 | `scripts/list_failed_gold.py`：按 Release 实物判 `never / incomplete / failed`，可直接输出 `--states` 串 | `list_failed_gold.py --all --format states` 能列出失败州并喂回 matrix | 见 `scripts/list_failed_gold.py` | 0 |
| W2-013 | 2026-10-2x | 缓存与签名 | 同名换内容会**静默复用旧桶**：OA 桶按包名目录（`cache_dir/OA-.../`）、Overture 桶固定 `cache_dir/overture/`（多包互相覆盖）、Actions cache 键 `gold-cache-<ST>-v1` —— **三者都没有 size/hash/mtime** | 缓存键只有文件名/固定名，没有内容指纹 | 数据：用旧桶算出「新」结果，分源守恒不报错（最坑的一种静默错） | 缓存键加内容指纹（`size+mtime` 或上游 ETag/资产 id）；Overture 桶按包名分目录；命中前校验 | 换一版同名 OA 包后跑一次：桶被重建（日志有 cache miss），行数随之变 | 未修 | 0 |
| W2-014 | 2026-10-2x | 采集器逻辑 | 单层融合：清洗与融合**同函数同扫描**，无 staging 层 → 加第五源必整州重跑（4 处直读一仓原始数据） | 没有「清洗产物」这一层，融合直接读原始 | 时间：加源/改源 = 全州重跑（每州数十分钟）；风险：改一处动全身 | 拆 staging（清洗 → 归一 → 3 元组键）与融合；融合只读 staging | 加一个源只需重跑 staging 之后阶段（用耗时对比证明） | 见 `docs/GOLD-LAYERING-2026-10-30.md`（方案已写，未实施） | 0 |
| W2-015 | 2026-10-31 | 测试与CI | 本仓**没有 CI**：无 `ci-smoke.yml`、无 `check_docs.py`，只有 7 个业务 workflow | 立仓时没接自检 | 质量：改动无自动闸门；**别拿「ci-smoke 绿」当门槛**（本仓没有） | 验收固定三件套：离线 unittest + `compileall` + 逐 workflow `yaml.safe_load`；后续可加 `ci-smoke.yml`（照三仓） | 三件套全绿；`ls .github/workflows` 能数出业务 workflow 数 | 未修 | 0 |
| W2-016 | 2026-10-30 | 账本与口径 | 去重键被写成 5 元组（`state, zip, street, number, unit`）→ 与实现不符（实现是 3 元组） | 文档口径与 `addr_key()` 实现漂移 | 账本：对外说明错，跨源投票结论被误读 | 唯一口径：**3 元组** `number` + `street_key` + `unit_key`（`addr_key()`，`gold_coalesce.py:159-162`）；州/县由 scope 决定，不进键 | 文档与代码一致；抽 100 条重复地址核对去重结果 | 见 `docs/GOLD-LAYERING-2026-10-30.md:64-73` | 0 |
| W2-017 | 2026-10-2x | 采集器逻辑 | Overture 只有县片、没有州级单文件时，`a["overture"]` 被**占位成某个县片**；若下游把它当「州级单文件」读，就只处理一个县 | 一个字段承担两种语义（「有没有」与「用哪个」） | 数据：静默只处理一个县 | 下游一律用 `overture_files[]` 遍历；`overture` 只用于判空 | 只有县片形态下，OVT 处理文件数 = `overture_files` 长度 | 见 `scripts/gold_scope.py:150-152` 注释 | 0 |
| W2-018 | 2026-10-2x | 并发队列 | 单 Job 顺序跑多县、共享缓存：**一个县崩整州重跑**（没有县级续跑） | 并发单位是州，不是县 | 时间：一县崩 = 全州重跑；数据：无 | 按县分 job（缓存仍共享）或县级断点（已出 `scope.json` 的县跳过） | 故意让中间县失败：重跑只补该县及之后（耗时与日志可证） | 见 `gold-coalesce.yml` 头部铁律 2（现状：单 Job 顺序） | 0 |

## 2. 用法（照抄即可）

```bash
# ① 派单前：查清单 + 本次涉及的类别
#    故障清单已查：W2-013,W2-015   （或「无」）
#    TODO：二仓的 scripts/gold_preflight.py 目前**不读**台账（三仓已有 F16）；要不要接同名 F16 另行审批

# ② 改脚本前后必跑（本仓没有 CI，这三条就是 CI）
python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts bots
for f in .github/workflows/*.yml; do python3 -c "import yaml,sys;yaml.safe_load(open('$f'))" || echo "YAML 坏: $f"; done

# ③ 新坑当天补一行，然后
git commit -m "ledger: +1 缓存与签名"
```

## 3. 证据路径索引

- `scripts/gold_scope.py`（G1/G2/G5/G10 的实现与修复注释、`overture_files` 语义）
- `scripts/gold_preflight.py`（G3/G4/G7 的判据与降级）
- `scripts/gold_coalesce.py`（3 元组 `addr_key()` `:159-162`、OA/Overture 桶 `:362-390,476-490`、`oa_rows` 回填 `:1016-1017`）
- `scripts/list_failed_gold.py`（G12 失败州单跑入口）
- `docs/GOLD-LAYERING-2026-10-30.md`（3 元组口径、单层融合无 staging、第五源对齐要求）
- `tests/test_gold_offline.py`（G9 离线自测）
- `.github/workflows/gold-coalesce.yml`（G6 分卷 `auto`、G8 `rc=2` 放行、缓存键 `gold-cache-<ST>-v1`、单 Job 顺序铁律）
