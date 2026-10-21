#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二仓 · 分卷合并（一仓 raw-US-<ST>-v1-p1 / -p2 … → 一个可加工目录）

为什么需要：德州这种 254 县的州，一仓按 `--volume` 拆成多卷，每卷一个 tag、
一本独立账本。二仓原来只认 `raw-US-<ST>-v1` 单标签 → 只会拉第一卷，当成全州。

本脚本做两件事：
  1. 发现该州全部分卷标签（`raw-US-<ST>-v1` 与 `raw-US-<ST>-v1-p<N>`）
  2. 下每个卷的 MANIFEST.json，合并成**一份**（县清单/资产/shards 取并集，标 volume 信息）；
     可选 `--download` 把所有卷的资产都拉到同一个目录（资产名本身已带县 fips，不会撞名）

合并口径（不造假）：
  · scope.counties 取并集；同一 fips 出现两次 → 直接报错（分卷切重了要人看）
  · assets / shards 按文件名去重取并集
  · reference_check 逐项相加（counties_ok/empty/failed/total、主键数、溢出数）
  · volume 段保留成列表，`volume_total` 记卷数

用法：
  python3 scripts/merge_volume_manifests.py --state TX --raw-dir data/raw/US-TX --download
  python3 scripts/merge_volume_manifests.py --state TX --raw-dir /tmp/tx --tags a,-b --dry-run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO = "ip9988001/World-US-Map-Data"
META_ASSETS = {"STATUS.json", "MANIFEST.json", "RELEASE_NOTES.md"}


def log(msg: str) -> None:
    print(f"[merge] {msg}", flush=True)


def gh(args: list[str], repo: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args, "-R", repo], capture_output=True, text=True)


def discover_tags(state: str, repo: str) -> list[str]:
    """返回该州的全部一仓标签（单卷 + 分卷），按卷号排序。"""
    r = gh(["release", "list", "--limit", "200", "--json", "tagName", "--jq", ".[].tagName"], repo)
    tags = [t.strip() for t in (r.stdout or "").splitlines() if t.strip()]
    base = f"raw-US-{state}-v1"
    vols, single = [], []
    for t in tags:
        if t == base:
            single.append(t)
        elif t.startswith(base + "-p") and t[len(base) + 2:].isdigit():
            vols.append((int(t[len(base) + 2:]), t))
    if vols:
        return [t for _, t in sorted(vols)]          # 有分卷就只认分卷（单卷是历史残留）
    return single


