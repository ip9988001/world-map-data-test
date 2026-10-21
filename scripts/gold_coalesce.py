#!/usr/bin/env python3
"""二仓 · Gold 层引擎 v2（schema 2.0）
================================================================================
一行 = 一条标准化地址；作用域 = 单县；输出 = ADDR-US-<ST>-<fips>-<key>.ndjson.gz

四条铁律（沿用 TASK-003 方案一裁定）
  1. 独立源计票：NAD / TIGER / OA 三票；Overture 上游溯源 NAD，不计独立票
  2. TIGER 校验必须叠加空间约束：号段区间命中 AND 点线距离 <= 60m AND 奇偶匹配
  3. 漏斗四栏分开：out_of_bounds / malformed / unendorsed_orphan / dedup，不混计
  4. 同址合并：同「门牌+街名+unit」只留最佳代表行，dup_group / dup_members 留痕

分源独立记账（架构门禁，任一不守恒 → exit 1）
  NAD : input == output + malformed + out_of_bounds + dedup
  OA  : input == absorbed + unendorsed_orphan + malformed + dedup
  OVT : input == absorbed + unendorsed_orphan + out_of_bounds + malformed + dedup
  合计: output_rows == Σ output（每行必有 NAD 背书）

依赖纪律（架构裁决 2026-10-18）
  * duckdb 只作 GeoParquet I/O 驱动；**严禁 INSTALL spatial**，几何用 cast(... AS VARCHAR) 抠
  * 严禁 shapely / geopandas / rtree；空间一律网格索引 + point_in_rings()

用法
  python3 scripts/gold_coalesce.py --scope data/gold/US-SD/scope.json \
      --raw-dir data/raw/US-SD --cache data/cache/US-SD --out data/gold/US-SD
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import re
import sys
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

GRID = 0.001                 # 网格边长 ~85m @ lat40
UNSAFE = "__unsafe__"        # SpatialIndex 记忆化：边界格永不缓存结论
MATCH_METERS = 60.0
TIGER_METERS = 60.0

DIRECTION = {
    "N": "North", "S": "South", "E": "East", "W": "West",
    "NE": "Northeast", "NW": "Northwest", "SE": "Southeast", "SW": "Southwest",
    "NORTH": "North", "SOUTH": "South", "EAST": "East", "WEST": "West",
    "NORTHEAST": "Northeast", "NORTHWEST": "Northwest",
    "SOUTHEAST": "Southeast", "SOUTHWEST": "Southwest",
}
SUFFIX = {
    "RD": "Road", "ROAD": "Road", "DR": "Drive", "DRIVE": "Drive",
    "ST": "Street", "STREET": "Street", "AVE": "Avenue", "AV": "Avenue", "AVENUE": "Avenue",
    "LN": "Lane", "LANE": "Lane", "CT": "Court", "COURT": "Court",
    "CIR": "Circle", "CIRCLE": "Circle", "BLVD": "Boulevard", "BOULEVARD": "Boulevard",
    "HWY": "Highway", "HIGHWAY": "Highway", "PL": "Place", "PLACE": "Place",
    "WAY": "Way", "TRL": "Trail", "TRAIL": "Trail", "TER": "Terrace", "TERRACE": "Terrace",
    "PKWY": "Parkway", "PARKWAY": "Parkway", "EXT": "Extension", "EXTENSION": "Extension",
    "RUN": "Run", "GRN": "Green", "GREEN": "Green", "XING": "Crossing", "CROSSING": "Crossing",
    "PATH": "Path", "CRK": "Creek", "CREEK": "Creek", "PLZ": "Plaza", "PLAZA": "Plaza",
    "LAND": "Land", "ALY": "Alley", "ALLEY": "Alley", "LOOP": "Loop", "BND": "Bend",
    "TPKE": "Turnpike", "TURNPIKE": "Turnpike", "EXPY": "Expressway", "FWY": "Freeway",
    "HTS": "Heights", "JCT": "Junction", "PT": "Point", "RDG": "Ridge", "SPG": "Spring",
    "CV": "Cove", "BRG": "Bridge", "CTR": "Center", "MNR": "Manor", "EST": "Estates",
    "ESTS": "Estates", "SQ": "Square", "VLG": "Village", "WDS": "Woods", "GRV": "Grove",
    "GDN": "Garden", "GLN": "Glen", "KNL": "Knoll", "ML": "Mill", "STA": "Station",
    "SMT": "Summit", "VW": "View", "MDW": "Meadow", "PASS": "Pass", "PIKE": "Pike",
}
UNIT_PREFIX = re.compile(r"^(APT|APARTMENT|STE|SUITE|UNIT|RM|ROOM|#|NO|LOT|BLDG)\s*[\.\-]?\s*", re.I)
PUNCT = re.compile(r"[^A-Z0-9 ]+")
NULLISH = {"", "<NULL>", "NULL", "NONE", "N/A", "NA", "UNKNOWN", "NOT STATED"}
COMMERCIAL_HINT = re.compile(
    r"\b(PLAZA|CTR|CENTER|MALL|SHOPPING|OFFICE|SUITE|STE|BUSINESS|PARK|HOTEL|"
    r"RESTAURANT|BANK|STORE|MARKET|PHARMACY|CLINIC|HOSPITAL|SCHOOL|CHURCH|"
    r"INDUSTRIAL|WAREHOUSE|AIRPORT)\b")
POINT_RE = re.compile(r"POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)", re.I)


# ---------------------------------------------------------------- 通用
def log(msg: str) -> None:
    print(f"[gold] {msg}", flush=True)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return None if s.upper() in NULLISH else s


def title_case(s: str | None) -> str | None:
    if not s:
        return None
    return " ".join(w.capitalize() if not w.isupper() or len(w) > 3 else w.title()
                    for w in s.split())


def parse_number(v) -> str | None:
    s = clean_str(v)
    if not s:
        return None
    m = re.match(r"^(\d+)", s.replace(",", ""))
    return m.group(1) if m else None


def num_int(s: str | None) -> int | None:
    try:
        return int(s) if s is not None else None
    except ValueError:
        return None


def norm_street_token(tok: str) -> str:
    t = PUNCT.sub("", tok.upper()).strip()
    return SUFFIX.get(t, t)


def street_key(street: str | None, post_type: str | None = None,
               pre_dir: str | None = None, post_dir: str | None = None) -> str | None:
    """归一化街道键：`TYPE|CORE`（方向词不参与，避免 NAD 拆字段与 OA 自由串对不上）。"""
    if not street:
        return None
    s = PUNCT.sub(" ", street.upper())
    toks = [t for t in s.split() if t]
    toks = [t for t in toks if t not in DIRECTION]
    core, suf = [], None
    for t in toks:
        if t in SUFFIX:
            suf = SUFFIX[t]
        else:
            core.append(t)
    if post_type:
        st = SUFFIX.get(post_type.upper(), post_type.upper())
        if not suf:
            suf = st
    if not core:
        return None
    return f"{(suf or '').upper()}|{' '.join(core)}"


def norm_unit(v) -> tuple[str | None, str | None]:
    s = clean_str(v)
    if not s:
        return None, None
    s = UNIT_PREFIX.sub("", s).strip()
    key = PUNCT.sub("", s.upper())
    return (s or None), (key or None)


def addr_key(num: str | None, skey: str | None, ukey: str | None) -> str | None:
    if not num or not skey:
        return None
    return f"{num}|{skey}|{ukey or ''}"


# ---------------------------------------------------------------- 几何
def point_in_rings(lon: float, lat: float, rings: list) -> bool:
    inside = False
    for ring in rings:
        n = len(ring)
        if n < 3:
            continue
        j = n - 1
        for i in range(n):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-18) + xi):
                inside = not inside
            j = i
    return inside


def rings_bbox(rings: list) -> tuple:
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)


def grid_key(lon: float, lat: float) -> tuple:
    return (int(math.floor(lon / GRID)), int(math.floor(lat / GRID)))


def hav_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def seg_distance_m(lon: float, lat: float, ax: float, ay: float, bx: float, by: float) -> float:
    """点到线段的近似距离（米）。经度按纬度缩放。"""
    k = math.cos(math.radians(lat))
    px, py, ax_, ay_ = lon * k, lat, ax * k, ay
    bx_, by_ = bx * k, by
    dx, dy = bx_ - ax_, by_ - ay_
    if dx == 0 and dy == 0:
        return hav_m(lon, lat, ax, ay)
    t = max(0.0, min(1.0, ((px - ax_) * dx + (py - ay_) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax_ + t * dx, ay_ + t * dy
    return math.hypot(px - cx, py - cy) * 111320.0


class SpatialIndex:
    """网格索引：多边形点位反查（ZCTA / places / county），零第三方依赖。

    ⚠️ cell 必须按要素尺度选：多边形用 0.01°（~1.1km），否则一个县大小的 bbox
    在 0.001° 网格下会展开成十几万个格子，构建时间爆炸（实测踩过）。
    """

    def __init__(self, items: list[dict], key_field: str, cell: float = 0.01):
        self.items = {}
        self.grid = defaultdict(list)
        self.cell = cell
        self._memo = {}
        for it in items:
            k = it[key_field]
            it["bbox"] = rings_bbox(it["rings"])
            self.items[k] = it
            x0, y0, x1, y1 = it["bbox"]
            for gx in range(int(x0 // cell), int(x1 // cell) + 1):
                for gy in range(int(y0 // cell), int(y1 // cell) + 1):
                    self.grid[(gx, gy)].append(k)

    def _exact(self, lon: float, lat: float):
        for k in self.grid.get((int(lon // self.cell), int(lat // self.cell)), ()):
            it = self.items[k]
            x0, y0, x1, y1 = it["bbox"]
            if x0 <= lon <= x1 and y0 <= lat <= y1 and point_in_rings(lon, lat, it["rings"]):
                return k
        return None

    def find(self, lon: float, lat: float):
        """点位反查（带「安全格」记忆化）。

        城市点位高度聚集在同一 110m 格内，重复做点在多边形测试是纯浪费。
        但**不能**把首个点的结论直接缓存给整格 —— 边界格会串县（实测 SD 会错 213 行）。
        做法：仅当格的 4 角 + 中心 5 个采样点结论一致时，才认定为「安全格」并缓存；
        边界格标记为 unsafe，永远走精确路径。
        """
        gx, gy = int(lon // self.cell), int(lat // self.cell)
        gk = (gx, gy)
        st = self._memo.get(gk)
        if st is not None:
            if st is UNSAFE:
                return self._exact(lon, lat)
            return st
        x0, y0 = gx * self.cell, gy * self.cell
        x1, y1 = x0 + self.cell, y0 + self.cell
        probes = [self._exact(x0, y0), self._exact(x1, y0), self._exact(x0, y1),
                  self._exact(x1, y1), self._exact(x0 + self.cell / 2, y0 + self.cell / 2)]
        if probes[0] is not None and len(set(probes)) == 1:
            self._memo[gk] = probes[0]
            return self._exact(lon, lat) if False else self._memo[gk]
        self._memo[gk] = UNSAFE
        return self._exact(lon, lat)


# ---------------------------------------------------------------- 读取：边界 / ZCTA / places
def load_esri_rings(path: Path) -> list[dict]:
    """TIGERweb 返回的是 Esri JSON（.geojson 后缀是历史包袱），只认 geometry.rings。"""
    if not path or not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("error"):
        log(f"⚠️ 边界文件是 esri error：{path.name}")
        return []
    out = []
    for i, f in enumerate(data.get("features") or []):
        rings = [[(float(x), float(y)) for x, y in ring]
                 for ring in (f.get("geometry") or {}).get("rings") or []]
        if rings:
            out.append({"id": str(i), "rings": rings, "attrs": f.get("attributes") or {}})
    return out


def load_zcta(path: Path) -> list[dict]:
    if not path or not path.exists():
        return []
    out = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            out.append({"zcta5": r["zcta5"], "rings": r["rings"]})
    return out


def load_places(zip_path: Path) -> list[dict]:
    if not zip_path or not zip_path.exists():
        return []
    import shapefile
    zf = zipfile.ZipFile(zip_path)
    shp = [n for n in zf.namelist() if n.endswith(".shp")]
    if not shp:
        return []
    shp = shp[0]
    r = shapefile.Reader(shp=io.BytesIO(zf.read(shp)),
                         dbf=io.BytesIO(zf.read(shp[:-4] + ".dbf")),
                         shx=io.BytesIO(zf.read(shp[:-4] + ".shx")))
    fields = [f[0] for f in r.fields[1:]]
    i_name = fields.index("NAME") if "NAME" in fields else None
    out = []
    for sr in r.iterShapeRecords():
        pts = getattr(sr.shape, "points", [])
        parts = list(getattr(sr.shape, "parts", [0])) + [len(pts)]
        rings = []
        for a, b in zip(parts, parts[1:]):
            ring = [(float(x), float(y)) for x, y in pts[a:b]]
            if len(ring) >= 3:
                rings.append(ring)
        if rings:
            name = sr.record[i_name] if i_name is not None else None
            out.append({"place": str(len(out)), "name": name, "rings": rings})
    return out


# ---------------------------------------------------------------- 读取：NAD
def read_nad(path: Path) -> list[dict]:
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            lon = r.get("Longitude") if r.get("Longitude") not in (None, "") else r.get("_lon")
            lat = r.get("Latitude") if r.get("Latitude") not in (None, "") else r.get("_lat")
            rows.append({
                "raw": r,
                "num": parse_number(r.get("Add_Number") or r.get("AddNo_Full")),
                "street_full": clean_str(r.get("StNam_Full")) or clean_str(r.get("St_Name")),
                "skey": street_key(clean_str(r.get("St_Name")) or clean_str(r.get("StNam_Full")),
                                   clean_str(r.get("St_PosTyp")),
                                   clean_str(r.get("St_PreDir")),
                                   clean_str(r.get("St_PosDir"))),
                "pre_dir": DIRECTION.get(str(r.get("St_PreDir") or "").upper()),
                "post_type": SUFFIX.get(str(r.get("St_PosTyp") or "").upper()),
                "post_dir": DIRECTION.get(str(r.get("St_PosDir") or "").upper()),
                "unit": norm_unit(r.get("Unit"))[0],
                "ukey": norm_unit(r.get("Unit"))[1],
                "lon": float(lon) if lon not in (None, "") else None,
                "lat": float(lat) if lat not in (None, "") else None,
                "zip5": clean_str(r.get("Zip_Code")),
                "city": clean_str(r.get("Post_City")),
                "muni": clean_str(r.get("Inc_Muni")),
                "county": clean_str(r.get("County")),
            })
    return rows


# ---------------------------------------------------------------- 读取：OpenAddresses（一次扫描多县分桶）
def bucket_oa_statewide(zip_path: Path, county_index: SpatialIndex, cache_dir: Path,
                        fips_list: list[str], write_fips: set | None = None) -> dict:
    """全州 OA 一次流式扫描，按县分桶落 ndjson.gz；已有缓存直接复用。

    write_fips: 只对这批县落盘；其余县（含 0-NAD 县）只计数，用于账本拆栏。
    """
    pkg_dir = cache_dir / zip_path.name.replace(".zip", "").replace("OA-", "oa-")
    pkg_dir.mkdir(parents=True, exist_ok=True)
    targets = {f: pkg_dir / f"oa-US-{f}.ndjson.gz" for f in fips_list}
    write_fips = write_fips if write_fips is not None else set(fips_list)
    if all(p.exists() for p in targets.values()):
        log(f"OA 分桶缓存命中（{len(targets)} 县）")
        return {f: sum(1 for _ in gzip.open(p, "rt")) for f, p in targets.items()}

    log(f"OA 全州单次扫描：{zip_path.name}")
    zf = zipfile.ZipFile(zip_path)
    members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
    handles = {}
    counts = Counter()
    header = None
    tot = 0
    for m in members:
        with zf.open(m) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
            for i, row in enumerate(csv.DictReader(text)):
                if header is None:
                    header = row.keys()
                tot += 1
                try:
                    lon = float(row.get("LON") or "")
                    lat = float(row.get("LAT") or "")
                except ValueError:
                    continue
                fips = county_index.find(lon, lat)
                if not fips:
                    continue
                counts[fips] += 1
                if fips not in write_fips:
                    continue
                if fips not in handles:
                    handles[fips] = gzip.open(targets[fips], "wt", encoding="utf-8")
                rec = {
                    "number": row.get("NUMBER"), "street": row.get("STREET"),
                    "unit": row.get("UNIT"), "city": row.get("CITY"),
                    "district": row.get("DISTRICT"), "region": row.get("REGION"),
                    "postcode": row.get("POSTCODE"), "id": row.get("ID"),
                    "hash": row.get("HASH"), "lon": lon, "lat": lat,
                    "file": m.rsplit("/", 1)[-1].replace(".csv", ""),
                }
                handles[fips].write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    for h in handles.values():
        h.close()
    log(f"OA 扫描 {tot} 行 → 落盘 {len(handles)} 县，命中县内合计 {sum(counts.values())} 行；"
        f"界外 {tot - sum(counts.values())} 行；无 NAD 县 {sum(v for k, v in counts.items() if k not in write_fips)} 行")
    return dict(counts)


def read_oa_bucket(cache_dir: Path, fips: str) -> list[dict]:
    """合并该县在所有 OA 包下的分桶（每包一个子目录，避免包间互相覆盖）。"""
    out = []
    for path in sorted(cache_dir.glob(f"*/oa-US-{fips}.ndjson.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    r["num"] = parse_number(r.get("number"))
                    r["skey"] = street_key(r.get("street"))
                    r["unit_k"], r["ukey"] = norm_unit(r.get("unit"))
                    r["_pkg"] = path.parent.name
                    out.append(r)
    return out


# ---------------------------------------------------------------- 读取：Overture（DuckDB，零 spatial 扩展）
def read_overture_slice(parquet: Path, bbox: tuple) -> list[dict]:
    import duckdb
    w, s, e, n = bbox
    sql = f"""
        SELECT id, number, street, unit, postcode, postal_city, address_levels,
               sources[1].dataset AS src_ds,
               cast(geometry AS VARCHAR) AS geom
        FROM read_parquet('{parquet.as_posix()}')
        WHERE bbox.xmin >= {w} AND bbox.xmax <= {e}
          AND bbox.ymin >= {s} AND bbox.ymax <= {n}
    """
    con = duckdb.connect()
    rows = []
    for (oid, number, street, unit, postcode, postal_city, levels, src_ds, geom) in con.execute(sql).fetchall():
        m = POINT_RE.search(geom or "")
        if not m:
            continue
        rows.append({
            "id": oid, "num": parse_number(number), "street": street,
            "skey": street_key(street), "unit": norm_unit(unit)[0],
            "ukey": norm_unit(unit)[1], "zip5": clean_str(postcode),
            "city": clean_str(postal_city),
            "levels": [x.get("value") for x in (levels or []) if isinstance(x, dict)],
            "upstream": src_ds,
            "lon": float(m.group(1)), "lat": float(m.group(2)),
        })
    con.close()
    return rows


def bbox_split_antimeridian(bbox: tuple) -> list[tuple]:
    """跨 180° 经线的 bbox 拆成两段。AK 的 roster bbox 是 [-179.231, …, 179.86, …]，
    宽度 ≈ 359°，不拆的话 WHERE 条件会匹配地球上几乎所有行（4GB parquet 全量载入 → OOM）。"""
    w, s, e, n = bbox
    if w <= e and (e - w) <= 180.0:
        return [(w, s, e, n)]
    return [(w, s, 180.0, n), (-180.0, s, e, n)]


# ---------------------------------------------------------------- 读取：Overture（全州一次切片，分县分桶）
def bucket_overture(parquet, county_index: SpatialIndex, cache_dir: Path,
                    write_fips: set, state_bbox: tuple) -> tuple[dict, int]:
    """全州只扫一次 parquet（O(1) 次扫描），按县多边形分桶落 ndjson.gz。

    ⚠️ 旧实现是「每县一次 duckdb 查询」，AR(275MB × 75 县) 单这一项就吃掉 20 分钟。
    这里复用 OA 已验证的「一次扫描 + 分桶」模式：扫描次数从 N 县降到 1 次。
    """
    import duckdb
    pkg_dir = cache_dir / "overture"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    # ★ 2026-10-21 修 G5：支持「州级单文件」与「按县多文件」两种输入（一仓两种都会出）。
    paths = [Path(x) for x in (parquet if isinstance(parquet, (list, tuple)) else [parquet])]
    paths = [x for x in paths if x.exists()]
    if not paths:
        raise FileNotFoundError(f"Overture parquet 不存在：{parquet}")
    sig = ",".join(x.name for x in paths)
    targets = {f: pkg_dir / f"ovt-US-{f}.ndjson.gz" for f in write_fips}
    stats_path = pkg_dir / "_stats.json"
    if all(p.exists() for p in targets.values()):
        st = json.loads(stats_path.read_text()) if stats_path.exists() else {}
        if st.get("sig") == sig:                       # 文件集合没变才算缓存命中
            log(f"Overture 分桶缓存命中（{len(targets)} 县 / {len(paths)} 个文件，"
                f"州外 {st.get('outside', 0):,} 行）")
            return ({f: sum(1 for _ in gzip.open(p, "rt")) for f, p in targets.items()},
                    st.get("outside", 0))
        log("Overture 输入文件集合已变 → 缓存作废，重新分桶")

    # bbox 跨 180° 经线（AK）必须拆两段，否则等价于「全球查询」——实测 AK 会直接爆内存
    boxes = bbox_split_antimeridian(state_bbox)
    conds = " OR ".join(
        f"(bbox.xmin >= {w} AND bbox.xmax <= {e} AND bbox.ymin >= {s} AND bbox.ymax <= {n})"
        for (w, s, e, n) in boxes)
    # 按县分片是「按县 bbox 切」的产物，相邻县必然重叠 → 用 DISTINCT ON (id) 去重
    src = "[" + ", ".join(f"'{x.as_posix()}'" for x in paths) + "]"
    sql = f"""
        SELECT DISTINCT ON (id) id, number, street, unit, postcode, postal_city, address_levels,
               sources[1].dataset AS src_ds,
               cast(geometry AS VARCHAR) AS geom
        FROM read_parquet({src})
        WHERE {conds}
    """
    if len(boxes) > 1:
        log(f"⚠️ bbox 跨 180° 经线 → 拆成 {len(boxes)} 段查询：{boxes}")
    con = duckdb.connect()
    cur = con.execute(sql)
    handles = {}
    counts = Counter()
    total = 0
    outside = 0
    while True:
        chunk = cur.fetchmany(20000)
        if not chunk:
            break
        for (oid, number, street, unit, postcode, postal_city, levels, src_ds, geom) in chunk:
            total += 1
            m = POINT_RE.search(geom or "")
            if not m:
                continue
            lon, lat = float(m.group(1)), float(m.group(2))
            fips = county_index.find(lon, lat)
            if not fips:
                outside += 1
                continue
            if fips not in write_fips:
                counts[fips] += 1          # 0-NAD 县只计数
                continue
            if fips not in handles:
                handles[fips] = gzip.open(targets[fips], "wt", encoding="utf-8")
            rec = {
                "id": oid, "number": number, "street": street, "unit": unit,
                "postcode": postcode, "postal_city": postal_city,
                "levels": [x.get("value") for x in (levels or []) if isinstance(x, dict)],
                "upstream": src_ds, "lon": lon, "lat": lat,
            }
            handles[fips].write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
            counts[fips] += 1
    for h in handles.values():
        h.close()
    con.close()
    stats_path.write_text(json.dumps({"total": total, "outside": outside, "sig": sig,
                                     "files": len(paths)}), encoding="utf-8")
    log(f"Overture 单次扫描 {total:,} 行 → 分桶 {len(handles)} 县，"
        f"县内 {sum(v for k, v in counts.items() if k in write_fips):,} 行，州外/海上 {outside:,} 行")
    return dict(counts), outside


def read_ovt_bucket(cache_dir: Path, fips: str) -> list[dict]:
    path = cache_dir / "overture" / f"ovt-US-{fips}.ndjson.gz"
    if not path.exists():
        return []
    out = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            r["num"] = parse_number(r.get("number"))
            r["skey"] = street_key(r.get("street"))
            r["unit_k"], r["ukey"] = norm_unit(r.get("unit"))
            r["zip5"] = clean_str(r.get("postcode"))
            r["city"] = clean_str(r.get("postal_city"))
            out.append(r)
    return out


# ---------------------------------------------------------------- 读取：TIGER addrfeat
def read_addrfeat(zip_path: Path) -> list[dict]:
    import shapefile
    if not zip_path.exists():
        return []
    zf = zipfile.ZipFile(zip_path)
    shp = [n for n in zf.namelist() if n.endswith(".shp")][0]
    r = shapefile.Reader(shp=io.BytesIO(zf.read(shp)),
                         dbf=io.BytesIO(zf.read(shp[:-4] + ".dbf")),
                         shx=io.BytesIO(zf.read(shp[:-4] + ".shx")))
    fields = [f[0] for f in r.fields[1:]]
    idx = {n: i for i, n in enumerate(fields)}
    segs = []
    for sr in r.iterShapeRecords():
        rec = sr.record
        pts = getattr(sr.shape, "points", [])
        if len(pts) < 2:
            continue
        name = rec[idx["FULLNAME"]] if "FULLNAME" in idx else None
        skey = street_key(name)
        if not skey:
            continue
        segs.append({
            "tlid": str(rec[idx["TLID"]]) if "TLID" in idx else None,
            "skey": skey,
            "fullname": name,
            "lfrom": parse_number(rec[idx["LFROMHN"]]) if "LFROMHN" in idx else None,
            "lto": parse_number(rec[idx["LTOHN"]]) if "LTOHN" in idx else None,
            "rfrom": parse_number(rec[idx["RFROMHN"]]) if "RFROMHN" in idx else None,
            "rto": parse_number(rec[idx["RTOHN"]]) if "RTOHN" in idx else None,
            "parityl": (rec[idx["PARITYL"]] or "").strip() if "PARITYL" in idx else "",
            "parityr": (rec[idx["PARITYR"]] or "").strip() if "PARITYR" in idx else "",
            "zipl": (rec[idx["ZIPL"]] or "").strip() if "ZIPL" in idx else "",
            "points": [(float(x), float(y)) for x, y in pts],
        })
    return segs


def build_seg_index(segs: list[dict]) -> dict:
    idx = defaultdict(list)
    for s in segs:
        idx[s["skey"]].append(s)
    return idx


def tiger_check(seg_index: dict, num: str, skey: str, lon: float, lat: float) -> tuple[str, float | None, str | None]:
    """返回 (verify, distance_m, tlid)。verify ∈ range / street / none"""
    n = num_int(num)
    best = None
    for seg in seg_index.get(skey, ()):
        d = min(seg_distance_m(lon, lat, seg["points"][i][0], seg["points"][i][1],
                               seg["points"][i + 1][0], seg["points"][i + 1][1])
                for i in range(len(seg["points"]) - 1))
        if best is None or d < best[0]:
            best = (d, seg)
    if not best:
        return "none", None, None
    d, seg = best
    if d > TIGER_METERS:
        return "none", round(d, 1), seg["tlid"]
    if n is None:
        return "street", round(d, 1), seg["tlid"]
    for a, b, par in ((seg["lfrom"], seg["lto"], seg["parityl"]), (seg["rfrom"], seg["rto"], seg["parityr"])):
        ia, ib = num_int(a), num_int(b)
        if ia is None or ib is None:
            continue
        lo, hi = min(ia, ib), max(ia, ib)
        if not (lo <= n <= hi):
            continue
        if par.upper() == "O" and n % 2 != 1:
            continue
        if par.upper() == "E" and n % 2 != 0:
            continue
        return "range", round(d, 1), seg["tlid"]
    return "street", round(d, 1), seg["tlid"]


# ---------------------------------------------------------------- 主流程：单县
def upstream_gaps(scope: dict) -> dict:
    """★ 2026-10-21 修 G7：把「上游缺几个县 / 哪几个县」原样带进产物。

    用户口径：缺县的州照样加工，但产物里必须标明缺几个、缺哪几个 ——
    不许静默把「缺县的州」当完整州流到下游。
    """
    g = scope.get("upstream_gaps") or {}
    missing = g.get("missing_counties") or []
    skipped = scope.get("skipped_counties") or []
    return {
        "phase": g.get("phase") or "unknown",
        "complete_partial": bool(g.get("complete_partial")),
        "missing_count": len(missing),
        "missing_counties": missing,
        "skipped_by_assets_count": len(skipped),
        "skipped_by_assets": [s.get("fips") if isinstance(s, dict) else s for s in skipped],
        "note": ("上游声明有县缺失：本段为权威缺口清单；coverage.nad_backed_counties 不含这些县。"
                 "缺县不影响已产数据的可信度，但下游不得当完整州使用。"),
    }


def process_county(scope: dict, county: dict, raw_dir: Path, cache_dir: Path,
                   oa_buckets: dict, zcta_idx: SpatialIndex | None,
                   place_idx: SpatialIndex | None, county_rings: list,
                   out_dir: Path) -> dict:
    t0 = time.time()
    fips = county["fips"]
    funnel = {"county": fips, "county_name": county["name"]}
    log(f"—— 县 {fips} {county['name']} ——")

    # ---- NAD
    nad_rows = read_nad(raw_dir / county["nad_file"])
    if county.get("nad_from_overflow"):
        want = (county.get("name") or "").strip().lower()
        before = len(nad_rows)
        nad_rows = [r for r in nad_rows if (r.get("county") or "").strip().lower() == want]
        funnel["nad_source"] = f"overflow_by_county_field({len(nad_rows)}/{before})"
    funnel["nad_input"] = len(nad_rows)
    nad_bad = Counter()
    nad_clean = []
    for r in nad_rows:
        if not r["num"] or not r["skey"]:
            nad_bad["missing_number_or_street"] += 1
            continue
        if r["lon"] is None or r["lat"] is None:
            nad_bad["coord_null"] += 1
            continue
        if (county_rings and not county.get("nad_from_overflow")
                and not point_in_rings(r["lon"], r["lat"], county_rings)):
            nad_bad["out_of_bounds"] += 1
            continue
        nad_clean.append(r)

    # 同址合并：同 key 保留最佳代表行
    by_key: dict[str, list[dict]] = defaultdict(list)
    for r in nad_clean:
        by_key[addr_key(r["num"], r["skey"], r["ukey"])].append(r)
    nad_keys = {}
    dedup_nad = 0

    def nad_score(r):
        return (1 if r["zip5"] else 0, 1 if r["unit"] else 0,
                1 if r["city"] else 0, len(r["raw"].get("UUID") or ""))

    for k, group in by_key.items():
        group.sort(key=nad_score, reverse=True)
        nad_keys[k] = {"rep": group[0], "members": len(group)}
        dedup_nad += len(group) - 1

    # ---- OA（读本县分桶）
    oa_rows = read_oa_bucket(cache_dir, fips)
    funnel["oa_input"] = len(oa_rows)
    oa_bad = Counter()
    oa_votes = Counter()
    oa_meta = {}
    oa_dedup = 0
    seen_oa = set()
    for r in oa_rows:
        if not r["num"] or not r["skey"]:
            oa_bad["missing_number_or_street"] += 1
            continue
        k = addr_key(r["num"], r["skey"], r["ukey"])
        if k in seen_oa:
            oa_dedup += 1
            continue
        seen_oa.add(k)
        if k in nad_keys:
            oa_votes[k] += 1
            oa_meta.setdefault(k, r)
        else:
            oa_bad["unendorsed_orphan"] += 1
    funnel["oa_absorbed"] = sum(oa_votes.values())
    funnel["oa_dedup"] = oa_dedup

    # ---- Overture（读全州一次性分桶；旧实现是每县一次 parquet 扫描，AR 上慢 20 分钟）
    ovt_rows = read_ovt_bucket(cache_dir, fips)
    funnel["ovt_input"] = len(ovt_rows)
    ovt_bad = Counter()
    ovt_votes = Counter()
    ovt_meta = {}
    ovt_seen = set()
    for r in ovt_rows:
        if not r["num"] or not r["skey"]:
            ovt_bad["missing_number_or_street"] += 1
            continue
        k = addr_key(r["num"], r["skey"], r["ukey"])
        if k in ovt_seen:
            ovt_bad["dedup"] += 1
            continue
        ovt_seen.add(k)
        if k in nad_keys:
            ovt_votes[k] += 1
            ovt_meta.setdefault(k, r)
        else:
            ovt_bad["unendorsed_orphan"] += 1
    funnel["ovt_absorbed"] = sum(ovt_votes.values())
    funnel["ovt_upstream"] = dict(Counter(r["upstream"] for r in ovt_rows))

    # ---- TIGER
    segs = read_addrfeat(raw_dir / county["addrfeat"])
    seg_index = build_seg_index(segs)
    funnel["tiger_segments"] = len(segs)
    log(f"NAD {funnel['nad_input']} → keys {len(nad_keys)}（dedup {dedup_nad}）｜"
        f"OA {funnel['oa_input']} → 票 {funnel['oa_absorbed']}｜"
        f"OVT {funnel['ovt_input']} → 票 {funnel['ovt_absorbed']}｜TIGER 号段 {len(segs)}")

    # ---- 组装输出
    out_rows = []
    tiers = Counter()
    tiger_dist = Counter()
    zip_div = 0
    fills = Counter()
    admin = scope["admin"]
    for k, info in nad_keys.items():
        rep = info["rep"]
        raw = rep["raw"]
        verify, dist, tlid = tiger_check(seg_index, rep["num"], rep["skey"], rep["lon"], rep["lat"])
        tier = ("S" if verify == "range" and (oa_votes[k] or ovt_votes[k]) else
                "A" if (oa_votes[k] or ovt_votes[k] or verify in ("range", "street")) else "B")
        tiers[tier] += 1
        tiger_dist[verify] += 1

        # 邮编：原生优先，缺失才 ZCTA 回填
        zip5 = rep["zip5"] or (ovt_meta.get(k, {}).get("zip5") if k in ovt_meta else None) \
            or (oa_meta.get(k, {}).get("postcode") if k in oa_meta else None)
        zip_src = "nad_native" if rep["zip5"] else ("ovt_native" if zip5 else None)
        zcta_hit = None
        if zcta_idx and rep["lon"] is not None:
            zcta_hit = zcta_idx.find(rep["lon"], rep["lat"])
        if not zip5 and zcta_hit:
            zip5, zip_src = zcta_hit, "zcta_derived"
        if zip5 and zcta_hit and zip5 != zcta_hit:
            zip_div += 1

        # 城市：NAD Post_City > OA CITY > null（统一 Title Case，否则 BONESTEEL / Sioux Falls 混眺）
        postal_city = title_case(rep["city"])
        pc_src = "nad_post_city" if postal_city else None
        if not postal_city and k in oa_meta and oa_meta[k].get("city"):
            postal_city, pc_src = title_case(oa_meta[k]["city"]), "oa_city"

        muni = rep["muni"]
        mc_src = "nad_inc_muni" if muni else None
        if muni and muni.strip().upper() in {"UNINCORPORATED"}:
            muni, mc_src = None, None
        if not muni and place_idx:
            pid = place_idx.find(rep["lon"], rep["lat"])
            if pid:
                muni = place_idx.items[pid].get("name")
                mc_src = "tiger_place"
        muni = title_case(muni)

        street_full = rep["street_full"]
        addr_type = ("Residential (Multi-Unit)" if rep["unit"] else
                     "Commercial" if COMMERCIAL_HINT.search(street_full or "") else "Residential")
        if str(raw.get("Addr_Type") or "").strip().upper() in {"COMMERCIAL"}:
            addr_type = "Commercial"

        street_line = f"{rep['num']}{'' if not raw.get('AddNum_Suf') else raw.get('AddNum_Suf')} {street_full}"
        if rep["unit"]:
            street_line += f" {rep['unit']}"
        tail = ", ".join(x for x in [postal_city, f"{scope['state']} {zip5 or ''}".strip()] if x)
        full = f"{street_line}, {tail}" if tail else street_line

        detail = []
        detail.append("NAD")
        if oa_votes[k]:
            detail.append("OA")
        if verify == "range":
            detail.append("TIGER[range]")
        elif verify == "street":
            detail.append("TIGER[street]")
        if ovt_votes[k]:
            detail.append("Overture")
        aid = hashlib.sha1(f"{scope['state']}|{fips}|{k}".encode()).hexdigest()[:20]

        row = {
            "house_number": rep["num"], "house_number_suffix": clean_str(raw.get("AddNum_Suf")),
            "street_pre_dir": rep["pre_dir"], "street_name": clean_str(raw.get("St_Name")),
            "street_post_type": rep["post_type"], "street_post_dir": rep["post_dir"],
            "street_full": street_full, "unit": rep["unit"], "building_floor": None,
            "postal_city": postal_city, "municipal_city": muni,
            "county_name": rep["county"] or county["name"], "county_fips": fips,
            "state_abbr": scope["state"], "state_name": scope["state_name"],
            "state_fips": scope["state_fips"],
            "zip5": zip5, "plus4": None, "zip9": zip5,
            "latitude": round(rep["lat"], 7), "longitude": round(rep["lon"], 7),
            "addr_type": addr_type, "area_code": None, "timezone": scope.get("timezone"),
            "timezone_precision": scope.get("timezone_precision"),
            "full_formatted_address": full,
            "source_confidence": {"S": "S-Tier", "A": "A-Tier", "B": "B-Tier"}[tier],
            "country_code": admin["country_code"],
            "country_code_alpha3": admin["country_code_alpha3"],
            "country_numeric": admin["country_numeric"],
            "admin1_code": admin["admin1_code"],
            "admin1_name": admin["admin1_name"],
            "admin1_type": admin["admin1_type"],
            # --- provenance ---
            "addr_id": aid, "zip_source": zip_src,
            "postal_city_source": pc_src, "municipal_city_source": mc_src,
            "source_confidence_detail": {"S": "S-Tier", "A": "A-Tier", "B": "B-Tier"}[tier]
                                       + ": " + "+".join(detail),
            "src_nad_uuid": raw.get("UUID"), "src_nad_objectid": raw.get("OBJECTID"),
            "src_oa_hash": oa_meta.get(k, {}).get("hash") if k in oa_meta else None,
            "src_overture_id": ovt_meta.get(k, {}).get("id") if k in ovt_meta else None,
            "src_tiger_tlid": tlid, "tiger_verify": verify, "tiger_distance_m": dist,
            "nad_addr_type_raw": raw.get("Addr_Type"),
            "nad_placement_raw": raw.get("Placement"),
            "nad_addclass_raw": raw.get("AddrClass"),
            "oa_file": oa_meta.get(k, {}).get("file") if k in oa_meta else None,
            "overture_upstream": ovt_meta.get(k, {}).get("upstream") if k in ovt_meta else None,
            "dup_group": info["members"] if info["members"] > 1 else 1,
            "dup_members": info["members"] - 1,
        }
        for f in ("zip5", "postal_city", "municipal_city", "unit", "tiger_verify"):
            if row.get(f) is not None:
                fills[f] += 1
        out_rows.append(row)

    # ---- 分源独立记账 + 守恒校验
    funnel["nad_malformed"] = sum(v for k, v in nad_bad.items() if k != "out_of_bounds")
    funnel["nad_out_of_bounds"] = nad_bad["out_of_bounds"]
    funnel["nad_dedup"] = dedup_nad
    funnel["oa_malformed"] = sum(v for k, v in oa_bad.items() if k != "unendorsed_orphan")
    funnel["oa_unendorsed_orphan"] = oa_bad["unendorsed_orphan"]
    funnel["ovt_malformed"] = sum(v for k, v in ovt_bad.items() if k not in ("out_of_bounds", "dedup", "unendorsed_orphan"))
    funnel["ovt_out_of_bounds"] = ovt_bad["out_of_bounds"]
    funnel["ovt_dedup"] = ovt_bad["dedup"]
    funnel["ovt_unendorsed_orphan"] = ovt_bad["unendorsed_orphan"]
    funnel["output_rows"] = len(out_rows)

    checks = {
        "nad": funnel["nad_input"] == (funnel["output_rows"] + funnel["nad_malformed"]
                                       + funnel["nad_out_of_bounds"] + funnel["nad_dedup"]),
        "oa": funnel["oa_input"] == (funnel["oa_absorbed"] + funnel["oa_unendorsed_orphan"]
                                     + funnel["oa_malformed"] + funnel["oa_dedup"]),
        "ovt": funnel["ovt_input"] == (funnel["ovt_absorbed"] + funnel["ovt_unendorsed_orphan"]
                                       + funnel["ovt_out_of_bounds"] + funnel["ovt_malformed"]
                                       + funnel["ovt_dedup"]),
    }
    funnel["conservation"] = checks
    funnel["conservation_ok"] = all(checks.values())
    funnel["tiers"] = dict(tiers)
    funnel["tiger_dist"] = dict(tiger_dist)
    funnel["zip_zcta_divergence_count"] = zip_div
    funnel["elapsed_s"] = round(time.time() - t0, 1)

    # ---- 落盘 ndjson.gz
    fname = f"ADDR-US-{scope['state']}-{fips}-{county['key']}.ndjson.gz"
    out_path = out_dir / fname
    out_dir.mkdir(parents=True, exist_ok=True)
    # mtime=0 → 同输入同输出同 sha256（gzip 头默认写当前时间，会破坏可复现性）
    with open(out_path, "wb") as raw, \
            gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, mtime=0) as gz, \
            io.TextIOWrapper(gz, encoding="utf-8") as fh:
        for row in out_rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    funnel["output_file"] = fname
    funnel["output_bytes"] = out_path.stat().st_size
    funnel["output_sha256"] = hashlib.sha256(out_path.read_bytes()).hexdigest()
    funnel["fills"] = {k: round(v / max(1, len(out_rows)) * 100, 2) for k, v in fills.items()}
    log(f"输出 {fname}：{len(out_rows)} 行 / {funnel['output_bytes']} B / "
        f"守恒={funnel['conservation_ok']} / 档位={dict(tiers)} / {funnel['elapsed_s']}s")
    return funnel


# ---------------------------------------------------------------- 多进程（按县并行）
_W = {}


def _worker_run(county: dict) -> dict:
    """子进程入口：globals 由 fork 继承（Linux），避免把 ZCTA/places 索引 pickle 过去。"""
    return process_county(_W["scope"], county, _W["raw"], _W["cache"], _W["oa"],
                          _W["zcta"], _W["places"], county["rings"], _W["out"])


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="二仓 Gold 层引擎 v2")
    ap.add_argument("--scope", required=True)
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--counties", help="逗号分隔 fips，覆盖 scope")
    ap.add_argument("--workers", type=int, default=0,
                    help="按县并行的进程数；0=自动（min(4, CPU)，单核按 1 跑）")
    args = ap.parse_args(argv)

    scope = json.loads(Path(args.scope).read_text(encoding="utf-8"))
    raw_dir = Path(args.raw_dir)
    cache = Path(args.cache)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    counties = scope["counties"]
    if args.counties:
        want = {c.strip() for c in args.counties.split(",")}
        counties = [c for c in counties if c["fips"] in want]
    log(f"{scope['state']} / {len(counties)} 县 / admin1={scope['admin']['admin1_code']}")
    t_start = time.time()

    # 县界索引（用于 OA 一次性分桶）
    county_shapes = []
    for c in counties:
        rings = []
        for f in load_esri_rings(raw_dir / c["county_geo"]):
            rings.extend(f["rings"])
        c["rings"] = rings
        county_shapes.append({"fips": c["fips"], "rings": rings})
    # 0-NAD 县也进索引：只参与 OA 计数，不产分片（否则它们的 OA 行会污染 out_of_bounds）
    zero = scope.get("zero_nad_counties") or []
    for c in zero:
        if not c.get("county_geo"):
            continue
        rings = []
        for f in load_esri_rings(raw_dir / c["county_geo"]):
            rings.extend(f["rings"])
        if rings:
            c["rings"] = rings
            county_shapes.append({"fips": c["fips"], "rings": rings})
    county_index = SpatialIndex(county_shapes, "fips")
    log(f"县界索引就绪：{len(county_shapes)} 县（含 {len(zero)} 个 0-NAD 县）/ {round(time.time()-t_start,1)}s")

    # OA 全州一次扫描 → 分县缓存
    oa_buckets = {}
    zero_counts = Counter()
    write_fips = {c["fips"] for c in counties}
    for src_name, fname in sorted(scope["assets"]["oa"].items()):
        if not (raw_dir / fname).exists():
            log(f"⚠️ OA 包缺失，跳过：{fname}")
            continue
        s = bucket_oa_statewide(raw_dir / fname, county_index, cache,
                                [c["fips"] for c in counties], write_fips)
        for f, n in s.items():
            oa_buckets[f] = oa_buckets.get(f, 0) + n
            if f not in write_fips:
                zero_counts[f] += n
    for c in zero:
        c["oa_rows"] = zero_counts.get(c["fips"], 0)
    log(f"OA 分桶就绪：有 NAD 县 {sum(oa_buckets.get(f, 0) for f in write_fips)} 行 / "
        f"0-NAD 县 {sum((c.get('oa_rows') or 0) for c in zero)} 行 / {round(time.time()-t_start,1)}s")

    # Overture：全州一次扫描 + 分县分桶（关键性能改造）
    sb = scope.get("bbox") or rings_bbox([p for c in county_shapes for p in [x for r in c["rings"] for x in r]])
    _ovt_names = scope["assets"].get("overture_files") or (
        [scope["assets"]["overture"]] if scope["assets"].get("overture") else [])
    _ovt_paths = [raw_dir / n for n in _ovt_names]
    log(f"Overture 输入：{len(_ovt_paths)} 个文件（模式 "
        f"{scope['assets'].get('overture_mode', 'state_file')}）")
    ovt_counts, ovt_outside = bucket_overture(_ovt_paths, county_index, cache,
                                              write_fips, tuple(sb))
    log(f"Overture 分桶就绪：{round(time.time()-t_start,1)}s")

    zcta = load_zcta(cache / f"zcta-US-{scope['state']}.ndjson.gz")
    zcta_idx = SpatialIndex(zcta, "zcta5") if zcta else None
    places = load_places(raw_dir / scope["assets"]["places"]) if scope["assets"].get("places") else []
    place_idx = SpatialIndex(places, "place") if places else None
    log(f"ZCTA 面 {len(zcta)} / places {len(places)} / {round(time.time()-t_start,1)}s")

    workers = args.workers or min(4, __import__("os").cpu_count() or 1)
    workers = max(1, min(workers, len(counties)))
    if workers > 1:
        import multiprocessing as mp
        _W.update(scope=scope, raw=raw_dir, cache=cache, oa=oa_buckets,
                  zcta=zcta_idx, places=place_idx, out=out_dir)
        log(f"按县并行：{workers} 个进程 / {len(counties)} 县（fork 继承空间索引，不重复加载）")
        ctx = mp.get_context("fork")
        with ctx.Pool(processes=workers) as pool:
            results = pool.map(_worker_run, counties)
    else:
        results = []
        for c in counties:
            results.append(process_county(scope, c, raw_dir, cache, oa_buckets,
                                          zcta_idx, place_idx, c["rings"], out_dir))

    ok = all(r["conservation_ok"] for r in results)
    manifest = {
        "generated_at": now_utc(),
        "schema_version": "2.0",
        "state": scope["state"],
        "admin": scope["admin"],
        "admin_registry": scope.get("admin_registry"),
        "source_manifest": scope.get("source_manifest"),
        "counties": results,
        "totals": {
            "counties": len(results),
            "output_rows": sum(r["output_rows"] for r in results),
            "nad_input": sum(r["nad_input"] for r in results),
            "oa_input": sum(r["oa_input"] for r in results),
            "ovt_input": sum(r["ovt_input"] for r in results),
            "oa_in_zero_nad_counties": sum((c.get("oa_rows") or 0) for c in zero),
            "ovt_out_of_state": ovt_outside,
            "ovt_input_note": "v2.1 起 Overture 为「全州一次扫描 + 按县多边形分桶」，ovt_input = 落在该县境内行数；"
                              "州 bbox 内但不属任何县的行单列在 ovt_out_of_state",
            "conservation_ok": ok,
        },
    }
    manifest["release_rev"] = __import__("os").environ.get("GITHUB_RUN_ID", "local")
    manifest["timezone"] = scope.get("timezone")
    manifest["timezone_precision"] = scope.get("timezone_precision")
    manifest["coverage"] = {
        "total_counties": (scope.get("coverage") or {}).get("total_counties"),
        "nad_backed_counties": len(results),
        "zero_nad_counties": len(zero),
        "note": "coverage 相对上游（一仓 NAD）声明，不是地理真值",
    }
    manifest["zero_nad_counties"] = [{k: v for k, v in c.items() if k != "rings"} for c in zero]
    manifest["upstream_gaps"] = upstream_gaps(scope)
    manifest["zcta_available"] = bool(zcta)
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "STATUS.json").write_text(json.dumps(
        {"generated_at": now_utc(), "state": scope["state"], "ok": ok,
         "counties_done": [r["county"] for r in results],
         "conservation": {r["county"]: r["conservation"] for r in results}},
        ensure_ascii=False, indent=1), encoding="utf-8")

    if not ok:
        log("❌ 漏斗守恒失败 —— 按门禁不得发版")
        return 1
    log(f"✅ 全部分源守恒：{manifest['totals']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
