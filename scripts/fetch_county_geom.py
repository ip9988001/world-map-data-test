#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉取「全国县界几何小包」—— 供 D2 第②道清洗（县界真校验）使用。

为什么需要它：D1/D2 定稿要求「点在县多边形内才算该县」，缺几何**必须 fail**、不许 skipped。
所以县界几何必须随仓可用、可校验、可离线复算。

选源（2026-11-22 实测，判据 = 全 3,144 县都有几何）：
  1. 一仓 Release 逐州资产 `TIGER-US-<ST>-county-<FIPS5>.geojson`
     → 实测 51 州 / **3,138 县**，缺 6 个独立市：24510 / 29510 / 51600 / 51620 / 51760 / 51770
     → 覆盖不全，按派单规则「覆盖不全 → 下全国县界小包」继续
  2. Census **TIGERweb** `State_County/MapServer/1`（Counties 图层，官方）
     · 支持 `maxAllowableOffset` 做服务端化简（等价于 500k 精度级别，不需要下全量 TIGER）
     · 单州一次请求，51 次拿全 3,144 县（含 CT 的 9 个 planning region 09110-09190、
       含 MD/VA 的独立市）——**与基准表 3,144 县逐 fips 对齐**
  3. `cb_2024_us_county_500k.zip`（www2.census.gov）本环境被 Cloudflare 403 拦截，
     故走同一官方服务的等价小包（TIGERweb REST），并在 manifest 里写明替代关系。

产物（都进 git，供 CI 离线使用）：
  config/baseline/counties_geom.json.gz      {fips: [rings...]}（5 位小数，gzip）
  config/baseline/county_geom_manifest.json  vintage / source_url / sha256 / bytes / county_count / 覆盖审计

跑法：
  python3 scripts/fetch_county_geom.py            # 拉取 + 写缓存 + 写 manifest（需联网）
  python3 scripts/fetch_county_geom.py --check     # 只校验现有产物（离线）
