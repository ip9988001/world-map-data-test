#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D1 判定 / D2 覆盖率计数 —— 「这一层到底算不算 ok」「覆盖率几成」的唯一实现。

口径来源：docs/D1-D2-ACCEPTANCE-CRITERIA.md（2026-11-22 版，取代 001175 版）。
任何脚本想判 ok / 算覆盖率，都必须调这里，不许自己再写一套宽松版（旧版那条
「declared 大于零即放行」的或-分支）—— 那正是 NH 2026-11-21 把 10 个 0 字节资产判成「完整」的原因。

三件事：
  D1  d1_verdict(...)          → {ok, coverage_status, verification, completeness_*, warnings}
  D2  county_boundary_check()  → 点在县多边形内才算该县（缺几何 = skipped:no_geometry + warn，不当通过）
      coverage_counters(...)   → 6 个 counties_* 计数 + 两道清洗的剔除数
  D2  nad_substantive_threshold(fused_rows, housing_units) → max(10, ceil(1% × 分母))

分母唯一 = config/baseline/counties_census.json 的 county_count（按州过滤）。
counties_done / counties_declared 只作观测，绝不当分母。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO / "config" / "baseline" / "counties_census.json"

COVERAGE_STATUS = ("ok", "empty_upstream_confirmed", "empty_anomaly", "failed")
VERIFICATION = ("verified", "unverified")
TOLERANCE = 0.005            # 完整率公差：|raw_fetched - declared| / declared ≤ 0.5%
SUBSTANTIVE_ABS_MIN = 10     # counties_nad_substantive 的绝对下限
SUBSTANTIVE_RATIO = 0.01     # 相对下限：1% × 该县分母


# ------------------------------------------------------------------ 基准表
def load_baseline(path: Path | str | None = None) -> dict:
    """读固定版 Census 基准县表（只读）。缺文件 → 抛错，不静默降级。"""
    p = Path(path) if path else BASELINE_PATH
    doc = json.loads(p.read_text(encoding="utf-8"))
    if not doc.get("counties"):
        raise SystemExit("基准县表为空：%s" % p)
    return doc


def expected_counties(baseline: dict, state_abbr: str) -> list[dict]:
    """目标州的县行（= 该州的法定分母）。州不在表里 → 空列表（由调用方报错）。"""
    ab = (state_abbr or "").upper()
    return [c for c in baseline.get("counties") or [] if (c.get("state_abbr") or "").upper() == ab]


def housing_units_of(baseline: dict, county_fips: str) -> int | None:
    for c in baseline.get("counties") or []:
        if c.get("county_fips") == county_fips:
            return c.get("housing_units")
    return None


# ------------------------------------------------------------------ D1
def d1_verdict(rows: int, declared: int | None, *, raw_fetched: int | None = None,
               conservation_ok: bool = True, upstream_evidence: str | None = None,
               name: str = "") -> dict:
    """D1 判定（docs/D1-D2-ACCEPTANCE-CRITERIA.md 逐字实现）。

    rows          落盘/产出行数
    declared      上游声明行数（缺失传 None）
    raw_fetched   上游实际取回行数；缺省 = rows
    upstream_evidence  上游「确实没有数据」的证据（URL / 字段 / 清单条目）；None = 无证据
    """
    rows = int(rows or 0)
    rf = int(raw_fetched) if raw_fetched is not None else rows
    warns: list[str] = []
    who = (" " + name) if name else ""
    delta = ratio = None

    if declared is None or int(declared) <= 0:
        if rows > 0:
            # 行数没法与上游对账 → 不许静默当 100% 完整
            warns.append("declared %s 但 rows=%d%s：行数无法对账，verification=unverified"
                         % ("缺失" if declared is None else "= 0", rows, who))
            return {"ok": bool(conservation_ok), "coverage_status": "ok" if conservation_ok else "failed",
                    "verification": "unverified", "rows": rows, "declared": declared,
                    "raw_fetched": rf, "completeness_delta": None, "completeness_ratio": None,
                    "warnings": warns}
        # rows == 0 且 declared 缺失或 0：按上游事实二选一，不再用旧的单值 empty
        status = "empty_upstream_confirmed" if upstream_evidence else "empty_anomaly"
        if not upstream_evidence:
            warns.append("rows=0 且 declared=%s 但无上游确认证据%s：记 empty_anomaly（不是 empty）"
                         % (declared, who))
        return {"ok": False, "coverage_status": status,
                "verification": "verified" if declared == 0 else "unverified",
                "rows": 0, "declared": declared, "raw_fetched": rf,
                "completeness_delta": 0 if declared == 0 else None,
                "completeness_ratio": 0.0 if declared == 0 else None,
                "warnings": warns}

    declared = int(declared)
    delta = abs(rf - declared)
    ratio = delta / declared
    if rows == 0:
        warns.append("declared=%d 但 rows=0%s：上游说有数据我们一条没出，记 failed" % (declared, who))
        return {"ok": False, "coverage_status": "failed", "verification": "verified",
                "rows": 0, "declared": declared, "raw_fetched": rf,
                "completeness_delta": delta, "completeness_ratio": round(ratio, 6),
                "warnings": warns}
    ok = bool(conservation_ok) and ratio <= TOLERANCE
    if ratio > TOLERANCE:
        warns.append("完整率越界%s：|raw_fetched %d - declared %d| / declared = %.4f > %.3f"
                     % (who, rf, declared, ratio, TOLERANCE))
    return {"ok": ok, "coverage_status": "ok" if ok else "failed", "verification": "verified",
            "rows": rows, "declared": declared, "raw_fetched": rf,
            "completeness_delta": delta, "completeness_ratio": round(ratio, 6),
            "warnings": warns}


