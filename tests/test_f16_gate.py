#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F16 阻塞门禁离线自测（T1~T3）

跑法：python3 -m unittest discover -s tests -v   或   python3 tests/test_f16_gate.py

为什么单独一个文件：`tests/test_gold_offline.py` 的 T1~T8 是既有验收基线（2026-10-21 事故回归），
不许为了新功能去动它；F16 门禁是 2026-11-22 新加的，自己的回归自己带。

三条硬判据（对应派单「F16 门禁自证」）：
  T1  清单里有 state=open 的 P0 → gold_preflight rc=1，stderr 点出编号
  T2  全 closed → rc=0（且不因为「清单存在」而误伤密封州）
  T3  bypass_f16=true → rc=0，且 step summary 里能看到 bypass_f16=true + 未关闭编号
  T4  清单缺失 / schema 不对 / closed 无 evidence → 一样 rc=1（fail-closed，不许「读不到就当没有」）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import gold_preflight  # noqa: E402

DE = [("10001", "kent"), ("10003", "new_castle"), ("10005", "sussex")]


def sealed_raw(tmp: Path) -> Path:
    """造一个「已封印」的最小一仓目录（3 县片 + OVERTURE + 账本自洽）。"""
    tmp.mkdir(parents=True, exist_ok=True)
    assets = [{"path": "overture/OVERTURE-US-DE.parquet", "bytes": 4096}]
    shards = []
    for fips, key in DE:
        fn = f"NAD-US-DE-{fips}-{key}.ndjson.gz"
        shards.append({"kind": "county", "county_fips": fips, "county_key": key,
                       "file": fn, "rows": 10})
        assets.append({"path": f"nad/{fn}", "bytes": 4096})
        assets.append({"path": f"tiger/TIGER-US-DE-{fips}-addrfeat.zip", "bytes": 2048})
        assets.append({"path": f"tiger/TIGER-US-DE-county-{fips}.geojson", "bytes": 2048})
    (tmp / "MANIFEST.json").write_text(json.dumps({
        "generated_at": "2026-11-22T00:00:00Z",
        "scope": {"state": "DE", "state_fips": "10"},
        "assets": assets, "shards": shards,
        "reference_check": {"counties_ok": 3, "counties_empty": 0, "counties_failed": 0,
                            "counties_total": 3,
                            "three_number_check": {"matches": True, "gap_ids": 0}},
        "completeness": {"nad": {"local_rows": 30}},
    }), encoding="utf-8")
    (tmp / "STATUS.json").write_text(json.dumps({"phase": "complete"}), encoding="utf-8")
    (tmp / "assets.txt").write_text("", encoding="utf-8")
    return tmp


def blockers_file(tmp: Path, blockers: list[dict], schema: str = "f16-blockers/v1") -> Path:
    p = tmp / "f16_blockers.json"
    p.write_text(json.dumps({"schema": schema, "bypass_allowed": True,
                             "blockers": blockers}, ensure_ascii=False), encoding="utf-8")
    return p


def run_preflight(raw: Path, bpath: Path | None, bypass: bool = False, summary: Path | None = None):
    args = [sys.executable, "scripts/gold_preflight.py", "--state", "DE", "--raw-dir", str(raw)]
    if bpath is not None:
        args += ["--f16-blockers", str(bpath)]
    if bypass:
        args += ["--bypass-f16"]
    env = dict(os.environ)
    env.pop("GITHUB_STEP_SUMMARY", None)
    if summary is not None:
        env["GITHUB_STEP_SUMMARY"] = str(summary)
    r = subprocess.run(args, cwd=REPO, capture_output=True, text=True, env=env)
    return r.returncode, r.stdout, r.stderr


class F16GateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="f16-"))
        self.raw = sealed_raw(self.tmp / "raw")

    # ---- T1：有未关闭 P0 → rc=1，stderr 点名 ----
    def test_t1_open_p0_blocks(self):
        b = blockers_file(self.tmp, [
            {"id": "P0-DEMO", "severity": "P0", "state": "open", "title": "造一个未关闭 P0"},
            {"id": "P1-OK", "severity": "P1", "state": "closed", "title": "已关", "evidence": "x"},
        ])
        rc, out, err = run_preflight(self.raw, b)
        self.assertEqual(rc, 1, err[-400:])
        self.assertIn("P0-DEMO", err)
        self.assertIn("F16", err)

    # ---- T2：全 closed → rc=0（且密封州照过）----
    def test_t2_all_closed_passes(self):
        b = blockers_file(self.tmp, [
            {"id": "G1", "severity": "P0", "state": "closed", "title": "已修",
             "evidence": "tests/test_gold_offline.py T2"},
        ])
        rc, out, err = run_preflight(self.raw, b)
        self.assertEqual(rc, 0, err[-400:])
        self.assertIn("终态封印核验通过", out + err)

    # ---- T3：bypass → rc=0 且摘要留痕 ----
    def test_t3_bypass_records_in_summary(self):
        b = blockers_file(self.tmp, [
            {"id": "P0-DEMO", "severity": "P0", "state": "open", "title": "未关闭"},
        ])
        sm = self.tmp / "summary.md"
        rc, out, err = run_preflight(self.raw, b, bypass=True, summary=sm)
        self.assertEqual(rc, 0, err[-400:])
        text = sm.read_text(encoding="utf-8")
        self.assertIn("bypass_f16：**true**", text)
        self.assertIn("P0-DEMO", text)

    # ---- T4：fail-closed ----
    def test_t4_missing_file_is_fail_closed(self):
        rc, out, err = run_preflight(self.raw, self.tmp / "nope.json")
        self.assertEqual(rc, 1)
        self.assertIn("不存在", err)

    def test_t4b_bad_schema(self):
        b = blockers_file(self.tmp, [{"id": "X", "severity": "P0", "state": "open"}],
                          schema="f16-blockers/v999")
        rc, _o, err = run_preflight(self.raw, b)
        self.assertEqual(rc, 1)
        self.assertIn("schema", err)

    def test_t4c_closed_without_evidence(self):
        b = blockers_file(self.tmp, [{"id": "Z", "severity": "P0", "state": "closed"}])
        rc, _o, err = run_preflight(self.raw, b)
        self.assertEqual(rc, 1)
        self.assertIn("evidence", err)

    # ---- T5：仓库自带的真清单必须能被解析（不要求无 P0，只要求结构合法）----
    def test_t5_repo_blockers_file_parses(self):
        res = gold_preflight.f16_gate(REPO / "config/f16_blockers.json")
        self.assertEqual(res["errors"], [], res["errors"])
        self.assertGreaterEqual(res["counts"]["blockers"], 1)
        self.assertIn("bypass_allowed", json.loads(
            (REPO / "config/f16_blockers.json").read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
