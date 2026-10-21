#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二仓离线自测（不联网、不下载、不需要 duckdb）

跑法：python3 tests/test_gold_offline.py

覆盖 2026-10-21 修的那批问题（每条都对应一个曾经在生产上崩过的场景）：
  T1 shard_fips 三种字段写法（county_fips / fips / 只有文件名）
  T2 溢出型州不再崩（NH 事故：nad_rows=None 拿去格式化 → TypeError）
  T3 账本只写 fips 时也能认县（AK 事故：manifest_heal 补的 shard 只有 fips → KeyError）
  T4 addrfeat 缺失 → 该县进 skipped_counties，其余县照加工
  T5 preflight：州级三数不咬合不再拒跑（G4）；读得到 phase=complete_partial（G7）
  T6 产物缺口声明：upstream_gaps() 必须如实给出缺几个县 / 哪几个县
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import gold_scope      # noqa: E402
import gold_preflight  # noqa: E402

try:                                     # coalesce 依赖较重，能导入就测，导不进就跳过
    import gold_coalesce  # noqa: E402
    HAS_COALESCE = True
except Exception as _exc:                 # noqa: BLE001
    HAS_COALESCE = False
    COALESCE_ERR = str(_exc)

DE = [("10001", "kent"), ("10003", "new_castle"), ("10005", "sussex")]


def mk_raw(tmp: Path, shards: list[dict], overflow: bool = False,
           addrfeat_for: list[str] | None = None,
           phase: str = "complete", failed: list[dict] | None = None) -> Path:
    """造一个最小的一仓 raw 目录（MANIFEST + STATUS + assets 清单）。"""
    tmp.mkdir(parents=True, exist_ok=True)
    shards = list(shards)
    if overflow:
        shards.append({"kind": "overflow", "file": "NAD-US-DE-OUTOFSTATE.ndjson.gz",
                       "rows": 100})
    assets = [{"path": "overture/OVERTURE-US-DE.parquet", "bytes": 4096}]
    for fips, key in DE:
        assets.append({"path": f"tiger/TIGER-US-DE-county-{fips}.geojson", "bytes": 2048})
        if addrfeat_for is None or fips in addrfeat_for:
            assets.append({"path": f"tiger/TIGER-US-DE-{fips}-addrfeat.zip", "bytes": 2048})
    # 县片实物：shards 里写了什么就存在什么（一仓“记账与实物同源”的最小模拟）
    for s in shards:
        fn = str(s.get("file") or "")
        if s.get("kind") == "county" and not fn:
            fips = s.get("county_fips") or s.get("fips")
            key = s.get("county_key") or s.get("county") or "x"
            fn = f"NAD-US-DE-{fips}-{key}.ndjson.gz"
        if fn:
            assets.append({"path": f"nad/{fn}", "bytes": 4096})
    man = {
        "generated_at": "2026-10-21T00:00:00Z",
        "runner": "offline-test",
        "scope": {"state": "DE", "state_fips": "10"},
        "assets": assets,
        "shards": shards,
        "reference_check": {
            "counties_ok": len([s for s in shards if s.get("kind") == "county"]),
            "counties_empty": 0, "counties_failed": len(failed or []),
            "counties_total": 3, "failed_counties": failed or [],
            "three_number_check": {"matches": False, "gap_ids": 5},
        },
        "completeness": {"nad": {"local_rows": 100}},
    }
    (tmp / "MANIFEST.json").write_text(json.dumps(man), encoding="utf-8")
    (tmp / "STATUS.json").write_text(json.dumps({"phase": phase}), encoding="utf-8")
    (tmp / "assets.txt").write_text("", encoding="utf-8")
    return tmp


def scope_of(tmp: Path) -> dict:
    return gold_scope.build_scope("DE", tmp, REPO / "rules/US/state_roster.yaml",
                                  REPO / "rules/geo/global_admin_registry.json")


