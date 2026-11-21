#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 / 复现「Census 基准县表」—— 覆盖率的唯一法定分母（config/baseline/counties_census.json）。

为什么必须有这张表：
  `counties_done` / `counties_declared` 都是「我们干了多少」的自述数，它们可以因为上游缺县、
  资产缺失、跳过县而变小 —— 拿它当分母，覆盖率永远算成 100%（自证）。法定分母只能是 Census
  的县清单，与我们的流水线无关。

两个输入（都不带自己的口径，逐字取官方值）：
  1. 县清单 = `rules/US/state_roster.yaml` 的 counties[]（TIGER2024 县界，GEOID 5 位）
  2. 住房单元数 = Census ACS 2020-2024 5-year 表 B25001_001（Total housing units）
     · Census 官方 API（api.census.gov）自 2025 起强制 API key，本环境无 key；
       故走 Census Reporter 的公开镜像（同一 ACS 表，无 key），并记下原始响应 sha256。
     · 只作 `counties_nad_substantive` 阈值在一县融合行数为 0 时的兜底分母，不是发布口径。

产物自描述：vintage / source_url / downloaded_at / sha256 / row_count / county_count 全写进文件头。
`sha256` 只覆盖 counties 数组的规范化序列化（sort_keys + 紧凑分隔符），头部元数据不参与，
所以任何人可以离线复算这一位，不必依赖本脚本。

跑法：
  python3 scripts/build_counties_baseline.py                       # 联网取 ACS（默认）
  python3 scripts/build_counties_baseline.py --acs-json cr.json     # 用已下载的响应离线重建
  python3 scripts/build_counties_baseline.py --check                # 只校验现有产物（不写文件）
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "config" / "baseline" / "counties_census.json"
ROSTER = REPO / "rules" / "US" / "state_roster.yaml"

# ACS 2024 5-year, B25001 = Housing Units, B25001001 = Total
ACS_URL = ("https://api.censusreporter.org/1.0/data/show/acs2024_5yr"
           "?table_ids=B25001&geo_ids=050%7C01000US")
TIGER_URL = "https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/"
VINTAGE = "ACS 2020-2024 5-year（Census 表 B25001_001 Total housing units）+ TIGER2024 县清单"
# 领地（PR/VI/GU/AS/MP）不入分母：本项目轮次作用域是 50 州 + DC
TERRITORY_PREFIXES = {"60": "AS", "66": "GU", "69": "MP", "72": "PR", "78": "VI"}


