#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D1 / D2 判据自测（不联网、不需要 duckdb）

跑法：python3 tests/test_d1_d2.py

口径来源：docs/D1-D2-ACCEPTANCE-CRITERIA.md（2026-11-22 版，取代 001175 版）。
每条用例都是「旧版会判绿、新版必须判红」的现场：

D1 五条
  D1-① rows=0 + declared=0 + 有上游证据 → ok=False + empty_upstream_confirmed
  D1-② 同上但无证据                          → empty_anomaly（不再是 empty）
  D1-③ rows>0 + declared 匹配 + 守恒通过     → ok=True + verified
  D1-④ rows>0 但 declared=0                  → ok 可为 True，但 verification=unverified + warn 留痕
  D1-⑤ 完整率越 0.5%                          → ok=False（旧版 declared>0 就放行）

D2 四条 + 一条真几何
  D2-① 10 县 done、只有 3 县有 NAD 行        → counties_with_nad_rows=3（分母仍=基准表）
  D2-② 某县 9 行 NAD                         → 不进 counties_nad_substantive（<10）
  D2-③ 同县 500 行但阈值 1,778                → 也不进；补 1,800 行 → 进（阈值只由 housing_units 算）
  D2-④ 溢出包全 MA/VT/ME 的行喂给 NH          → 全落 excluded_state_mismatch，any_rows 不虚增
  D2-⑤ 全国县界小包（仓内 3,144 县 gz）+ DE Kent 原始 Esri 样本
                                              → 县内点留 / 县外点剔 / state_fips 不符剔除 / 缺几何 fail（不是 skip）
  D2-⑥ 同一县融合行数极少（3）但 housing_units 正常 + 融合行数爆到 6 万
                                              → 两种情况下阈值都只由 housing_units 定（防回归，muse-000156）
                                              附：基准表无 housing_units 的县 → 不计数 + warn，也不当通过
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import coverage_counters as CC   # noqa: E402

BASE = CC.load_baseline()
GEOMS = CC.load_county_geoms()          # config/baseline/counties_geom.json.gz（3,144 县）
NH10 = ["33001", "33003", "33005", "33007", "33009", "33011", "33013", "33015", "33017", "33019"]
KENT_GEOM = REPO / "data" / "dover" / "task001" / "tiger_boundary_kent_10' AND COUNTY.json"


def inside_pt(fips: str) -> tuple[float, float]:
    """取该县多边形内一点（网格扫描 + 射线法，真几何）。"""
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


def rec(fips, source="nad", lat=None, lon=None, state="NH"):
    if lat is None or lon is None:
        lat, lon = inside_pt(fips)
    return {"county_fips": fips, "state_abbr": state, "lat": lat, "lon": lon, "source": source}


