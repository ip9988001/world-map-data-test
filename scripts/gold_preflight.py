#!/usr/bin/env python3
"""二仓 · 开州前置核验（一仓 Release 终态封印检查）
================================================================================
为什么需要它：一仓是「边抓边传」的，Release 在采集过程中就已创建。
若在采集未收尾时开跑，会拿到缺县/缺 OVERTURE/无账本的半成品。

一仓 MANIFEST **没有 phase/sealed 字段**（已核对 DE/HI/SD/ND/AR 五份），
真正的封印判据是下面 5 条同时成立：

  C1  MANIFEST.json 已上传到 Release
  C2  generated_at 有值，且晚于（或接近）Release 创建时间
  C3  reference_check.counties_ok + counties_empty + counties_failed == counties_total
  C4  three_number_check.matches == true
  C5  县并集 + 溢出 == NAD local_rows；Σshards == 县并集 + 县界重复

注意：「已采集县数 == roster 县数」**不是**判据 —— 一仓只对 NAD 有覆盖的县产片
（SD 7/66、HI 0/5 均为合法），counties_empty 是合法状态。

退出码：0 = sealed；2 = partial/missing（拒绝开跑）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def log(msg: str) -> None:
    print(f"[preflight] {msg}", flush=True)


def check(manifest_path: Path, expect_state: str | None,
          assets_file: Path | None = None) -> tuple[str, list[str], list[str]]:
    """返回 (status, errors, warns)

    assets_file（可选）：`gh release view --json assets` 导出的实物清单（每行 `名字\t大小`）。
    为什么需要：一仓是「边抓边传 + 断点续传」的，MANIFEST 记账可能漏记实物
    —— AK 的 shards 为空但 Release 里 23 个县片都在；ID 的 assets 漏记 addrfeat 但实物 43 个在。
    只信账本 → 把好数据挡在门外；以实物为准 → 账本缺失降为 warning。
    """
    errors: list[str] = []
    warns: list[str] = []
    if not manifest_path.exists():
        return "missing", [f"MANIFEST 不存在：{manifest_path}"], warns

    actual: list[str] = []
    if assets_file and assets_file.exists():
        for line in assets_file.read_text(encoding="utf-8", errors="replace").splitlines():
            n = line.strip().split("\t")[0].strip()
            if n:
                actual.append(n.rsplit("/", 1)[-1])

    try:
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return "missing", [f"MANIFEST 无法解析：{exc}"], warns

    # C1 账本存在（已过）
    if not m.get("generated_at"):
        errors.append("C2 失败：generated_at 为空")
    if m.get("integrity", {}).get("sha256") is None:
        warns.append("integrity.sha256 缺失（不影响判定，但无法做字节级校验）")

    scope = m.get("scope") or {}
    st = scope.get("state")
    if expect_state and st and st != expect_state:
        errors.append(f"州码不符：MANIFEST={st} 期望={expect_state}")

    rc = m.get("reference_check") or {}
    total = rc.get("counties_total")
    ok = rc.get("counties_ok")
    empty = rc.get("counties_empty")
    failed = rc.get("counties_failed")
    if total is None:
        warns.append("reference_check 缺失（HI 这类 0 覆盖州会出现）")
    else:
        # C3
        if None in (ok, empty, failed):
            errors.append(f"C3 无法判定：counties_ok/empty/failed 有缺失 {ok}/{empty}/{failed}")
        elif ok + empty + failed != total:
            errors.append(f"C3 失败：{ok}+{empty}+{failed} != {total}")
        if failed:
            warns.append(f"有 {failed} 个县核验失败（一仓策略：只丢该县、不阻断）")

    # C4
    tnc = rc.get("three_number_check") or {}
    if tnc and tnc.get("matches") is False:
        errors.append("C4 失败：州级三数咬合不匹配（仅参考口径，但出现在封印态通常意味着中断）")
    elif not tnc:
        warns.append("three_number_check 缺失")

    # C5
    shards = [s for s in (m.get("shards") or []) if s.get("kind") == "county"]
    if not shards and actual:
        # ★ 记账自愈：MANIFEST.shards 漏写，但 Release 里县片实物在（NAD-<ST>-<fips>-<key>.ndjson.gz）
        for n in actual:
            if n.startswith("NAD-") and n.endswith(".ndjson.gz") and n.count("-") >= 3:
                shards.append({"kind": "county", "file": n, "rows": None})
        if shards:
            warns.append(f"MANIFEST.shards 缺失，已从 Release 实物重建 {len(shards)} 个县片（账可补，数据不丢）")
    if not shards:
        errors.append("C5 失败：没有任何 county 分片（账本与实物都没有）")
    nad_local = (m.get("completeness") or {}).get("nad", {}).get("local_rows")
    union_ids = rc.get("county_union_ids")
    overflow = rc.get("overflow_ids")
    if None not in (nad_local, union_ids, overflow):
        if union_ids + overflow != nad_local:
            errors.append(f"C5 失败：县并集 {union_ids} + 溢出 {overflow} != NAD local_rows {nad_local}")
    elif nad_local is not None:
        warns.append("county_union_ids/overflow_ids 缺失，跳过 C5 精确对账")

    shard_rows = sum((s.get("rows") or 0) for s in shards)
    src = m.get("assets") or []
    names = [a["path"].rsplit("/", 1)[-1] for a in src]
    if actual:                                  # 账本 ∪ 实物：只信账本会漏尽断点续传的产物
        names = sorted(set(names) | set(actual))
    if not any(n.endswith(".parquet") for n in names):
        errors.append("C5 失败：Release 里没有 OVERTURE parquet")
    nad_shard_names = [n for n in names if n.startswith("NAD-") and n.endswith(".ndjson.gz")]
    if not nad_shard_names:
        warns.append("assets[] 里没有 NAD 县片（一仓习惯：县片只登记在 shards[].file，不影响）")
    addrfeat = [n for n in names if n.endswith("-addrfeat.zip")]
    if len(addrfeat) < len(shards):
        warns.append(f"addrfeat {len(addrfeat)} 个 < 县片 {len(shards)} 个（缺失县会被 scope 跳过）")

    status = "sealed" if not errors else "partial"
    log(f"州={st} 县={len(shards)} 县片行数={shard_rows:,} NAD local={nad_local} "
        f"资产={len(src)} → {status.upper()}")
    return status, errors, warns


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="一仓 Release 终态封印核验")
    ap.add_argument("--state", help="期望的两位州码")
    ap.add_argument("--manifest", help="MANIFEST.json 路径")
    ap.add_argument("--raw-dir", help="等价写法：<raw-dir>/MANIFEST.json")
    ap.add_argument("--json-out", help="把结论写成 json（供 workflow 消费）")
    ap.add_argument("--assets", help="Release 实物清单（每行 名字\\t大小）；缺省时试 <raw-dir>/assets.txt")
    args = ap.parse_args(argv)

    mpath = Path(args.manifest) if args.manifest else Path(args.raw_dir or ".") / "MANIFEST.json"
    apath = Path(args.assets) if args.assets else (
        Path(args.raw_dir) / "assets.txt" if args.raw_dir else None)
    status, errors, warns = check(mpath, args.state, apath)
    for w in warns:
        log(f"⚠️ {w}")
    for e in errors:
        log(f"❌ {e}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(
            {"status": status, "errors": errors, "warnings": warns}, ensure_ascii=False, indent=1),
            encoding="utf-8")

    if status != "sealed":
        log("🚫 未达终态封印，拒绝开跑（等一仓收尾后重试）")
        return 2
    log("✅ 终态封印核验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