def merge_docs(docs: list[tuple[str, dict]]) -> dict:
    """把多卷账本合成一本。规则见模块 docstring。"""
    if not docs:
        raise SystemExit("没有可合并的 MANIFEST")
    base_tag, base = docs[0]
    out = json.loads(json.dumps(base))               # 深拷贝，别改原对象
    out["generated_at"] = max(str((d.get("generated_at") or "")) for _, d in docs)
    out["merged_from"] = [t for t, _ in docs]

    counties: dict[str, dict] = {}
    assets: dict[str, dict] = {}
    shards: dict[str, dict] = {}
    rc = {}
    vols = []
    for tag, d in docs:
        for c in ((d.get("scope") or {}).get("counties") or []):
            fips = str(c.get("fips") or "")
            if not fips:
                continue
            if fips in counties:
                raise SystemExit(f"❌ 分卷切重：{fips} 同时出现在账本里（{tag} 与其它卷）")
            counties[fips] = c
        for a in (d.get("assets") or []):
            n = str(a.get("path") or "").rsplit("/", 1)[-1]
            if n and n not in META_ASSETS:          # 过程态/发布说明不算数据资产
                assets[n] = a
        for s in (d.get("shards") or []):
            n = str(s.get("file") or "").rsplit("/", 1)[-1]
            if n:
                shards[n] = s
        r = d.get("reference_check") or {}
        for k in ("counties_ok", "counties_empty", "counties_failed", "counties_total",
                  "county_union_ids", "overflow_ids", "state_upstream_count"):
            v = r.get(k)
            if isinstance(v, int):
                rc[k] = rc.get(k, 0) + v
        if r.get("failed_counties"):
            rc.setdefault("failed_counties", []).extend(r["failed_counties"])
        if r.get("county_slicing") and "county_slicing" not in rc:
            rc["county_slicing"] = r["county_slicing"]
        if d.get("volume"):
            vols.append(d["volume"])

    sc = dict(out.get("scope") or {})
    sc["counties"] = [counties[k] for k in sorted(counties)]
    out["scope"] = sc
    out["assets"] = [assets[k] for k in sorted(assets)]
    out["shards"] = [shards[k] for k in sorted(shards)]
    if rc:
        rc["policy"] = ("县级核验为准；本段由分卷账本逐项相加，"
                        "跨卷三数咬合需按合并后 shards 复核")
        out["reference_check"] = rc
    out["volume"] = {"merged": True, "volumes": len(docs),
                     "per_volume": vols, "counties_total": len(counties)}
    # integrity 重算
    import hashlib
    body = {k: v for k, v in out.items() if k != "integrity"}
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    h = hashlib.sha256(blob).hexdigest()
    out["integrity"] = {"sha256": h, "algo": "sha256(manifest-minus-integrity,sort_keys)",
                        "sha256_head": h[:16], "bytes": len(blob)}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="合并一仓分卷账本成一个可加工目录")
    ap.add_argument("--state", required=True)
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--tags", default="", help="手工指定（逗号分隔）；留空=自动发现")
    ap.add_argument("--download", action="store_true", help="同时把各卷资产下到 raw-dir")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    raw = Path(args.raw_dir)
    raw.mkdir(parents=True, exist_ok=True)
    tags = ([t.strip() for t in args.tags.split(",") if t.strip()] if args.tags
            else discover_tags(args.state, args.repo))
    if not tags:
        log(f"❌ 找不到 raw-US-{args.state}-v1（或其分卷）")
        return 2
    log(f"发现 {len(tags)} 个标签：{tags}")
    if len(tags) == 1:
        log("只有单卷 → 不需要合并，直接用原标签即可")
        if not args.dry_run:
            (raw / ".volume_tags").write_text(tags[0] + "\n", encoding="utf-8")
        return 0

    docs = []
    for t in tags:
        r = gh(["release", "download", t, "-p", "MANIFEST.json", "-D", str(raw / "_vol" / t),
                "--clobber"], args.repo)
        p = raw / "_vol" / t / "MANIFEST.json"
        if not p.exists():
            log(f"❌ {t} 没有 MANIFEST.json（未封印）：{(r.stderr or r.stdout)[:160]}")
            return 2
        docs.append((t, json.loads(p.read_text(encoding="utf-8"))))

    merged = merge_docs(docs)
    log(f"合并完成：县 {len(merged['scope']['counties'])} / 资产 {len(merged['assets'])} / "
        f"县片 {len(merged['shards'])} / 卷 {merged['volume']['volumes']}")
    if args.dry_run:
        log("--dry-run：不写盘、不下载资产")
        return 0
    (raw / "MANIFEST.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    (raw / ".volume_tags").write_text("\n".join(tags) + "\n", encoding="utf-8")
    log(f"已写出 {raw / 'MANIFEST.json'}")

    if args.download:
        for t in tags:
            log(f"下载 {t} 的全部资产 → {raw}")
            r = gh(["release", "download", t, "-D", str(raw), "--clobber"], args.repo)
            if r.returncode != 0:
                log(f"⚠️ {t} 下载有告警：{(r.stderr or r.stdout)[:200]}")
        # MANIFEST 已合并，别被最后一卷的原账本覆盖
        (raw / "MANIFEST.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
        n = len(list(raw.glob("*")))
        log(f"资产就位：{n} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