# ------------------------------------------------------------------ D2
def point_in_rings(lon: float, lat: float, rings: list) -> bool:
    """射线法（偶奇规则，天然处理洞）。bbox 只做预筛，不许当结论。"""
    inside = False
    for ring in rings:
        n = len(ring)
        if n < 3:
            continue
        j = n - 1
        for i in range(n):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-18) + xi):
                inside = not inside
            j = i
    return inside


def rings_from_esri_json(path: Path | str) -> list:
    """TIGERweb / TIGER GeoJSON（Esri JSON）→ rings。只认 geometry.rings / GeoJSON coordinates。"""
    p = Path(path)
    if not p.exists():
        return []
    doc = json.loads(p.read_text(encoding="utf-8"))
    if doc.get("error"):
        return []
    rings: list = []
    for f in doc.get("features") or []:
        g = f.get("geometry") or {}
        if g.get("rings"):
            rings.extend([[(float(x), float(y)) for x, y in r] for r in g["rings"]])
        elif g.get("type") == "Polygon":
            rings.extend([[(float(x), float(y)) for x, y in r] for r in g.get("coordinates") or []])
        elif g.get("type") == "MultiPolygon":
            for poly in g.get("coordinates") or []:
                rings.extend([[(float(x), float(y)) for x, y in r] for r in poly])
    return rings


def county_boundary_check(rows: list[dict], county_geom: list | None) -> dict:
    """D2 第②道清洗：点落在县多边形内才算该县。

    county_geom 为 None / 空 → status=`skipped:no_geometry`（**不许**当通过，也不许为此下载大几何包）。
    返回 {status, checked, kept, rejected, skipped_rows, sample_rejected}
    """
    if not county_geom:
        return {"status": "skipped:no_geometry", "checked": 0, "kept": len(rows),
                "rejected": 0, "skipped_rows": len(rows), "kept_rows": list(rows),
                "sample_rejected": []}
    kept, rejected = [], []
    for r in rows:
        lat, lon = r.get("lat"), r.get("lon")
        if lat is None or lon is None or not point_in_rings(lon, lat, county_geom):
            rejected.append(r)
        else:
            kept.append(r)
    return {"status": "checked", "checked": len(rows), "kept": len(kept),
            "rejected": len(rejected), "skipped_rows": 0, "kept_rows": kept,
            "sample_rejected": rejected[:3]}


def nad_substantive_threshold(fused_rows: int | None, housing_units: int | None) -> int | None:
    """max(10, ceil(1% × 分母))；分母优先该县总融合行数，为 0 时退回 housing_units。"""
    denom = fused_rows if (fused_rows or 0) > 0 else (housing_units if (housing_units or 0) > 0 else None)
    if denom is None:
        return None
    return max(SUBSTANTIVE_ABS_MIN, math.ceil(SUBSTANTIVE_RATIO * denom))