def body_sha256(counties: list[dict]) -> str:
    """表体指纹：只覆盖 counties 数组，与头部元数据无关，可离线复算。"""
    blob = json.dumps(counties, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_roster() -> dict[str, dict]:
    try:
        import yaml                                  # noqa: PLC0415
    except Exception as exc:                          # noqa: BLE001
        raise SystemExit("需要 pyyaml 读 state_roster.yaml：%s" % exc)
    d = yaml.safe_load(ROSTER.read_text(encoding="utf-8"))
    out = {}
    for abbr, st in (d.get("states") or {}).items():
        for c in st.get("counties") or []:
            out[str(c["fips"])] = {"state_abbr": abbr, "county_name": c["name"],
                                   "state_fips": str(st["state_fips"])}
    return out


def load_acs(path: Path | None) -> tuple[dict, bytes]:
    if path and path.exists():
        raw = path.read_bytes()
    else:
        req = urllib.request.Request(ACS_URL, headers={"User-Agent": "world-map-data-test/baseline"})
        with urllib.request.urlopen(req, timeout=120) as rsp:      # noqa: S310
            raw = rsp.read()
    d = json.loads(raw.decode("utf-8"))
    rel = d.get("release") or {}
    rows, moe = {}, {}
    for geoid, v in (d.get("data") or {}).items():
        fips = geoid[-5:]
        cell = (v.get("B25001") or {}).get("estimate") or {}
        err = (v.get("B25001") or {}).get("error") or {}
        hu = cell.get("B25001001")
        rows[fips] = {"housing_units": int(hu) if hu is not None else None,
                      "housing_units_moe": int(err["B25001001"]) if err.get("B25001001") is not None else None,
                      "census_name": ((d.get("geography") or {}).get(geoid) or {}).get("name")}
    return {"release": rel, "rows": rows}, raw


def build(acs: dict, raw: bytes, downloaded_at: str) -> dict:
    roster = load_roster()
    acs_rows = acs["rows"]
    counties, missing = [], []
    for fips in sorted(roster):
        r = roster[fips]
        a = acs_rows.get(fips) or {}
        if a.get("housing_units") is None:
            missing.append(fips)
        counties.append({
            "state_fips": r["state_fips"],
            "county_fips": fips,
            "county_name": r["county_name"],
            "state_abbr": r["state_abbr"],
            "housing_units": a.get("housing_units"),
            "housing_units_moe": a.get("housing_units_moe"),
            "census_name": a.get("census_name"),
        })
    excluded = {}
    for fips in sorted(set(acs_rows) - set(roster)):
        pref = fips[:2]
        if pref in TERRITORY_PREFIXES:
            excluded.setdefault(TERRITORY_PREFIXES[pref], 0)
            excluded[TERRITORY_PREFIXES[pref]] += 1
        else:
            excluded.setdefault("unknown", 0)
            excluded["unknown"] += 1
    rel = acs.get("release") or {}
    return {
        "schema": "counties-baseline/v1",
        "purpose": "覆盖率唯一法定分母：county_count = 分母。禁止用 counties_done / counties_declared 当分母（那两个是自述数，永远算成 100%）",
        "vintage": VINTAGE,
        "county_list_vintage": "TIGER2024 县界（GEOID 5 位；CT 为 2022 起的 9 个 planning region：09110-09190）",
        "housing_units_vintage": "%s（%s）" % (rel.get("name") or "ACS 2024 5-year", rel.get("years") or "2020-2024"),
        "source_url": ACS_URL,
        "county_list_source_url": TIGER_URL,
        "downloaded_at": downloaded_at,
        "generated_by": "scripts/build_counties_baseline.py",
        "sha256": body_sha256(counties),
        "sha256_scope": "只覆盖 counties 数组的规范化序列化（json.dumps sort_keys=True, separators=(',',':')，UTF-8）；头部元数据不参与，可离线复算",
        "row_count": len(acs_rows),
        "row_count_note": "上游 ACS 响应里的总行数（含领地），不等于分母",
        "county_count": len(counties),
        "county_count_note": "表内县行数 = 覆盖率分母（50 州 + DC，3,144 县）",
        "territories_included": False,
        "coverage_scope": "50 州 + DC；领地（PR/VI/GU/AS/MP）不入表、不计入分母",
        "excluded_entities": excluded,
        "missing_housing_units": missing,
        "sources": [
            {"name": "Census Reporter mirror of ACS 2024 5-year B25001", "url": ACS_URL,
             "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
            {"name": "TIGER2024 county list", "url": TIGER_URL,
             "note": "县清单实际取自仓内 rules/US/state_roster.yaml 的 counties[]（由 TIGERweb 生成）",
             "path": "rules/US/state_roster.yaml"},
        ],
        "read_only": "运行期只读：任何脚本不得写回本文件；口径变化只能新增 vintage 文件并改 SCHEMA 引用",
        "counties": counties,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--acs-json", default="", help="已下载的 Census Reporter 响应（离线重建用）")
    ap.add_argument("--check", action="store_true", help="只校验现有产物，不写文件")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    out = Path(a.out)

    if a.check:
        if not out.exists():
            print("❌ 基准表不存在：%s" % out)
            return 1
        doc = json.loads(out.read_text(encoding="utf-8"))
        got = body_sha256(doc["counties"])
        ok = (got == doc.get("sha256")
              and len(doc["counties"]) == doc.get("county_count")
              and len({c["county_fips"] for c in doc["counties"]}) == doc.get("county_count"))
        print("vintage  = %s" % doc.get("vintage"))
        print("row_count= %s   county_count= %s" % (doc.get("row_count"), doc.get("county_count")))
        print("sha256   = %s（复算 %s）" % (doc.get("sha256"), "一致" if got == doc["sha256"] else "不一致 " + got))
        print("✅ 基准表自校验通过" if ok else "❌ 基准表自校验失败")
        return 0 if ok else 1

    acs, raw = load_acs(Path(a.acs_json) if a.acs_json else None)
    doc = build(acs, raw, _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    out.parent.mkdir(parents=True, exist_ok=True)
    # 头部缩进便于人读；counties 一行一县（compact），避免 3 千行 × 8 行缩进把文件撑到 600KB+
    head = {k: v for k, v in doc.items() if k != "counties"}
    head_txt = json.dumps(head, ensure_ascii=False, indent=1)
    rows_txt = ",\n".join("  " + json.dumps(c, ensure_ascii=False, separators=(",", ":"))
                          for c in doc["counties"])
    out.write_text(head_txt[:-2] + ',\n "counties": [\n' + rows_txt + "\n ]\n}\n",
                   encoding="utf-8")
    print("写入 %s" % out)
    print("vintage  = %s" % doc["vintage"])
    print("row_count= %d   county_count= %d   missing_hu=%d" %
          (doc["row_count"], doc["county_count"], len(doc["missing_housing_units"])))
    print("sha256   = %s" % doc["sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
