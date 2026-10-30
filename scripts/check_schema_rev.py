#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""schema 版本跃迁断言器 —— 把「rev 升级只加不删、grain 不动」变成可执行事实。

为什么需要它：SCHEMA.json 是 LOCKED 的契约文件，靠肉眼 diff 两个 rev 的 32 个主字段
迟早出事（少一个 `null: false`、改一个字 type 都看不出来）。所以每次 rev 跃迁必须跑它：

  python3 scripts/check_schema_rev.py --base main --head HEAD
  python3 scripts/check_schema_rev.py --base 514f12f --head 5841aef --json

判据（任一不满足 → exit 1）：
  1. `grain` 文本逐字节相同
  2. `primary_fields` 名字/类型/可空/来源/注释逐字段相同，且顺序不变（不许增删改）
  3. provenance 字段只许**新增**，既有字段的 name/type/note 不许变（additive-only）
  4. head 的 `rev` = 期望值（默认 3），`rev_log` 依次含 rev 1/2/3 三条；
     rev3 必须写明 `rejected`（含「方案A」）与 why
  5. 段落级改动白名单：只允许 rev_log / geom / 字段数组追加；其余顶层键值不许变
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCHEMA_PATH = "schema/SCHEMA.json"
# 主字段必须逐字节等同的键（note 也算：note 里写着语义，改了就是改语义）
FIELD_KEYS = ("name", "type", "null", "src", "note")


def load(ref: str, path: str = SCHEMA_PATH) -> dict:
    """从 git ref 读 SCHEMA.json（ref 也可写成文件路径，便于离线比对）。"""
    p = Path(ref)
    if p.exists() and path in (None, SCHEMA_PATH) and p.suffix == ".json":
        return json.loads(p.read_text(encoding="utf-8"))
    r = subprocess.run(["git", "-C", str(REPO), "show", f"{ref}:{path}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("取不到 %s:%s —— %s" % (ref, path, (r.stderr or "").strip()[:200]))
    return json.loads(r.stdout)


def field_sig(f: dict, keys=FIELD_KEYS) -> tuple:
    return tuple((k, json.dumps(f.get(k), ensure_ascii=False, sort_keys=True)) for k in keys)


def check(base: dict, head: dict, want_rev: int) -> dict:
    errs, notes = [], []

    # ① grain
    if base.get("grain") != head.get("grain"):
        errs.append("grain 变了：%r → %r" % (base.get("grain"), head.get("grain")))
    else:
        notes.append("grain 逐字节相同")

    # ② primary_fields 逐字段
    b_pf, h_pf = base.get("primary_fields") or [], head.get("primary_fields") or []
    if len(b_pf) != len(h_pf):
        errs.append("primary_fields 数量变了：%d → %d（主字段只许 32 个，不许增删）"
                    % (len(b_pf), len(h_pf)))
    diffs = []
    for i, (a, b) in enumerate(zip(b_pf, h_pf)):
        if field_sig(a) != field_sig(b):
            for k in FIELD_KEYS:
                if json.dumps(a.get(k), ensure_ascii=False, sort_keys=True) != \
                        json.dumps(b.get(k), ensure_ascii=False, sort_keys=True):
                    diffs.append("#%d %s.%s: %r → %r" % (i, b.get("name"), k, a.get(k), b.get(k)))
    if diffs:
        errs.extend("主字段差异：" + d for d in diffs)
    else:
        notes.append("primary_fields %d 条 名/类型/可空/来源/注释 全等" % len(b_pf))

    # ③ provenance 只许追加
    b_pv = {f["name"]: f for f in (base.get("provenance_fields") or [])}
    h_pv = {f["name"]: f for f in (head.get("provenance_fields") or [])}
    removed = sorted(set(b_pv) - set(h_pv))
    added = sorted(set(h_pv) - set(b_pv))
    if removed:
        errs.append("provenance 字段被删/被改名：%s" % ", ".join(removed))
    for nm in sorted(set(b_pv) & set(h_pv)):
        for k in ("type", "note"):
            if b_pv[nm].get(k) != h_pv[nm].get(k):
                errs.append("既有 provenance 字段 %s.%s 被改：%r → %r"
                            % (nm, k, b_pv[nm].get(k), h_pv[nm].get(k)))
    notes.append("provenance %d → %d（新增 %s）"
                 % (len(b_pv), len(h_pv), ", ".join(added) or "无"))

    # ④ rev / rev_log
    if head.get("rev") != want_rev:
        errs.append("head.rev = %r，期望 %d" % (head.get("rev"), want_rev))
    log = head.get("rev_log") or []
    revs = [x.get("rev") for x in log]
    if revs != sorted(revs):
        errs.append("rev_log 顺序不对：%s" % revs)
    for need in range(1, want_rev + 1):
        if need not in revs:
            errs.append("rev_log 缺 rev %d" % need)
    top = [x for x in log if x.get("rev") == want_rev]
    if top:
        t = top[-1]
        if not t.get("rejected"):
            errs.append("rev%d 没写 rejected（方案被否的理由必须留痕）" % want_rev)
        elif "方案A" not in str(t.get("rejected")).replace(" ", ""):
            errs.append("rev%d 的 rejected 未点名「方案A」：%r"
                        % (want_rev, str(t.get("rejected"))[:80]))
        if not t.get("why"):
            errs.append("rev%d 没写 why" % want_rev)
        notes.append("rev_log %d 条：%s；rev%d 记 rejected=方案A ✓"
                     % (len(log), revs, want_rev))

    # ⑤ 顶层键白名单（只允许 rev/rev_log/geom 变化 + 字段数组追加 + 现状声明）
    #   current_state：必填的「现状护栏」（字段已定义但恒为 null 时必须写明），属纯追加元数据
    allow = {"rev", "rev_log", "geom", "provenance_fields", "current_state"}
    for k in sorted(set(base) | set(head)):
        if k in allow:
            continue
        if json.dumps(base.get(k), ensure_ascii=False, sort_keys=True) != \
                json.dumps(head.get(k), ensure_ascii=False, sort_keys=True):
            errs.append("顶层键 %s 发生了变化（不在白名单 rev/rev_log/geom/字段追加 内）" % k)
    return {"ok": not errs, "errors": errs, "notes": notes,
            "base_rev": base.get("rev"), "head_rev": head.get("rev"),
            "added_provenance": added, "removed_provenance": removed,
            "primary_fields": len(h_pf), "provenance_fields": len(h_pv)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--want-rev", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = check(load(a.base), load(a.head), a.want_rev)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        for n in res["notes"]:
            print("  ✓ " + n)
        for e in res["errors"]:
            print("  ✗ " + e)
        print(("✅ rev%s → rev%s 断言全过（主字段 %d / provenance %d）"
               % (res["base_rev"], res["head_rev"], res["primary_fields"],
                  res["provenance_fields"])) if res["ok"] else "❌ 断言失败")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
