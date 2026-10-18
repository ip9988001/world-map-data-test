#!/usr/bin/env python3
"""二仓 · Gold 层作用域生成器（scope builder）
================================================================================
输入（全部随仓库走 / 由 workflow 下载好的本地文件，本脚本不联网）：
  rules/US/state_roster.yaml                    州 bbox / state_fips / 县清单
  rules/geo/global_admin_registry.json          ISO 3166-1 / 3166-2 常量源
  data/raw/US-<ST>/MANIFEST.json                一仓封存账本（资产名 + 分片清单）

输出：
  data/gold/US-<ST>/scope.json                  引擎可直接消费的任务上下文

设计纪律
  * 资产名一律以 MANIFEST 为准，不靠猜文件名
  * ISO 常量查不到 → 直接 exit 2（发布门禁，复用一仓 roster 拼写锁思路）
  * 不手写 51 份 scope：任何州/县组合都由本脚本生成
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 州 → IANA 时区（多时区州标 multi_tz，精细化留待后续按县/经度）
STATE_TZ = {
    "CT": "America/New_York", "DE": "America/New_York", "DC": "America/New_York",
    "FL": "America/New_York", "GA": "America/New_York", "IN": "America/Indiana/Indianapolis",
    "KY": "America/New_York", "ME": "America/New_York", "MD": "America/New_York",
    "MA": "America/New_York", "MI": "America/Detroit", "NH": "America/New_York",
    "NJ": "America/New_York", "NY": "America/New_York", "NC": "America/New_York",
    "OH": "America/New_York", "PA": "America/New_York", "RI": "America/New_York",
    "SC": "America/New_York", "VT": "America/New_York", "VA": "America/New_York",
    "WV": "America/New_York",
    "AL": "America/Chicago", "AR": "America/Chicago", "IL": "America/Chicago",
    "IA": "America/Chicago", "KS": "America/Chicago", "LA": "America/Chicago",
    "MN": "America/Chicago", "MS": "America/Chicago", "MO": "America/Chicago",
    "NE": "America/Chicago", "ND": "America/Chicago", "OK": "America/Chicago",
    "SD": "America/Chicago", "TN": "America/Chicago", "TX": "America/Chicago",
    "WI": "America/Chicago",
    "CO": "America/Denver", "MT": "America/Denver", "NM": "America/Denver",
    "UT": "America/Denver", "WY": "America/Denver",
    "AZ": "America/Phoenix",
    "ID": "America/Boise",
    "NV": "America/Los_Angeles", "CA": "America/Los_Angeles",
    "OR": "America/Los_Angeles", "WA": "America/Los_Angeles",
    "AK": "America/Anchorage", "HI": "Pacific/Honolulu",
}
MULTI_TZ = {"IN", "KY", "TN", "FL", "MI", "ND", "SD", "NE", "KS", "TX", "ID", "OR", "AK", "AZ"}


def log(msg: str) -> None:
    print(f"[scope] {msg}", flush=True)


def load_yaml(path: Path) -> dict:
    import yaml  # PyYAML 随 runner 自带；本地亦有
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def admin_constants(registry: dict, state: str) -> dict:
    """ISO 3166-1 + 3166-2 常量；查不到即抛错（发布门禁）。"""
    us = next((c for c in registry["countries"] if c.get("country_code") == "US"), None)
    if not us:
        raise KeyError("registry 中没有 US（ISO 3166-1）")
    code = f"US-{state}"
    div = next((d for d in registry["admin_divisions"]
                if d.get("iso_3166_2") == code), None)
    if not div:
        raise KeyError(f"registry 中查不到 {code}（ISO 3166-2）→ 该州禁止发布")
    return {
        "country_code": us["country_code"],
        "country_code_alpha3": us.get("alpha_3"),
        "country_numeric": us.get("numeric"),
        "country_name": us.get("country_name"),
        "continent_code": us.get("continent_code"),
        "country_phone_prefix": us.get("phone_prefix"),
        "postal_code_regex": us.get("postal_code_regex"),
        "admin1_code": div["iso_3166_2"],
        "admin1_name": div["admin_division_name"],
        "admin1_type": div.get("admin_division_type"),
        "admin1_in_iso3166_2": div.get("in_iso3166_2", True),
        "admin1_source": div.get("source"),
    }


def index_assets(manifest: dict) -> dict:
    """把 MANIFEST.assets 按角色归类（只用 basename 前缀，不猜子目录）。"""
    a = {"nad": {}, "tiger_addrfeat": {}, "tiger_county": {}, "oa": {},
         "overture": None, "state_geo": None, "places": None, "zcta": None}
    for item in manifest.get("assets") or []:
        name = item["path"].rsplit("/", 1)[-1]
        if name.startswith("NAD-") and name.endswith(".ndjson.gz"):
            parts = name[:-len(".ndjson.gz")].split("-")   # NAD-US-SD-46053-gregory
            if len(parts) >= 5:
                a["nad"][parts[3]] = name
        elif name.startswith("NAD-") and name.startswith("NAD-US-") and "OUTOFSTATE" in name:
            a.setdefault("outofstate", name)
        elif name.startswith("TIGER-") and name.endswith("-addrfeat.zip"):
            parts = name[:-len("-addrfeat.zip")].split("-")
            a["tiger_addrfeat"][parts[3]] = name
        elif name.startswith("TIGER-") and "-county-" in name and name.endswith(".geojson"):
            parts = name[:-len(".geojson")].split("-")
            a["tiger_county"][parts[-1]] = name
        elif name.startswith("TIGER-") and name.endswith("-state.geojson"):
            a["state_geo"] = name
        elif name.startswith("TIGER-") and name.endswith("-places.zip"):
            a["places"] = name
        elif name.startswith("TIGER-") and name.endswith("-zcta.geojson"):
            a["zcta"] = name
        elif name.startswith("OA-") and name.endswith(".zip"):
            src = name[:-len(".zip")].split(f"OA-")[-1]           # US-SD-statewide
            parts = src.split("-")
            a["oa"]["-".join(parts[2:])] = name
        elif name.startswith("OVERTURE-") and name.endswith(".parquet"):
            a["overture"] = name
    return a


def build_scope(state: str, raw_dir: Path, roster_path: Path, reg_path: Path,
                only_counties: list[str] | None = None) -> dict:
    roster = load_yaml(roster_path)["states"]
    registry = json.loads(reg_path.read_text(encoding="utf-8"))
    if state not in roster:
        raise KeyError(f"roster 里没有 {state}")
    r = roster[state]
    manifest = json.loads((raw_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    assets = index_assets(manifest)
    # 一仓实证：NAD 县片不一定出现在 assets[]，但一定在 shards[].file —— 以 shards 为准
    for s in manifest.get("shards") or []:
        if s.get("kind") == "county" and s.get("file"):
            nm = s["file"].rsplit("/", 1)[-1]
            if nm.endswith(".ndjson.gz"):
                assets["nad"].setdefault(s["county_fips"], nm)

    if not assets.get("overture"):
        raise KeyError("MANIFEST 里没有 OVERTURE-US-<ST>.parquet")
    if not assets["nad"]:
        raise KeyError("MANIFEST 里没有任何 NAD 县片")

    # 县清单：以 MANIFEST.shards 为准（有行数的县才做），roster 只提供名字
    shards = [s for s in (manifest.get("shards") or [])
              if s.get("kind") == "county" and (s.get("rows") or 0) > 0]
    counties = []
    for s in sorted(shards, key=lambda x: x["county_fips"]):
        fips = s["county_fips"]
        if only_counties and fips not in only_counties:
            continue
        counties.append({
            "fips": fips,
            "key": s.get("county_key"),
            "name": s.get("county_name"),
            "nad_rows": s.get("rows"),
            "nad_file": assets["nad"].get(fips),
            "addrfeat": assets["tiger_addrfeat"].get(fips),
            "county_geo": assets["tiger_county"].get(fips),
        })

    missing = [c["fips"] for c in counties
               if not (c["nad_file"] and c["addrfeat"] and c["county_geo"])]
    if missing:
        log(f"⚠️ 这些县的 NAD/TIGER 资产不齐，将跳过：{missing}")
        counties = [c for c in counties if c["fips"] not in missing]
    if not counties:
        raise KeyError("没有任何可加工的完整县")

    admin = admin_constants(registry, state)
    scope = {
        "state": state,
        "state_name": r.get("name"),
        "state_fips": r.get("state_fips"),
        "bbox": r.get("bbox"),
        "timezone": STATE_TZ.get(state),
        "multi_tz": state in MULTI_TZ,
        "zcta_range": r.get("zcta_range"),
        "admin": admin,
        "admin_registry": {
            "schema": registry.get("schema"),
            "generated_at": registry.get("generated_at"),
            "counts": registry.get("counts"),
        },
        "raw_dir": str(raw_dir),
        "assets": {
            "overture": assets["overture"],
            "oa": assets["oa"],
            "state_geo": assets["state_geo"],
            "places": assets["places"],
            "zcta": assets["zcta"],
            "outofstate": assets.get("outofstate"),
        },
        "counties": counties,
        "source_manifest": {
            "generated_at": manifest.get("generated_at"),
            "runner": manifest.get("runner"),
            "quality": manifest.get("quality"),
            "reference_check": manifest.get("reference_check"),
        },
    }
    return scope


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成二仓 Gold 层 scope")
    ap.add_argument("--state", required=True)
    ap.add_argument("--raw-dir", required=True, help="一仓 raw 资产目录（含 MANIFEST.json）")
    ap.add_argument("--roster", default="rules/US/state_roster.yaml")
    ap.add_argument("--registry", default="rules/geo/global_admin_registry.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--counties", help="逗号分隔 fips；留空=全州所有有数据的县")
    args = ap.parse_args(argv)

    only = [c.strip() for c in args.counties.split(",")] if args.counties else None
    try:
        scope = build_scope(args.state, Path(args.raw_dir), Path(args.roster),
                            Path(args.registry), only)
    except KeyError as exc:
        log(f"❌ 阻断：{exc}")
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(scope, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"写出 {out}：{scope['state']} / {len(scope['counties'])} 县 / "
        f"admin1={scope['admin']['admin1_code']} / tz={scope['timezone']}")
    for c in scope["counties"]:
        log(f"  县 {c['fips']} {c['name']:<28} NAD={c['nad_rows']:>7}  addrfeat={c['addrfeat']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
