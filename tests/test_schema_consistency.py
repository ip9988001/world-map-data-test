#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SCHEMA ↔ 代码 口径一致性校验（muse-000158 第三条）。

跑法（两种都行）：
  python3 -m pytest tests/test_schema_consistency.py -q
  python3 tests/test_schema_consistency.py

为什么要有这个文件：
  `counties_nad_substantive` 的分母口径写在两处 —— `schema/SCHEMA.json`
  （`coverage.counties_nad_substantive.denominator_priority`，对外契约/人读）
  与 `scripts/coverage_counters.py`（`nad_substantive_threshold()`，实际算的）。
  历史上这两处漂过两次：文档把绝对下限 10 当成唯一门槛、而代码按 1%×housing_units 算；
  代码 001153 版还留过「优先总融合行数，为 0 才退回 housing_units」的兜底分支。
  只改一处 = 另一处继续骗人。这个文件就是那道闸。

三条断言（对应派单 A3 的 1/2/3）：
  S1  SCHEMA 文本侧：`denominator_priority` 必须含 `housing_units`，
      且**不得**含旧口径的两个短语（黑名单见下文 OLD_PHRASES）。
  S2  签名侧：`inspect.signature(nad_substantive_threshold)` 的参数**只有** `housing_units`
      一个（多一个少一个都 fail —— 多一个说明融合行数被接回来，少一个说明调用方在猜）。
  S3  端到端：`nad_substantive_threshold(177734) == max(10, ceil(0.01×177734)) == 1778`；
      `nad_substantive_threshold(500) == 10`（1%×500=5 → 抬到绝对下限 10）。

零第三方依赖（pytest 只是可选跑法）。口径定稿：muse-000155 / 000156 / 000158。
"""
from __future__ import annotations

import inspect
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO / "schema" / "SCHEMA.json"

sys.path.insert(0, str(REPO / "scripts"))
import coverage_counters as CC   # noqa: E402

# 旧口径字样（S1 黑名单）
OLD_PHRASES = ("优先用该县总融合行数", "为 0 时退回")
# 绝对下限 / 相对比例（与 scripts/coverage_counters.py 的常量对齐，由 S3 交叉验证）
ABS_MIN = 10
RATIO = 0.01
HU_33011 = 177_734          # NH Strafford：基准表 housing_units


def _denominator_priority() -> str:
    doc = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return doc["coverage"]["counties_nad_substantive"]["denominator_priority"]


# ---------------------------------------------------------------- S1
def test_schema_denominator_priority_text():
    """SCHEMA 的分母口径文字必须是「固定为 housing_units」，不许回退到融合行数。"""
    txt = _denominator_priority()
    assert "housing_units" in txt, (
        "schema/SCHEMA.json → coverage.counties_nad_substantive.denominator_priority "
        "必须含 housing_units（现文：%r）" % txt)
    hits = [p for p in OLD_PHRASES if p in txt]
    assert not hits, (
        "schema/SCHEMA.json → coverage.counties_nad_substantive.denominator_priority "
        "出现旧口径字样 %s（现文：%r）；分母固定为 housing_units，融合行数只作被除数" % (hits, txt))


# ---------------------------------------------------------------- S2
def test_signature_is_single_param_housing_units():
    """函数签名必须且只能有一个参数 housing_units。"""
    params = list(inspect.signature(CC.nad_substantive_threshold).parameters.values())
    names = [p.name for p in params]
    assert names == ["housing_units"], (
        "scripts/coverage_counters.py → nad_substantive_threshold() 参数表必须只有 "
        "[housing_units]，实测 %s（多一个=融合行数被接回来，少一个=调用方在猜）" % names)
    assert params[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD, (
        "nad_substantive_threshold 的唯一参数必须是普通位置/关键字参数，实测 %s" % params[0].kind)
    # 双参调用必须当场炸（旧口径调用方一旦回流立刻暴露）
    try:
        CC.nad_substantive_threshold(HU_33011, 10_000_000)   # type: ignore[call-arg]
    except TypeError:
        pass
    else:
        raise AssertionError(
            "nad_substantive_threshold(hu, fused_rows) 竟然没抛 TypeError —— "
            "说明融合行数又被接受为第二参（001153 旧口径回流）")


# ---------------------------------------------------------------- S3
def test_threshold_end_to_end():
    """端到端：大县走 1%，小县抬到绝对下限 10。"""
    hu = CC.housing_units_of(CC.load_baseline(), "33011")
    assert hu == HU_33011, "基准表 33011 的 housing_units 变了（实测 %r），断言基准需更新" % hu
    expect_big = max(ABS_MIN, math.ceil(RATIO * HU_33011))          # = 1778
    assert expect_big == 1778, "算式基准异常：max(10, ceil(1%%×177734)) = %d" % expect_big
    got_big = CC.nad_substantive_threshold(HU_33011)
    assert got_big == expect_big, (
        "nad_substantive_threshold(%d) 实测 %r，期望 %d（=max(10, ceil(1%%×%d))）"
        % (HU_33011, got_big, expect_big, HU_33011))
    # 小县：1%×500 = 5 < 10 → 绝对下限兜底
    got_small = CC.nad_substantive_threshold(500)
    assert got_small == ABS_MIN, (
        "nad_substantive_threshold(500) 实测 %r，期望 %d（1%%×500=5 → 抬到绝对下限）"
        % (got_small, ABS_MIN))
    # 缺失/≤0 → None（不计数也不当通过）
    assert CC.nad_substantive_threshold(0) is None and CC.nad_substantive_threshold(None) is None, (
        "housing_units 缺失或 ≤0 时必须返回 None（不计数也不当通过），"
        "实测 0→%r None→%r" % (CC.nad_substantive_threshold(0), CC.nad_substantive_threshold(None)))


# 允许 `python3 tests/test_schema_consistency.py` 直跑（不经 pytest）
def main() -> int:
    tests = [test_schema_denominator_priority_text,
             test_signature_is_single_param_housing_units,
             test_threshold_end_to_end]
    bad = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            bad += 1
            print("❌ %s\n   %s" % (t.__name__, exc))
        else:
            print("✅ %s" % t.__name__)
    print("\n总判定：%s（%d/%d）" % ("✅ 全部通过" if not bad else "❌ 失败", len(tests) - bad, len(tests)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