def coverage_counters(state_abbr: str, records, *, baseline: dict | None = None,
                      counties_done=None, counties_declared=None,
                      county_geoms: dict | None = None) -> dict:
    """算 6 个 counties_* 计数（唯一分母 = 基准表）。

    records  可迭代 [{county_fips, state_abbr, lat, lon, source}]，source ∈ nad/oa/ovt/tiger
    county_geoms  {fips: rings}；None = 没有几何 → 第②道清洗 skipped:no_geometry + warn
    """
    base = baseline or load_baseline()
    target = (state_abbr or "").upper()
    exp = expected_counties(base, target)
    warns: list[str] = []
    if not exp:
        warns.append("基准表里没有州 %s：counties_expected 无法确定" % target)

    per: dict[str, dict] = {}
    excluded_state = 0
    excluded_geom = 0
    boundary_statuses: set[str] = set()
    grouped: dict[str, list] = {}

    for r in records or []:
        st = (r.get("state_abbr") or "").upper()
        if st != target:                          # ① 州码匹配（先做，顺序不许颠倒）
            excluded_state += 1
            continue
        grouped.setdefault(str(r.get("county_fips") or ""), []).append(r)

    for fips, grp in grouped.items():
        if county_geoms is None:                  # ② 县界空间校验（可插拔：缺几何 = skipped，不当通过）
            boundary_statuses.add("skipped:no_geometry")
            kept = grp
        else:
            chk = county_boundary_check(grp, county_geoms.get(fips))
            boundary_statuses.add(chk["status"])
            if chk["status"] == "checked":
                kept = chk["kept_rows"]
                excluded_geom += chk["rejected"]
            else:
                kept = grp
        d = per.setdefault(fips, {"any": 0, "nad": 0})
        d["any"] += len(kept)
        d["nad"] += sum(1 for r in kept if (r.get("source") or "").lower() == "nad")

    if county_geoms is None:
        warns.append("无县界几何：第②道清洗状态=skipped:no_geometry（未做空间校验，不是通过）")
    elif "skipped:no_geometry" in boundary_statuses:
        warns.append("部分县无县界几何：这些县第②道清洗 skipped:no_geometry")

    with_nad = sum(1 for v in per.values() if v["nad"] > 0)
    substantive, no_denom = 0, []
    for fips, v in per.items():
        if v["nad"] <= 0:
            continue
        thr = nad_substantive_threshold(v["any"], housing_units_of(base, fips))
        if thr is None:
            no_denom.append(fips)
            continue
        if v["nad"] >= thr:
            substantive += 1
    if no_denom:
        warns.append("这些县分母两种都缺（融合行数 0 且无 housing_units），不计数也不当通过：%s" % sorted(no_denom))

    if counties_declared is not None and len(counties_declared) > len(exp):
        warns.append("counties_declared=%d 大于 counties_expected=%d（申明多做县或基准表过期）"
                     % (len(counties_declared), len(exp)))

    return {
        "counties_expected": len(exp),
        "counties_done": len(counties_done or []),
        "counties_declared": len(counties_declared or []),
        "counties_with_any_rows": sum(1 for v in per.values() if v["any"] > 0),
        "counties_with_nad_rows": with_nad,
        "counties_nad_substantive": substantive,
        "excluded_state_mismatch": excluded_state,
        "excluded_out_of_county_geometry": excluded_geom,
        "boundary_check": sorted(boundary_statuses) or ["skipped:no_geometry"],
        "denominator": "counties_expected（基准表 config/baseline/counties_census.json）",
        "per_county": per,
        "warnings": warns,
    }


def counters_from_funnels(state_abbr: str, funnels, *, baseline: dict | None = None,
                          counties_declared=None, geoms_available: bool | None = None,
                          baseline_path: Path | str | None = None) -> dict:
    """给 gold_coalesce 用：从逐县 funnel 直接算 6 个数（不重扫行）。

    funnel 里 `nad_input - nad_malformed - nad_out_of_bounds` = 该县可用 NAD 行数；
    `output_rows` = 该县融合行数（＝ substantive 阈值的第一优先分母）。
    """
    try:
        base = baseline or load_baseline(baseline_path)
    except (SystemExit, OSError, ValueError) as exc:        # 基准表缺失不许拦住发布，但必须留痕
        return {"available": False, "reason": "baseline_unavailable: %s" % str(exc)[:120],
                "counties_expected": None, "counties_done": len(list(funnels or [])),
                "warnings": ["基准表不可用：counties_expected=null（分母缺失，覆盖率本轮不算）"]}
    funnels = list(funnels or [])
    target = (state_abbr or "").upper()
    exp = expected_counties(base, target)
    hu = {c.get("county_fips"): c.get("housing_units") for c in base.get("counties") or []}
    substantive = 0
    reports = []
    for f in funnels:
        fips = str(f.get("county") or "")
        nad_usable = (f.get("nad_input") or 0) - (f.get("nad_malformed") or 0) - (f.get("nad_out_of_bounds") or 0)
        thr = nad_substantive_threshold(f.get("output_rows"), hu.get(fips))
        if nad_usable <= 0 or thr is None:
            continue
        if nad_usable >= thr:
            substantive += 1
        else:
            reports.append({"county": fips, "nad_rows": nad_usable, "threshold": thr})
    warns = []
    if not exp:
        warns.append("基准表里没有州 %s：counties_expected=null" % target)
    if geoms_available is False:
        warns.append("无县界几何：第②道清洗 skipped:no_geometry（不是通过）")
    return {
        "available": True,
        "counties_expected": len(exp) or None,
        "counties_done": len(funnels),
        "counties_declared": len(counties_declared or []) or None,
        "counties_with_any_rows": sum(1 for f in funnels if (f.get("output_rows") or 0) > 0),
        "counties_with_nad_rows": sum(
            1 for f in funnels
            if (f.get("nad_input") or 0) - (f.get("nad_malformed") or 0) - (f.get("nad_out_of_bounds") or 0) > 0),
        "counties_nad_substantive": substantive,
        "excluded_state_mismatch": 0,
        "boundary_check": "skipped:no_geometry" if geoms_available is False else "checked",
        "denominator": "counties_expected（基准表 config/baseline/counties_census.json）",
        "below_substantive": reports,
        "warnings": warns,
    }
