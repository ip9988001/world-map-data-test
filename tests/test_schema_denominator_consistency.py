#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""口径一致性校验：schema 文本 ↔ 代码行为 ↔ 文档判据，三处必须是同一句话。

跑法：python3 tests/test_schema_denominator_consistency.py

为什么要这个文件（muse-000158 后半句）：
  `counties_nad_substantive` 的口径分三处写着 —— `schema/SCHEMA.json`（给外部看的契约）、
  `scripts/coverage_counters.py`（实际算的代码）、`docs/D1-D2-ACCEPTANCE-CRITERIA.md`（给人看的判据）。
  历史上这三处漂过：文档写「阈值 10」、代码却按 1%×housing_units 算；代码 001153 版还留过
  「优先总融合行数，为 0 才退回 housing_units」的兜底分支。任何一处单改，另一处就会悄悄骗人。
  这个文件的作用是：**改一处必须同步另一处，否则测试红**。

四条断言（对应派单 A1–A4）：
  S1  schema 文本侧：`coverage.counties_nad_substantive.denominator_priority` 必须含「固定」+ `housing_units`，
      且黑名单字样「优先」「退回」不得出现在**生效文字**里（无「作废」标记的括注也照扫）；
      `ties` 不得含「两种都缺」。
  S2  代码行为侧：同一 housing_units、融合行数 0 vs 10,000,000 → `nad_substantive_threshold()` 返回值完全相同；
      管道级（coverage_counters）同样证明融合行数对 substantive 判定零影响。
  S3  签名侧：函数只收 1 个参数（名字必须是 housing_units），双参调用必抛 TypeError。
  S4  文档侧：D2 阈值段含 `housing_units`；全文不得出现旧口径原文
      「优先该县**总融合行数**；该县融合行数为 0 时退回」。

关于「已作废」引述（S1 的处置，写在明处，别当成放宽）：
  SCHEMA 现值里「优先」「退回」确实出现过一次，但它被包在
  `（旧「优先总融合行数是 0 时退回」已作废，muse-000155/000156）` 这个**显式作废引述括注**里。
  判据与 S4 的处置一致：把**带「作废」二字的括注**从扫描面上摘掉后再扫黑名单；
  不带「作废」的括注（例如有人写成 `（优先融合行数）`）照扫不误，一样红。
  这样既允许「引述旧口径以说明其作废」，又不允许「把旧口径当生效规则写回来」。

