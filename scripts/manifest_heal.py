#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一仓 MANIFEST 的「账」按 Release 实物补全（只修账，不动一个字节数据）

背景（2026-10-20 实测）：
  一仓是「边抓边传 + 断点续传」，MANIFEST 可能漏记实物：
    · AK：Release 里 23 个 NAD 县片都在，manifest.shards = []
    · NH：1 个县片，shards = []
    · ID：Release 里 43 个 addrfeat 包，manifest.assets 里一个没有
  下游 preflight / scope / coalesce 全读这本账 → 好数据被挡在门外。

做法：以 `gh release view --json assets` 的实物清单为准，把 shards / assets 补进账本。
      rows 能从 STATUS.json 里取到就取（这样 C5 精确对账也能过），取不到就留 null。

用法：
  python3 scripts/manifest_heal.py --manifest <MANIFEST.json> --assets <assets.txt> [--status <STATUS.json>]
退出码：0 正常（含「无需修补」）；2 参数/文件问题
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# NAD-US-AK-02013-aleutians_east.ndjson.gz / NAD-US-AK-OUTOFSTATE.ndjson.gz
# 注意：NAD-<国家>-<州>-<fips>-<县>，国家段不能漏（否则一个都匹配不上）
RE_COUNTY = re.compile(r"^NAD-([A-Z]{2})-([A-Z]{2})-(\d{5})-(.+)\.ndjson\.gz$")
RE_OVERFLOW = re.compile(r"^NAD-([A-Z]{2})-([A-Z]{2})-(OUTOFSTATE|OVERFLOW)\.ndjson\.gz$")


def log(m: str) -> None:
    print(f"[heal] {m}", flush=True)


def read_assets(p: Path) -> list[tuple[str, int | None]]:
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.strip().split("\t")
        if not parts or not parts[0]:
            continue
        name = parts[0].rsplit("/", 1)[-1]
        size = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        out.append((name, size))
    return out


def read_status_rows(p: Path | None) -> dict[str, int]:
    """STATUS.assets[文件名] = {kind, rows, expected_rows, gz_bytes, ...} → 文件名→rows"""
    if not p or not p.exists():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log(f"STATUS 解析失败（忽略）：{exc}")
        return {}
    rows = {}
    for name, rec in (doc.get("assets") or {}).items():
        if isinstance(rec, dict) and rec.get("rows") is not None:
            rows[name] = int(rec["rows"])
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="按 Release 实物补全一仓 MANIFEST 账本")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--assets", required=True)
    ap.add_argument("--status", default="")
    args = ap.parse_args(argv)

    mp, apath = Path(args.manifest), Path(args.assets)
    if not mp.exists():
        log(f"MANIFEST 不存在：{mp}")
        return 2
    if not apath.exists():
        log(f"assets 清单不存在：{apath}")
        return 2

    m = json.loads(mp.read_text(encoding="utf-8"))
    actual = read_assets(apath)
    rows_map = read_status_rows(Path(args.status) if args.status else None)
    names = [n for n, _ in actual]
    changed: list[str] = []

    # ---- shards：county / overflow ----
    shards = [s for s in (m.get("shards") or []) if isinstance(s, dict)]
    have = {str(s.get("file")) for s in shards if s.get("file")}
    rebuilt = []
    for name, size in actual:
        if name in have:
            continue
        mc = RE_COUNTY.match(name)
        mo = RE_OVERFLOW.match(name)
        if mc:
            rebuilt.append({"kind": "county", "file": name, "fips": mc.group(3),
                            "county": mc.group(4), "rows": rows_map.get(name),
                            "bytes": size})
        elif mo:
            rebuilt.append({"kind": "overflow", "file": name,
                            "rows": rows_map.get(name), "bytes": size})
    if rebuilt:
        shards.extend(rebuilt)
        shards.sort(key=lambda s: (0 if s.get("kind") == "county" else 1, str(s.get("file"))))
        m["shards"] = shards
        changed.append(f"shards +{len(rebuilt)}（county {sum(1 for s in rebuilt if s['kind']=='county')}"
                       f" / overflow {sum(1 for s in rebuilt if s['kind']=='overflow')}）")

    # ---- assets：按实物补 {path, bytes}（sha 留空，宁可缺也不编）----
    assets = [a for a in (m.get("assets") or []) if isinstance(a, dict)]
    known = {str(a.get("path", "")).rsplit("/", 1)[-1] for a in assets}
    added = 0
    for name, size in actual:
        if name in known:
            continue
        prefix = "nad" if name.startswith("NAD-") else (
            "tiger" if name.startswith(("TIGER-", "tl_")) else
            "overture" if name.startswith("OVERTURE-") else
            "openaddresses" if name.startswith("OA-") else "")
        assets.append({"path": f"{prefix}/{name}" if prefix else name,
                       "bytes": size, "sha256": None, "sha256_head": None,
                       "healed": True})
        added += 1
    if added:
        m["assets"] = assets
        changed.append(f"assets +{added}")

    if not changed:
        log("账本与实物一致，无需修补")
        return 0

    m.setdefault("heal", {})["at"] = __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ",
                                                               __import__("time").gmtime())
    m["heal"]["reason"] = "按 Release 实物补全账本（数据未改动）"
    m["heal"]["changes"] = changed
    mp.with_suffix(".json.pre-heal").write_text(json.dumps(
        json.loads(mp.read_text(encoding="utf-8")), ensure_ascii=False, indent=1), encoding="utf-8")
    mp.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    log("已修补：" + "；".join(changed))
    log(f"县片 {sum(1 for s in m.get('shards') or [] if s.get('kind') == 'county')} 个，"
        f"有 rows 的 {sum(1 for s in m.get('shards') or [] if s.get('rows'))} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
