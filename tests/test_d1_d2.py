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
  D2-③ 同县 500 行但阈值 600                 → 也不进；补 600 行 → 进（阈值可复算）
  D2-④ 溢出包全 MA/VT/ME 的行喂给 NH          → 全落 excluded_state_mismatch，any_rows 不虚增
  D2-⑤ 仓内真几何（DE Kent Esri JSON）         → 县内点留、县外点剔；无几何 → skipped:no_geometry
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import coverage_counters as CC   # noqa: E402

BASE = CC.load_baseline()
NH10 = ["33001", "33003", "33005", "33007", "33009", "33011", "33013", "33015", "33017", "33019"]
KENT_GEOM = REPO / "data" / "dover" / "task001" / "tiger_boundary_kent_10' AND COUNTY.json"


def rec(fips, source="nad", lat=43.0, lon=-71.5, state="NH"):
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
                              counties_done=NH10, counties_declared=NH10)
    detail["D2-①"] = {k: c1[k] for k in ("counties_expected", "counties_done", "counties_declared",
                                         "counties_with_any_rows", "counties_with_nad_rows",
                                         "boundary_check")}
    ok["D2-①"] = (c1["counties_with_nad_rows"] == 3 and c1["counties_with_any_rows"] == 10
                  and c1["counties_done"] == 10 and c1["counties_declared"] == 10
                  and c1["counties_expected"] == len(CC.expected_counties(BASE, "NH")) == 10
                  and c1["boundary_check"] == ["skipped:no_geometry"]
                  and any("skipped:no_geometry" in w for w in c1["warnings"]))

    c2 = CC.coverage_counters("NH", [rec("33011", "nad") for _ in range(9)], baseline=BASE)
    detail["D2-②"] = {"nad": c2["per_county"]["33011"]["nad"],
                      "substantive": c2["counties_nad_substantive"],
                      "thr": CC.nad_substantive_threshold(9, CC.housing_units_of(BASE, "33011"))}
    ok["D2-②"] = (c2["per_county"]["33011"]["nad"] == 9
                  and c2["counties_nad_substantive"] == 0
                  and detail["D2-②"]["thr"] == 10)

    big = ([rec("33011", "nad") for _ in range(500)]
           + [rec("33011", "oa") for _ in range(59_500)])
    c3 = CC.coverage_counters("NH", big, baseline=BASE)
    thr3 = CC.nad_substantive_threshold(c3["per_county"]["33011"]["any"],
                                       CC.housing_units_of(BASE, "33011"))
    # 补到 600 行 NAD（总融合行数仍 60,000 —— 多出的行会抬高阈值，所以要等量换掉 OA）
    big2 = ([rec("33011", "nad") for _ in range(600)]
            + [rec("33011", "oa") for _ in range(59_400)])
    c3b = CC.coverage_counters("NH", big2, baseline=BASE)
    detail["D2-③"] = {"fused": c3["per_county"]["33011"]["any"],
                      "nad": c3["per_county"]["33011"]["nad"], "thr": thr3,
                      "substantive_500": c3["counties_nad_substantive"],
                      "substantive_600": c3b["counties_nad_substantive"]}
    ok["D2-③"] = (thr3 == 600 and c3["counties_nad_substantive"] == 0
                  and c3b["counties_nad_substantive"] == 1)

    overflow = ([rec("33011", "nad", state="MA") for _ in range(30)]
                + [rec("33011", "nad", state="VT") for _ in range(20)]
                + [rec("33011", "oa", state="ME") for _ in range(10)])
    c4 = CC.coverage_counters("NH", overflow, baseline=BASE)
    detail["D2-④"] = {"excluded_state_mismatch": c4["excluded_state_mismatch"],
                      "any_rows": c4["counties_with_any_rows"],
                      "nad_rows": c4["counties_with_nad_rows"]}
    ok["D2-④"] = (c4["excluded_state_mismatch"] == 60 and c4["counties_with_any_rows"] == 0
                  and c4["counties_with_nad_rows"] == 0)

    rings = CC.rings_from_esri_json(KENT_GEOM)
    inside = {"county_fips": "10001", "state_abbr": "DE", "lat": 39.1582, "lon": -75.5244, "source": "nad"}
    outside = {"county_fips": "10001", "state_abbr": "DE", "lat": 40.0000, "lon": -80.0000, "source": "nad"}
    chk = CC.county_boundary_check([inside, outside], rings)
    c5 = CC.coverage_counters("DE", [inside, outside], baseline=BASE,
                              county_geoms={"10001": rings})
    c5b = CC.coverage_counters("DE", [inside], baseline=BASE, county_geoms={"10001": None})
    detail["D2-⑤"] = {"rings": len(rings), "status": chk["status"], "kept": chk["kept"],
                      "rejected": chk["rejected"], "any_rows": c5["counties_with_any_rows"],
                      "excluded_geom": c5["excluded_out_of_county_geometry"],
                      "no_geom_status": c5b["boundary_check"]}
    ok["D2-⑤"] = (len(rings) > 0 and chk["status"] == "checked" and chk["kept"] == 1
                  and chk["rejected"] == 1 and c5["counties_with_any_rows"] == 1
                  and c5["excluded_out_of_county_geometry"] == 1
                  and c5b["boundary_check"] == ["skipped:no_geometry"])

    for k in sorted(ok):
        print("%s: %s  %s" % (k, "✅" if ok[k] else "❌", detail.get(k, "")))
    bad = [k for k, v in ok.items() if not v]
    print("\n总判定：", "✅ 全部通过（%d 条）" % len(ok) if not bad else f"❌ 失败 {bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