零第三方依赖、不联网、不需要 duckdb。
"""
from __future__ import annotations

import inspect
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO / "schema" / "SCHEMA.json"
DOCS_PATH = REPO / "docs" / "D1-D2-ACCEPTANCE-CRITERIA.md"

sys.path.insert(0, str(REPO / "scripts"))
import coverage_counters as CC   # noqa: E402

# 旧口径关键词黑名单（生效文字里出现即判失败）
BLACKLIST = ("优先", "退回")
# docs 里旧口径的完整原文（允许「已作废」引述，故用精确整串判定，而不是散词）
DOCS_BANNED_SENTENCE = "优先该县**总融合行数**；该县融合行数为 0 时退回"

# 引述括注：全角括号内且含「作废」→ 视为「引述旧口径并声明其作废」，不进黑名单扫描面
_PAREN = re.compile(r"（[^（）]*）")


def split_quoted(text: str) -> tuple[str, list[str]]:
    """返回 (生效文字, 被摘掉的作废引述括注列表)。

    只摘**含「作废」二字**的括注；其余文字（含无「作废」的括注）一律留在生效文字里，
    照常参与黑名单扫描 —— 防止有人把旧口径塞进普通括注来绕过检查。
    """
    quoted = [m.group(0) for m in _PAREN.finditer(text) if "作废" in m.group(0)]
    operative = text
    for q in quoted:
        operative = operative.replace(q, "", 1)
    return operative, quoted


def _scan_blacklist(text: str) -> list[str]:
    operative, _ = split_quoted(text)
    return [w for w in BLACKLIST if w in operative]


def _pipeline_threshold(hu: int | None, fused_extra: int) -> int:
    """把该县喂进真管道：nad=1,778（正好过线）+ 不同数量的融合行，取 substantive 与逐县阈值。

    返回 counties_nad_substantive 的判定结果（0/1），用于证明融合行数不参与阈值。
    """
    fips = "33011"
    lat, lon = _inside_pt(fips)
    rows = [{"county_fips": fips, "state_abbr": "NH", "lat": lat, "lon": lon, "source": "nad"}
            for _ in range(1778)]
    rows += [{"county_fips": fips, "state_abbr": "NH", "lat": lat, "lon": lon, "source": "oa"}
             for _ in range(fused_extra)]
    c = CC.coverage_counters("NH", rows, baseline=BASE, county_geoms={fips: GEOMS[fips]})
    return c["counties_nad_substantive"]


def _inside_pt(fips: str) -> tuple[float, float]:
    """取该县多边形内一点（网格扫描 + 射线法，与 tests/test_d1_d2.py 同法）。"""
    rings = GEOMS[fips]
    big = max(rings, key=len)
    xs = [p[0] for p in big]
    ys = [p[1] for p in big]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    for i in range(1, 40):
        for j in range(1, 40):
            lon = x0 + (x1 - x0) * i / 40
            lat = y0 + (y1 - y0) * j / 40
            if CC.point_in_rings(lon, lat, rings):
                return round(lat, 5), round(lon, 5)
    raise SystemExit("县 %s 找不到内部点" % fips)


BASE = CC.load_baseline()
GEOMS = CC.load_county_geoms()


def main() -> int:
    ok: dict[str, bool] = {}
    detail: dict[str, dict] = {}
    fix: dict[str, str] = {}          # 每条失败时「改哪一处」

    # ------------------------------------------------ S1 · schema 文本侧
    node = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["coverage"]["counties_nad_substantive"]
    den = node.get("denominator_priority") or ""
    ties = node.get("ties") or ""
    _, den_quoted = split_quoted(den)
    ties_scan, ties_quoted = split_quoted(ties)
    den_black = _scan_blacklist(den)
    ties_black = _scan_blacklist(ties)
    detail["S1"] = {
        "has_固定": "固定" in den,
        "has_housing_units": "housing_units" in den,
        "den_blacklist_hits": den_black,
        "ties_blacklist_hits": ties_black,
        "ties_has_两种都缺": "两种都缺" in ties_scan,
        "quoted_as_deprecated": den_quoted + ties_quoted,
        "den": den,
    }
    ok["S1"] = (detail["S1"]["has_固定"] and detail["S1"]["has_housing_units"]
                and not den_black and not ties_black
                and not detail["S1"]["ties_has_两种都缺"])
    fix["S1"] = ("schema/SCHEMA.json → coverage.counties_nad_substantive.denominator_priority / .ties："
                 "生效文字必须写「分母**固定为该县 housing_units**」，不许出现「优先」「退回」；"
                 "引述旧口径必须包在含「作废」的括注里（例：（旧「…」已作废，muse-000155/000156）），"
                 "ties 不许写「两种都缺」")

    # ------------------------------------------------ S2 · 代码行为侧
    hu = CC.housing_units_of(BASE, "33011")                     # 177,734
    scenarios = {
        "fused_rows=0": {"housing_units": hu, "fused_rows": 0},
        "fused_rows=10000000": {"housing_units": hu, "fused_rows": 10_000_000},
    }
    thr_by_scenario, thr_err = {}, None
    try:
        for k, v in scenarios.items():
            thr_by_scenario[k] = CC.nad_substantive_threshold(v["housing_units"])
    except TypeError as exc:            # 旧口径双参签名回流：不抛栈，落成可读失败
        thr_err = "%s: %s" % (type(exc).__name__, exc)
    thr_values = set(thr_by_scenario.values())
    # 管道级：nad 恰好 1,778 行，融合行数 0 vs 20,000（20,000 上限受内存约束；
    # 10,000,000 由 S3 的签名封闭性覆盖 —— 函数只有 1 个参数，融合行数根本没有注入通道）
    sub_0 = sub_big = None
    pipe_err = None
    try:
        sub_0 = _pipeline_threshold(hu, 0)
        sub_big = _pipeline_threshold(hu, 20_000)
    except TypeError as exc:            # 旧口径双参签名回流：不抛栈，落成可读失败
        pipe_err = "%s: %s" % (type(exc).__name__, exc)
    detail["S2"] = {"hu": hu, "thr_by_scenario": thr_by_scenario,
                    "thr_unique": sorted(v for v in thr_values if v is not None),
                    "one_arg_call_error": thr_err, "pipeline_error": pipe_err,
                    "pipeline_substantive_fused0": sub_0,
                    "pipeline_substantive_fused20000": sub_big}
    ok["S2"] = (thr_err is None and pipe_err is None
                and None not in thr_values and len(thr_values) == 1
                and thr_values == {1778}
                and sub_0 == sub_big == 1)
    fix["S2"] = ("scripts/coverage_counters.py → nad_substantive_threshold()：阈值必须只由 housing_units 决定；"
                 "若两场景返回值不同，说明有人把融合行数（fused_rows/output_rows）又接回了阈值计算")

    # ------------------------------------------------ S3 · 签名侧
    sig = inspect.signature(CC.nad_substantive_threshold)
    params = list(sig.parameters.values())
    two_arg_type_error = False
    try:
        CC.nad_substantive_threshold(hu, 10_000_000)            # 旧口径双参调用必须当场炸
    except TypeError:
        two_arg_type_error = True
    detail["S3"] = {"signature": str(sig), "n_params": len(params),
                    "param_names": [p.name for p in params],
                    "two_arg_raises_TypeError": two_arg_type_error}
    ok["S3"] = (len(params) == 1 and params[0].name == "housing_units"
                and params[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
                and two_arg_type_error)
    fix["S3"] = ("scripts/coverage_counters.py → nad_substantive_threshold()：必须只有 1 个参数且名为 "
                 "housing_units；若参数变多，说明融合行数又被当成第二参接回来（001153 旧口径回流）")

    # ------------------------------------------------ S4 · 文档侧
    doc = DOCS_PATH.read_text(encoding="utf-8")
    lines = doc.splitlines()
    thr_idx = [i for i, ln in enumerate(lines) if "县内 NAD 行数 >= max(10, ceil(0.01 × 分母))" in ln]
    thr_block = "\n".join(lines[thr_idx[0]:thr_idx[0] + 3]) if thr_idx else ""
    detail["S4"] = {"thr_line_no": (thr_idx[0] + 1) if thr_idx else None,
                    "thr_block": thr_block,
                    "banned_sentence_hit": DOCS_BANNED_SENTENCE in doc,
                    "block_has_housing_units": "housing_units" in thr_block,
                    "block_has_固定": "固定" in thr_block}
    ok["S4"] = (bool(thr_idx) and detail["S4"]["block_has_housing_units"]
                and detail["S4"]["block_has_固定"]
                and not detail["S4"]["banned_sentence_hit"])
    fix["S4"] = ("docs/D1-D2-ACCEPTANCE-CRITERIA.md → 「### counties_nad_substantive 判定」段的 "
                 "「分母：」行：必须写「固定为该县 **housing_units**」；不许再出现旧的 "
                 "「" + DOCS_BANNED_SENTENCE + "」原文")

    # ------------------------------------------------------------ 输出
    print("口径一致性校验（schema 文本 ↔ 代码行为 ↔ 文档判据）\n")
    for k in ("S1", "S2", "S3", "S4"):
        print("%s: %s  %s" % (k, "✅" if ok[k] else "❌", json.dumps(detail[k], ensure_ascii=False)))
        if not ok[k]:
            print("   ↳ 改哪一处：%s" % fix[k])
    bad = [k for k in ok if not ok[k]]
    print()
    if bad:
        print("总判定： ❌ 失败 %d 条（%s）—— 口径已漂，改一处必须同步另一处" % (len(bad), ", ".join(bad)))
        return 1
    print("总判定： ✅ 全部通过（%d 条）—— schema 文本 / 代码行为 / 文档判据 三处同一句话" % len(ok))
    return 0


if __name__ == "__main__":
    sys.exit(main())