def main() -> int:
    results: dict[str, bool] = {}
    base = Path(tempfile.mkdtemp(prefix="gold-offline-"))

    # ---- T1 字段三写法 ----
    r1 = {
        "原生 county_fips": gold_scope.shard_fips({"county_fips": "10001"}) == "10001",
        "heal 的 fips": gold_scope.shard_fips({"fips": "10003"}) == "10003",
        "只有文件名": gold_scope.shard_fips(
            {"file": "data/raw/US-DE/nad/NAD-US-DE-10005-sussex.ndjson.gz"}) == "10005",
        "文件名推 key": gold_scope.shard_key(
            {"file": "NAD-US-DE-10005-sussex.ndjson.gz"}) == "sussex",
    }
    results["T1"] = all(r1.values())
    print("T1 字段三写法：", r1)

    # ---- T2 溢出型州不崩 ----
    d2 = mk_raw(base / "t2", shards=[], overflow=True)
    rc2 = subprocess.run([sys.executable, "scripts/gold_scope.py", "--state", "DE",
                          "--raw-dir", str(d2), "--out", str(d2 / "scope.json")],
                         cwd=REPO, capture_output=True, text=True)
    sc2 = json.loads((d2 / "scope.json").read_text(encoding="utf-8")) if rc2.returncode == 0 else {}
    r2 = {
        "退出0（旧版必崩 TypeError）": rc2.returncode == 0,
        "溢出模式生效": all(c.get("nad_from_overflow") for c in sc2.get("counties") or []),
        "nad_rows 允许为空": all(c.get("nad_rows") is None for c in sc2.get("counties") or []),
        "县数=roster": len(sc2.get("counties") or []) == 3,
    }
    results["T2"] = all(r2.values())
    print("T2 溢出型州：", r2, "" if rc2.returncode == 0 else rc2.stderr[-300:])

    # ---- T3 heal 风格 shard（只有 fips） ----
    d3 = mk_raw(base / "t3", shards=[
        {"kind": "county", "file": "NAD-US-DE-10001-kent.ndjson.gz", "fips": "10001",
         "county": "kent", "rows": 10}])
    sc3 = scope_of(d3)
    r3 = {
        "不抛 KeyError": True,
        "认到该县": [c["fips"] for c in sc3["counties"]] == ["10001"],
        "key 从字段补齐": sc3["counties"][0].get("key") == "kent",
        "其余县进 0 覆盖声明": sorted(c["fips"] for c in sc3["zero_nad_counties"]) == ["10003", "10005"],
        "没有假的 skipped": sc3["skipped_counties"] == [],
    }
    results["T3"] = all(r3.values())
    print("T3 heal 风格 shard：", r3)

    # ---- T4 addrfeat 缺失只跳该县 ----
    d4 = mk_raw(base / "t4",
                shards=[{"kind": "county", "county_fips": f, "county_key": k, "rows": 5}
                        for f, k in DE],
                addrfeat_for=["10001"])
    sc4 = scope_of(d4)
    skipped4 = {s["fips"]: s["missing"] for s in sc4["skipped_counties"]}
    r4 = {
        "好县保留": [c["fips"] for c in sc4["counties"]] == ["10001"],
        "缺 addrfeat 的县被点名": sorted(skipped4) == ["10003", "10005"],
        "缺口写明缺什么": skipped4.get("10003") == ["addrfeat"],
        "没有假字段 oa_rows": all("oa_rows" not in c for c in sc4["zero_nad_counties"]),
    }
    results["T4"] = all(r4.values())
    print("T4 addrfeat 缺失：", r4)

    # ---- T5 preflight：C4 降级 + 读 phase ----
    d5 = mk_raw(base / "t5",
                shards=[{"kind": "county", "county_fips": f, "county_key": k, "rows": 5}
                        for f, k in DE[:2]],
                phase="complete_partial",
                failed=[{"county_fips": "10005", "county_key": "sussex",
                         "county_name": "Sussex", "reason": "行数不符"}])
    status5, errs5, warns5, phase5 = gold_preflight.check(d5 / "MANIFEST.json", "DE")
    r5 = {
        "缺县不拒跑": status5 == "sealed",
        "州级不咬合不再报错": not any("C4" in e for e in errs5),
        "州级降为提示": any("C4 提示" in w for w in warns5),
        "读到 complete_partial": phase5 == "complete_partial",
        "缺县有提示": any("complete_partial" in w for w in warns5),
    }
    results["T5"] = all(r5.values())
    print("T5 preflight：", r5, "| errors:", errs5)

    # ---- T6 产物缺口声明 ----
    d6 = mk_raw(base / "t6",
                shards=[{"kind": "county", "county_fips": f, "county_key": k, "rows": 5}
                        for f, k in DE[:2]],
                phase="complete_partial",
                failed=[{"county_fips": "10005", "county_key": "sussex",
                         "county_name": "Sussex", "reason": "行数不符"}])
    sc6 = scope_of(d6)
    r6 = {"scope 带缺口": (sc6.get("upstream_gaps") or {}).get("missing_count") == 1}
    if HAS_COALESCE:
        g = gold_coalesce.upstream_gaps(sc6)
        r6.update({
            "缺 1 个县": g["missing_count"] == 1,
            "点名到县": [c["fips"] for c in g["missing_counties"]] == ["10005"],
            "带 phase": g["phase"] == "complete_partial" and g["complete_partial"] is True,
            "不许当完整": "不得当完整州" in g["note"],
        })
    else:
        print(f"  （coalesce 未导入，跳过合并断言：{COALESCE_ERR}）")
    results["T6"] = all(r6.values())
    print("T6 产物缺口声明：", r6)

    # ---- T7 Overture 两种形态（州级单文件 / 按县分片）----
    d7 = mk_raw(base / "t7", shards=[{"kind": "county", "county_fips": f, "county_key": k,
                                     "rows": 5} for f, k in DE])
    m7 = json.loads((d7 / "MANIFEST.json").read_text(encoding="utf-8"))
    m7["assets"] = [a for a in m7["assets"] if "overture" not in a["path"]]
    for f, k in DE:
        m7["assets"].append({"path": f"overture/OVERTURE-US-DE-{f}-{k}.parquet", "bytes": 1024})
    (d7 / "MANIFEST.json").write_text(json.dumps(m7), encoding="utf-8")
    sc7 = scope_of(d7)
    files7 = sc7["assets"].get("overture_files") or []
    r7 = {
        "收集全部县片": len(files7) == 3,
        "模式=per_county": sc7["assets"].get("overture_mode") == "per_county",
        "不再只留最后一个": len(set(files7)) == 3,
        "compat 字段仍有值": bool(sc7["assets"].get("overture")),
    }
    results["T7"] = all(r7.values())
    print(f"  T7: {r7}")
    print("T7 判定：", "✅ 通过" if results["T7"]
          else f"❌ 失败 {[k for k, v in r7.items() if not v]}")

    bad = [k for k, v in results.items() if not v]
    print("\n总判定：", "✅ 全部通过" if not bad else f"❌ 失败 {bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