def main() -> int:
    ok: dict[str, bool] = {}
    detail: dict[str, dict] = {}

    # ---------------- D1 ----------------
    a = CC.d1_verdict(rows=0, declared=0, conservation_ok=True, upstream_evidence="NAD MANIFEST 声明该层 0 行")
    detail["D1-①"] = {"ok": a["ok"], "status": a["coverage_status"], "ver": a["verification"]}
    ok["D1-①"] = (a["ok"] is False and a["coverage_status"] == "empty_upstream_confirmed"
                  and a["warnings"] == [])

    b = CC.d1_verdict(rows=0, declared=0, conservation_ok=True, upstream_evidence=None)
    detail["D1-②"] = {"ok": b["ok"], "status": b["coverage_status"], "warn": len(b["warnings"])}
    ok["D1-②"] = (b["ok"] is False and b["coverage_status"] == "empty_anomaly"
                  and len(b["warnings"]) == 1 and "empty" != b["coverage_status"])

    c = CC.d1_verdict(rows=1200, declared=1200, conservation_ok=True)
    detail["D1-③"] = {"ok": c["ok"], "status": c["coverage_status"], "ver": c["verification"],
                      "ratio": c["completeness_ratio"]}
    ok["D1-③"] = (c["ok"] is True and c["coverage_status"] == "ok"
                  and c["verification"] == "verified" and c["completeness_ratio"] == 0.0)

    d = CC.d1_verdict(rows=500, declared=0, conservation_ok=True)
    detail["D1-④"] = {"ok": d["ok"], "ver": d["verification"], "warn": d["warnings"][:1]}
    ok["D1-④"] = (d["ok"] is True and d["verification"] == "unverified"
                  and len(d["warnings"]) == 1 and "unverified" in d["warnings"][0])

    e = CC.d1_verdict(rows=99_000, declared=100_000, conservation_ok=True)
    detail["D1-⑤"] = {"ok": e["ok"], "status": e["coverage_status"],
                      "ratio": e["completeness_ratio"], "delta": e["completeness_delta"]}
    ok["D1-⑤"] = (e["ok"] is False and e["coverage_status"] == "failed"
                  and e["completeness_ratio"] == 0.01 and e["completeness_delta"] == 1000)

    # 附加：declared>0 但 rows=0 → failed（旧版空包会被当 empty 混过去）
    f = CC.d1_verdict(rows=0, declared=777)
    detail["D1-⑥"] = {"ok": f["ok"], "status": f["coverage_status"]}
    ok["D1-⑥"] = f["ok"] is False and f["coverage_status"] == "failed"

    # ---------------- D2 ----------------
    rows1 = ([rec(f, "nad") for f in NH10[:3] for _ in range(20)]
             + [rec(f, "oa") for f in NH10[3:] for _ in range(5)])
    c1 = CC.coverage_counters("NH", rows1, baseline=BASE,
                              counties_done=NH10, counties_declared=NH10)   # 几何默认取仓内小包
    detail["D2-①"] = {k: c1[k] for k in ("counties_expected", "counties_done", "counties_declared",
                                         "counties_with_any_rows", "counties_with_nad_rows",
                                         "boundary_check")}
    ok["D2-①"] = (c1["counties_with_nad_rows"] == 3 and c1["counties_with_any_rows"] == 10
                  and c1["counties_done"] == 10 and c1["counties_declared"] == 10
                  and c1["counties_expected"] == len(CC.expected_counties(BASE, "NH")) == 10
                  and c1["boundary_check"] == ["checked"] and c1["missing_geom"] == 0
                  and c1["coverage_status"] == "ok" and c1["verification"] == "verified")

    c2 = CC.coverage_counters("NH", [rec("33011", "nad") for _ in range(9)], baseline=BASE)
    hu_33011 = CC.housing_units_of(BASE, "33011")           # = 177,734
    detail["D2-②"] = {"nad": c2["per_county"]["33011"]["nad"],
                      "substantive": c2["counties_nad_substantive"],
                      "hu": hu_33011, "thr": CC.nad_substantive_threshold(hu_33011),
                      "abs_min_thr": CC.nad_substantive_threshold(500)}
    ok["D2-②"] = (c2["per_county"]["33011"]["nad"] == 9
                  and c2["counties_nad_substantive"] == 0
                  and detail["D2-②"]["thr"] == 1778
                  and detail["D2-②"]["abs_min_thr"] == 10)      # 1%×500=5 → 抬到绝对下限 10

    big = ([rec("33011", "nad") for _ in range(500)]
           + [rec("33011", "oa") for _ in range(59_500)])
    c3 = CC.coverage_counters("NH", big, baseline=BASE)
    thr3 = CC.nad_substantive_threshold(CC.housing_units_of(BASE, "33011"))
    # 融合行数 6 万在旧口径下会把阈值抬到 600；新口径阈值恒 = ceil(1% × housing_units) = 1,778
    big2 = ([rec("33011", "nad") for _ in range(1800)]
            + [rec("33011", "oa") for _ in range(58_200)])
    c3b = CC.coverage_counters("NH", big2, baseline=BASE)
    detail["D2-③"] = {"fused": c3["per_county"]["33011"]["any"],
                      "nad": c3["per_county"]["33011"]["nad"], "thr": thr3,
                      "substantive_500": c3["counties_nad_substantive"],
                      "substantive_1800": c3b["counties_nad_substantive"]}
    ok["D2-③"] = (thr3 == 1778 and thr3 != 600 and c3["counties_nad_substantive"] == 0
                  and c3b["counties_nad_substantive"] == 1)

    nh_pt = inside_pt("33011")
    overflow = ([rec("33011", "nad", lat=nh_pt[0], lon=nh_pt[1], state="MA") for _ in range(30)]
                + [rec("33011", "nad", lat=nh_pt[0], lon=nh_pt[1], state="VT") for _ in range(20)]
                + [rec("33011", "oa", lat=nh_pt[0], lon=nh_pt[1], state="ME") for _ in range(10)])
    c4 = CC.coverage_counters("NH", overflow, baseline=BASE)
    detail["D2-④"] = {"excluded_state_mismatch": c4["excluded_state_mismatch"],
                      "any_rows": c4["counties_with_any_rows"],
                      "nad_rows": c4["counties_with_nad_rows"]}
    ok["D2-④"] = (c4["excluded_state_mismatch"] == 60 and c4["counties_with_any_rows"] == 0
                  and c4["counties_with_nad_rows"] == 0)

    rings = CC.rings_from_esri_json(KENT_GEOM)          # 仓内原始 Esri 样本（DE Kent）
    inside = {"county_fips": "10001", "state_abbr": "DE", "lat": 39.1582, "lon": -75.5244, "source": "nad"}
    outside = {"county_fips": "10001", "state_abbr": "DE", "lat": 40.0000, "lon": -80.0000, "source": "nad"}
    chk = CC.county_boundary_check([inside, outside], rings)
    c5 = CC.coverage_counters("DE", [inside, outside], baseline=BASE,
                              county_geoms={"10001": rings})
    # 缺几何：必须 fail（missing_geometry），不再是 skipped
    miss = CC.coverage_counters("DE", [inside], baseline=BASE, county_geoms={})
    chk_miss = CC.county_boundary_check([inside], None)
    # state_fips 不符：先剔（AZ 的点喂给 DE）
    wrong_state = dict(inside, state_abbr="AZ")
    c5s = CC.coverage_counters("DE", [wrong_state], baseline=BASE)
    detail["D2-⑤"] = {"rings": len(rings), "status": chk["status"], "kept": chk["kept"],
                      "rejected": chk["rejected"], "excluded_geom": c5["excluded_geom"],
                      "missing_status": miss["coverage_status"],
                      "missing_verification": miss["verification"],
                      "missing_geom": miss["missing_geom"],
                      "chk_missing": chk_miss["status"],
                      "state_mismatch": c5s["excluded_state_mismatch"],
                      "any_rows_after_mismatch": c5s["counties_with_any_rows"]}
    ok["D2-⑤"] = (len(rings) > 0 and chk["status"] == "checked" and chk["kept"] == 1
                  and chk["rejected"] == 1 and c5["excluded_geom"] == 1
                  and c5["counties_with_any_rows"] == 1
                  and chk_miss["status"] == "missing_geometry"
                  and miss["missing_geom"] == 1 and miss["coverage_status"] == "failed"
                  and miss["verification"] == "unverified"
                  and c5s["excluded_state_mismatch"] == 1 and c5s["counties_with_any_rows"] == 0)

    # D2-⑥ 防回归（muse-000155/000156）：分母只认 housing_units，融合行数只作被除数
    # 判别力：600 行 NAD + 融合 603 行（旧口径 thr=max(10,ceil(1%×603))=10 → 会判进）
    #         600 行 NAD + 融合 60,000 行（旧口径 thr=600 → 会判进）
    #         新口径两者 thr 恒 = ceil(1%×177,734) = 1,778 → 都不进
    few = [rec("33011", "nad") for _ in range(600)] + [rec("33011", "oa") for _ in range(3)]
    c6a = CC.coverage_counters("NH", few, baseline=BASE)
    many = ([rec("33011", "nad") for _ in range(600)]
            + [rec("33011", "oa") for _ in range(59_400)])
    c6b = CC.coverage_counters("NH", many, baseline=BASE)
    # 同一县融合行数仍只 3 行，NAD 补到 1,800 → 超过 1,778 才进（证明阈值可达成、且不由融合行数推）
    enough = [rec("33011", "nad") for _ in range(1800)] + [rec("33011", "oa") for _ in range(3)]
    c6d = CC.coverage_counters("NH", enough, baseline=BASE)
    # 基准表里该县无 housing_units（分母缺失）→ 不计数也不当通过，且 warn 文案只说 housing_units
    no_hu_base = dict(BASE)
    no_hu_base["counties"] = [dict(c, housing_units=0) if c.get("county_fips") == "33011" else c
                              for c in BASE.get("counties") or []]
    c6c = CC.coverage_counters("NH", [rec("33011", "nad") for _ in range(5000)], baseline=no_hu_base)
    warn_txt = [w for w in c6c["warnings"] if "housing_units" in w]
    # 结构护栏：函数不再接收融合行数（传第二个位置参直接 TypeError，留着旧口径调用必炸）
    two_arg_rejected = False
    try:
        CC.nad_substantive_threshold(177_734, 60_000)      # type: ignore[call-arg]
    except TypeError:
        two_arg_rejected = True
    detail["D2-⑥"] = {"fused_603": c6a["per_county"]["33011"]["any"],
                       "substantive_603": c6a["counties_nad_substantive"],
                       "fused_60k": c6b["per_county"]["33011"]["any"],
                       "substantive_60k": c6b["counties_nad_substantive"],
                       "fused_1803_substantive": c6d["counties_nad_substantive"],
                       "thr_by_hu": CC.nad_substantive_threshold(hu_33011),
                       "thr_old_603": 10, "thr_old_60k": 600,
                       "thr_no_hu": CC.nad_substantive_threshold(0),
                       "two_arg_rejected": two_arg_rejected,
                       "no_hu_substantive": c6c["counties_nad_substantive"],
                       "no_hu_warn": warn_txt[:1]}
    ok["D2-⑥"] = (c6a["per_county"]["33011"]["any"] == 603
                  and c6b["per_county"]["33011"]["any"] == 60_000
                  and c6a["counties_nad_substantive"] == 0      # 旧口径会判 1
                  and c6b["counties_nad_substantive"] == 0      # 旧口径会判 1
                  and c6d["counties_nad_substantive"] == 1      # 1,800 ≥ 1,778
                  and CC.nad_substantive_threshold(hu_33011) == 1778
                  and CC.nad_substantive_threshold(0) is None
                  and CC.nad_substantive_threshold(None) is None
                  and two_arg_rejected
                  and c6c["counties_nad_substantive"] == 0
                  and len(warn_txt) == 1 and "融合行数" not in warn_txt[0])

    for k in sorted(ok):
        print("%s: %s  %s" % (k, "✅" if ok[k] else "❌", detail.get(k, "")))
    bad = [k for k, v in ok.items() if not v]
    print("\n总判定：", "✅ 全部通过（%d 条）" % len(ok) if not bad else f"❌ 失败 {bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
