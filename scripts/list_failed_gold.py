#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二仓 · 列出「还没跑成 / 跑失败」的州（G12：失败州单跑入口）

判据（按 Release 实物，不信任何中间状态）：
  · gold-US-<ST>-v1 不存在          → never（从未跑）
  · 存在但没有 MANIFEST.json        → incomplete（跑到一半 / 守恒没过，没发版）
  · 有 MANIFEST 且 STATUS.ok 为 false → failed（发了版但自检说守恒不过）

用法：
  python3 scripts/list_failed_gold.py --states AZ,NJ,TX     # 指定州
  python3 scripts/list_failed_gold.py --all                 # 扫一遍 roster 里的州
  python3 scripts/list_failed_gold.py --all --format states # 直接输出逗号串（喂给 --states）
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

REPO = "ip9988001/world-map-data-test"
ROSTER = Path(__file__).resolve().parents[1] / "rules" / "US" / "state_roster.yaml"


def gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args, "-R", REPO], capture_output=True, text=True)


def check(state: str) -> str:
    tag = f"gold-US-{state}-v1"
    r = gh("release", "view", tag, "--json", "assets", "--jq", ".assets[].name")
    if r.returncode != 0:
        return "never"
    names = (r.stdout or "").split()
    if "MANIFEST.json" not in names:
        return "incomplete"
    d = tempfile.mkdtemp(prefix="goldchk-")
    gh("release", "download", tag, "-p", "STATUS.json", "-D", d, "--clobber")
    try:
        ok = json.loads((Path(d) / "STATUS.json").read_text(encoding="utf-8")).get("ok")
    except Exception:  # noqa: BLE001
        ok = None
    if ok is False:
        return "failed"
    return "ok"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="列出二仓未完成/失败的州")
    ap.add_argument("--states", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--format", choices=["table", "states"], default="table")
    args = ap.parse_args(argv)

    if args.states:
        states = [s.strip().upper() for s in args.states.split(",") if s.strip()]
    elif args.all:
        import yaml
        states = sorted(yaml.safe_load(ROSTER.read_text(encoding="utf-8"))["states"])
    else:
        ap.error("需要 --states 或 --all")

    bad = []
    for st in states:
        verdict = check(st)
        if args.format == "table":
            print(f"{st}  {verdict}")
        if verdict != "ok":
            bad.append(st)
    if args.format == "states":
        print(",".join(bad))
    else:
        print(f"\n未完成/失败：{len(bad)} / {len(states)} → {','.join(bad) or '（无）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