"""
from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "config" / "baseline" / "counties_census.json"
OUT_GZ = REPO / "config" / "baseline" / "counties_geom.json.gz"
OUT_MAN = REPO / "config" / "baseline" / "county_geom_manifest.json"

SERVICE = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"
LAYER_DOC = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1"
DECIMALS = 5           # ~1.1 m 精度，PIP 判定足够（与 SCHEMA geom.rings_spec 6 位同量级）
MAX_OFFSET = 0.001     # 服务端化简容差（约 100 m），等价 500k 视口精度


def rings_of(geom: dict) -> list:
    """GeoJSON Polygon/MultiPolygon → rings（5 位小数）。"""
    if not geom:
        return []
    t, c = geom.get("type"), geom.get("coordinates") or []
    polys = [c] if t == "Polygon" else (c if t == "MultiPolygon" else [])
    out = []
    for poly in polys:
        for ring in poly:
            pts = [(round(float(x), DECIMALS), round(float(y), DECIMALS)) for x, y in ring]
            if len(pts) >= 4:
                out.append(pts)
    return out


def fetch_state(state_fips: str, timeout: int = 120) -> tuple[str, dict]:
    q = urllib.parse.urlencode({
        "where": f"STATE='{state_fips}'", "outFields": "GEOID,STATE,COUNTY,BASENAME",
        "returnGeometry": "true", "outSR": "4326", "f": "geojson",
        "maxAllowableOffset": str(MAX_OFFSET),
    })
    with urllib.request.urlopen(f"{SERVICE}?{q}", timeout=timeout) as rsp:   # noqa: S310
        raw = rsp.read()
    doc = json.loads(raw.decode("utf-8"))
    got = {}
    for f in doc.get("features") or []:
        fips = str((f.get("properties") or {}).get("GEOID") or "")
        rings = rings_of(f.get("geometry") or {})
        if fips and rings:
            got[fips] = rings
    return state_fips, {"counties": got, "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest()}


def build(baseline: dict) -> dict:
    states = sorted({c["state_fips"] for c in baseline["counties"]})
    per_state, geoms = {}, {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for fips, res in ex.map(fetch_state, states):
            per_state[fips] = {"counties": len(res["counties"]), "bytes": res["bytes"],
                               "geojson_sha256": res["sha256"]}
            geoms.update(res["counties"])
    return {"geoms": geoms, "per_state": per_state}


def write_all(geoms: dict, per_state: dict, baseline: dict, fetched_at: str) -> dict:
    body = json.dumps(geoms, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    OUT_GZ.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_GZ, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(body)
    want = {c["county_fips"] for c in baseline["counties"]}
    missing = sorted(want - set(geoms))
    man = {
        "schema": "county-geom-manifest/v1",
        "purpose": "D2 第②道清洗的唯一几何来源；缺任一县 → fail（不许 skipped）",
        "vintage": "TIGERweb State_County/Counties（2024 版县界，含 CT planning region 09110-09190 与 MD/VA 独立市）",
        "source_url": SERVICE,
        "source_doc": LAYER_DOC,
        "max_allowable_offset_deg": MAX_OFFSET,
        "coordinate_decimals": DECIMALS,
        "fetched_at": fetched_at,
        "county_count": len(geoms),
        "counties_expected": len(want),
        "missing": missing,
        "combined": {"path": "config/baseline/counties_geom.json.gz",
                     "bytes": OUT_GZ.stat().st_size,
                     "sha256": hashlib.sha256(OUT_GZ.read_bytes()).hexdigest(),
                     "body_sha256": hashlib.sha256(body).hexdigest()},
        "source_audit": {
            "yicang_release_assets": {
                "repo": "ip9988001/World-US-Map-Data",
                "note": "逐州 raw-US-<ST>-v1 里的 TIGER-US-<ST>-county-<FIPS5>.geojson；只读核查，未下载",
                "states": 51, "counties": 3138,
                "missing_fips": ["24510", "29510", "51600", "51620", "51760", "51770"],
                "verdict": "覆盖不全（3138/3144）→ 按派单改下全国县界小包",
            },
            "cb_500k_blocked": {
                "url": "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip",
                "verdict": "本环境 Cloudflare 403（curl/scrapling 均被拦），改用同一官方服务的等价小包 TIGERweb REST",
            },
        },
        "per_state": per_state,
        "read_only": "运行期只读；口径变化只能重新生成并改 SCHEMA 引用",
    }
    OUT_MAN.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return man


def check() -> int:
    if not OUT_GZ.exists() or not OUT_MAN.exists():
        print("❌ 几何缓存或 manifest 缺失")
        return 1
    man = json.loads(OUT_MAN.read_text(encoding="utf-8"))
    with gzip.open(OUT_GZ, "rt", encoding="utf-8") as fh:
        geoms = json.load(fh)
    base = json.loads(BASE.read_text(encoding="utf-8"))
    want = {c["county_fips"] for c in base["counties"]}
    have = set(geoms)
    sha_ok = hashlib.sha256(OUT_GZ.read_bytes()).hexdigest() == man["combined"]["sha256"]
    print("county_count=%d  counties_expected=%d  missing=%d  sha256=%s"
          % (len(geoms), len(want), len(want - have), "一致" if sha_ok else "不一致"))
    ok = sha_ok and not (want - have) and len(geoms) == man["county_count"] == len(want)
    print("✅ 县界几何自校验通过（%d/%d）" % (len(want & have), len(want)) if ok
          else "❌ 县界几何自校验失败：缺 %s" % sorted(want - have)[:10])
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        return check()
    baseline = json.loads(BASE.read_text(encoding="utf-8"))
    built = build(baseline)
    man = write_all(built["geoms"], built["per_state"], baseline,
                    _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    print("county_count=%d  missing=%d  gz=%d B  sha256=%s"
          % (man["county_count"], len(man["missing"]), man["combined"]["bytes"],
             man["combined"]["sha256"][:16]))
    if man["missing"]:
        print("❌ 缺几何：%s" % man["missing"], file=sys.stderr)
        return 1
    print("✅ 3,144 县几何齐（TIGERweb 小包）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
