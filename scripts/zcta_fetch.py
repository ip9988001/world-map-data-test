#!/usr/bin/env python3
"""二仓 · ZCTA5 自取器（TIGERweb）—— 二仓自闭环，不改一仓
  
用途：为本州/本县的门牌点提供「邮编面」反查能力，用于
  1) 给 NAD 里 Zip_Code 缺失的行回填 zip5（回填值必须标 zip_source=zcta_derived）
  2) 校验「邮编 ↔ 坐标」是否自相矛盾
  3) 给 Overture/OA 行补邮编缺口
  4) 决定 municipal_city —— ⚠️ ZCTA5 图层**没有城市名**，城市落点走 TIGER places

端点（与一仓同源，实证可用）：
  {tigerweb}/PUMA_TAD_TAZ_UGA_ZCTA/MapServer/1
  
  勘察记录（一仓 fetch_state_raw.py 已踩过）：
  * ZCTA 图层**没有 STATE 字段** —— 带 STATE 条件会 400 Failed to execute query
  * 只能用 ZCTA5 区间（ZCTA5>='lo' AND ZCTA5<='hi'）或空间信封查询
  * 单次返回有记录上限，可能触发 exceededTransferLimit → 必须分页

零新依赖：只用标准库 urllib / gzip / json。

输出（ndjson.gz，一行一个面）：
  {"zcta5": "57317", "geoid": "...", "rings": [[[lon,lat],...],...]}

用法
  python3 scripts/zcta_fetch.py --state SD --zcta-range 57300-57599
  python3 scripts/zcta_fetch.py --state SD --bbox -99.5,42.9,-98.4,43.5 --out data/zcta
  python3 scripts/zcta_fetch.py --self-check          # 只发 1 次查询验证端点
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REGISTRY_ENDPOINTS = {
    "tigerweb": "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb",
}
ZCTA_LAYER = "{tigerweb}/PUMA_TAD_TAZ_UGA_ZCTA/MapServer/1"
UA = "world-map-data-test/2.0 (+zcta-fetch)"
PAGE = 2000           # 单页记录数上限（实际会按服务端 maxRecordCount 收紧）
MAX_PAGE_RETRY = 3
_META: dict = {}


def log(msg: str) -> None:
    print(f"[zcta] {msg}", flush=True)


def _get(url: str, params: dict, timeout: int = 90) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{qs}", headers={"User-Agent": UA})
    last = None
    for attempt in range(MAX_PAGE_RETRY):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"查询失败 {url}: {last}")


def layer_meta() -> dict:
    """⚠️ 踩坑记录：查询必须打 /query，打 /1 拿到的是图层元数据（没有 features 键）。"""
    if not _META:
        _META.update(_get(ZCTA_LAYER.format(**REGISTRY_ENDPOINTS), {"f": "json"}))
        log(f"图层：{_META.get('name')} | maxRecordCount={_META.get('maxRecordCount')} | 字段={[f['name'] for f in (_META.get('fields') or [])][:8]}")
    return _META


def query_page(where: str, offset: int, bbox: tuple | None) -> dict:
    cap = int(layer_meta().get("maxRecordCount") or PAGE)
    params = {
        "f": "json",
        "where": where,
        "outFields": "ZCTA5,GEOID",
        "returnGeometry": "true",
        "outSR": "4326",
        "resultOffset": str(offset),
        "resultRecordCount": str(min(PAGE, cap)),
    }
    if bbox:
        w, s, e, n = bbox
        params.update({
            "geometry": f"{w},{s},{e},{n}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
        })
    return _get(ZCTA_LAYER.format(**REGISTRY_ENDPOINTS) + "/query", params)


def features_of(payload: dict) -> list[dict]:
    feats = payload.get("features") or []
    out = []
    for f in feats:
        attrs = f.get("attributes") or {}
        geom = f.get("geometry") or {}
        rings = geom.get("rings") or []
        z = str(attrs.get("ZCTA5") or "").strip()
        if not z or not rings:
            continue
        out.append({
            "zcta5": z,
            "geoid": str(attrs.get("GEOID") or ""),
            "rings": [[[float(x), float(y)] for x, y in ring] for ring in rings],
        })
    return out


def fetch(where: str, bbox: tuple | None, max_rows: int = 100000) -> list[dict]:
    seen: dict[str, dict] = {}
    offset = 0
    while True:
        payload = query_page(where, offset, bbox)
        if payload.get("error"):
            raise RuntimeError(f"esri error: {payload['error']}")
        batch = features_of(payload)
        for rec in batch:
            seen.setdefault(rec["zcta5"], rec)
        exceeded = bool(payload.get("exceededTransferLimit"))
        log(f"页 offset={offset} 取回 {len(batch)} 个面，累计 {len(seen)}，exceeded={exceeded}")
        if not exceeded or not batch:
            break
        offset += len(batch)
        if offset > max_rows:
            log(f"⚠️ 触达 max_rows={max_rows}，提前停止（请缩小范围）")
            break
    return list(seen.values())


def write_ndjson_gz(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        for rec in sorted(rows, key=lambda r: r["zcta5"]):
            fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TIGERweb ZCTA5 自取器（二仓自闭环）")
    ap.add_argument("--state", help="两位州码，仅用于命名")
    ap.add_argument("--zcta-range", help="邮编区间 lo-hi，如 57300-57599（推荐：由 NAD Zip_Code 实测推导）")
    ap.add_argument("--bbox", help="W,S,E,N；与 --zcta-range 二选一或叠加")
    ap.add_argument("--out", default="data/zcta", help="输出目录")
    ap.add_argument("--force", action="store_true", help="已有产物也重跑")
    ap.add_argument("--self-check", action="store_true", help="只查一个邮编验证端点")
    args = ap.parse_args(argv)

    if args.self_check:
        payload = query_page("ZCTA5='19901'", 0, None)
        recs = features_of(payload)
        log(f"自检：ZCTA5=19901 → {len(recs)} 个面，ring 数={[len(r['rings']) for r in recs]}")
        return 0 if recs else 2

    if not args.zcta_range and not args.bbox:
        log("必须给 --zcta-range 或 --bbox 之一（ZCTA 图层无 STATE 字段，不能按州名查）")
        return 2

    where = "1=1"
    if args.zcta_range:
        lo, hi = [x.strip() for x in args.zcta_range.split("-", 1)]
        where = f"ZCTA5>='{lo}' AND ZCTA5<='{hi}'"

    bbox = None
    if args.bbox:
        bbox = tuple(float(x) for x in args.bbox.split(","))

    out = Path(args.out) / f"zcta-US-{args.state or 'XX'}.ndjson.gz"
    if out.exists() and not args.force:
        with gzip.open(out, "rt") as fh:
            n = sum(1 for _ in fh)
        log(f"已存在 {out}（{n} 行），跳过；--force 可重跑")
        return 0

    rows = fetch(where, bbox)
    if not rows:
        log("⚠️ 取回 0 个面 —— 端点可能降级或条件写错")
        return 2
    write_ndjson_gz(rows, out)
    log(f"写出 {out}：{len(rows)} 个 ZCTA 面，{out.stat().st_size} B")
    log(f"邮编范围：{min(r['zcta5'] for r in rows)} ~ {max(r['zcta5'] for r in rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
