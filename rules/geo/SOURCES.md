# 全球行政编码注册表 · 数据来源与口径

产物：`rules/geo/global_admin_registry.json`（约 1.4 MB，随代码走，**不发 Release**）
生成器：`bots/build_admin_registry.py`（可重跑、幂等、稳定排序）

## 为什么放在仓库里

这是**参考字典**，不是抓来的数据载荷。性质等同 `rules/US/state_roster.yaml`：
读它的脚本应当 `git checkout` 就能用，不依赖"去网上下载一个附件"。
放在 git 里还能用 commit SHA 锁定版本，并在 diff 里看清 ISO 每次更新动了哪几条。
（Release 留给每州 1GB 级的原始数据快照，语义不要混。）

## 三个数据源与各自边界

| 源 | 提供什么 | 许可 | 用法边界 |
|---|---|---|---|
| **Debian iso-codes**（经 `pycountry`） | ISO 3166-1 国家 + ISO 3166-2 一级行政区 | LGPL-2.1+ | **权威主源**，行政区一律以它为准 |
| **GeoNames `countryInfo.txt`** | 国家层增强：电话区号前缀、邮编正则、大陆码、首都、geonameid | CC-BY 4.0 | 只补国家层字段，不碰区划 |
| **GeoNames `admin1CodesASCII.txt`** | 各国一级行政区 | CC-BY 4.0 | **仅当某国 ISO 完全没有一级行政区时兜底**；这类行 `iso_3166_2 = null`、`in_iso3166_2 = false` |

### ⚠️ 两个体系不能混用

GeoNames 的 admin1 码在不少国家（如法国大区、部分亚洲国家）**不等于** ISO 3166-2 码。
把两套码硬合并会产出"看起来像 ISO 其实不是"的脏码，所以本仓库的做法是：
**ISO 有就用 ISO；ISO 没有才用 GeoNames，并且明确打标，永远不做无标记覆盖。**

## 字段口径

`countries[]`

| 字段 | 含义 | 来源 |
|---|---|---|
| `country_code` | ISO 3166-1 alpha-2（`US`） | iso-codes |
| `country_name` | 英文全称（`United States`） | iso-codes |
| `country_name_official` / `country_name_common` | 官方名 / 常用名（可为空） | iso-codes |
| `alpha_3` / `numeric` | ISO alpha-3（`USA`）/ 数字码（`840`） | iso-codes |
| `phone_prefix` | 国际电话区号（`1`） | GeoNames |
| `postal_code_format` / `postal_code_regex` | 邮编书写格式 / 校验正则 | GeoNames |
| `continent_code` / `capital` / `geoname_id` | 大陆码 / 首都 / GeoNames 主键 | GeoNames |

`admin_divisions[]`

| 字段 | 含义 |
|---|---|
| `iso_3166_2` | 组合码（`US-RI`）；GeoNames 兜底行为 `null` |
| `country_code` | 所属国家 alpha-2 |
| `admin_division_code` | 国家内的区划码（`RI`） |
| `admin_division_name` | 英文名（`Rhode Island`） |
| `admin_division_type` | `State` / `Province` / `Parish` …（GeoNames 兜底行为 `null`） |
| `parent_code` | 上级区划码（有层级时才有） |
| `in_iso3166_2` | `true` = 真 ISO 码；`false` = GeoNames 兜底，别当 ISO 用 |
| `source` | `iso-codes` / `geonames` |

## 当前规模（生成快照）

- 国家：**249**
- ISO 3166-2 一级行政区：**5,046**（覆盖 **200** 个国家）
- GeoNames 兜底区划：**277**（ISO 未覆盖的小属地等，均标记 `in_iso3166_2=false`）
- 美国：**57** 条（50 州 + DC + 若干属地/边远岛屿）

## 更新方式

ISO 一年更新数次，GeoNames 每周更新 dump。重跑即刷新：

```bash
python3 bots/build_admin_registry.py                      # 联网取 GeoNames 后生成
python3 bots/build_admin_registry.py --offline            # 只用 pycountry（跳过增强）
python3 bots/build_admin_registry.py --geonames-dir /tmp  # 用本地已下好的两个 txt
```

重跑后 diff 一遍 `git diff rules/geo/global_admin_registry.json` 就能看清增删了哪几条，
提交时在 commit message 里注明"ISO 更新到某版本"即可。

## 自检

```bash
python3 tests/test_admin_registry_offline.py
```

覆盖：国家数 ≥249、字段长度合法、US 电话前缀 = 1、US-DC/US-RI 存在且类型为 State、
`state_roster.yaml` 里每个州都能在注册表里查到 `US-XX`、无重复 `iso_3166_2`、
兜底行不得混入 ISO 字段。
