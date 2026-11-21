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
  4. head 的 `rev` = 期望值（默认 4），`rev_log` 依次含 rev 1/2/3/4 四条；
     顶 rev 必须写明 `rejected`（含「方案A」）与 why
  5. 段落级改动白名单：只允许 rev_log / geom / 字段数组追加 / 分级口径段（enums / grade_rules / tiers）变化；其余顶层键值不许变
  6. rev>=4 额外硬判据（不只白名单，还要正面断言）：
     a) enums 只许追加：既有枚举的每个旧值必须仍在（不删不改名），只允许多出新值/新枚举键
     b) tiers 两轴必需：completeness_tier ∈ {S,A,B,C}、confidence_level ∈ {L1,L2,L3}，
        且四个新列各自写清 who_fills / when_filled / downstream_must_not_assume
     c) 两轴不许合成：tiers 必须声明正交性禁令，且禁止出现形如 qual_tier 的合成列
     d) grade_rules 必须显式声明 superseded_by=tiers + 旧档→confidence_level 单向映射 + source_confidence 处置
     e) enums.completeness_tier / enums.confidence_level 必须与 tiers 的值域一致
  7. rev>=4 另需 coverage 段（覆盖率契约）：
     a) counties_expected 带 path/vintage/sha256/county_count，且文件真存在、sha256 与 county_count 能对上
     b) 显式禁止 counties_done / counties_declared 当分母（deprecated_denominators）
     c) coverage_status 四值（ok / empty_upstream_confirmed / empty_anomaly / failed）
        + deprecated_values 含 "empty" + 迁移说明；且与 enums.coverage_status 一致
     d) verification 两值（verified / unverified）且不得混进 coverage_status
     e) status_fields.keys 含 6 个 counties_* 键名（派单原文重复了一次 counties_done）
     f) county_boundary_check：几何包实存 + sha256 对得上 + 3,144 县全覆盖 + 缺几何=fail（不许 skipped）
"""
from __future__ import annotations

import argparse
import hashlib
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

    # ⑤ 顶层键白名单（只允许 rev/rev_log/geom 变化 + 字段数组追加 + 分级口径段 + 现状声明）
    #   current_state：必填的「现状护栏」（字段已定义但恒为 null 时必须写明），属纯追加元数据
    #   coverage：rev4 内追加的覆盖率口径段（唯一法定分母 + 状态枚举 + 计数键名），同属纯追加元数据
    allow = {"rev", "rev_log", "geom", "provenance_fields", "current_state",
             "enums", "grade_rules", "tiers", "coverage"}
    for k in sorted(set(base) | set(head)):
        if k in allow:
            continue
        if json.dumps(base.get(k), ensure_ascii=False, sort_keys=True) != \
                json.dumps(head.get(k), ensure_ascii=False, sort_keys=True):
            errs.append("顶层键 %s 发生了变化（不在白名单 rev/rev_log/geom/字段追加/分级口径 内）" % k)

    # ⑥ rev>=4：enums 只许追加 + tiers 两轴正面断言 + grade_rules 替换声明
    if want_rev >= 4:
        b_en, h_en = base.get("enums") or {}, head.get("enums") or {}
        for k, old in b_en.items():
            if k.startswith("_"):
                continue
            new = h_en.get(k)
            if new is None:
                errs.append("enums.%s 被删/被改名（枚举只许追加）" % k)
                continue
            lost = [v for v in old if v not in new]
            if lost:
                errs.append("enums.%s 删了旧值：%s" % (k, lost))
        added_enum_vals = {k: [v for v in (h_en.get(k) or []) if v not in (b_en.get(k) or [])]
                           for k in h_en if not k.startswith("_")}
        notes.append("enums 追加值：%s" % {k: v for k, v in added_enum_vals.items() if v})

        tiers = head.get("tiers") or {}
        if not tiers:
            errs.append("rev>=4 必须新增顶层 tiers 段（两轴定义 + 谁填/何时填/下游假定）")
        else:
            want_vals = {"completeness_tier": ["S", "A", "B", "C"],
                         "confidence_level": ["L1", "L2", "L3"]}
            for axis, vals in want_vals.items():
                d = tiers.get(axis) or {}
                if not d:
                    errs.append("tiers.%s 缺失" % axis)
                    continue
                if list(d.get("values") or []) != vals:
                    errs.append("tiers.%s.values = %r，期望 %r" % (axis, d.get("values"), vals))
                if set(d.get("definitions") or {}) != set(vals):
                    errs.append("tiers.%s.definitions 必须逐个覆盖 %s" % (axis, vals))
                for k in ("who_fills", "when_filled", "downstream_must_not_assume"):
                    if not str(d.get(k) or "").strip():
                        errs.append("tiers.%s 缺 %s（谁填/何时填/下游能否假定非空 必须写清）"
                                    % (axis, k))
            for col in ("backfilled_fields", "missing_reason"):
                d = tiers.get(col) or {}
                if not d:
                    errs.append("tiers.%s 缺失（rev4 的元数据列也要写清谁填/何时填/下游假定）" % col)
                    continue
                for k in ("who_fills", "when_filled", "downstream_must_not_assume"):
                    if not str(d.get(k) or "").strip():
                        errs.append("tiers.%s 缺 %s" % (col, k))
            ortho = tiers.get("two_axes_orthogonality") or {}
            if not ortho.get("forbidden"):
                errs.append("tiers.two_axes_orthogonality.forbidden 缺失（必须写明禁止合成一列）")
            else:
                notes.append("两轴正交禁令已声明（禁止合成列）")
            # 合成列名一律不许出现在「列名」位置上（rev_log.rejected 里提到被否方案的列名不算）
            name_slots = ({f.get("name") for f in (head.get("primary_fields") or [])}
                          | set(h_pv) | set(tiers))
            for bad in ("qual_tier", "combined_tier", "grade_total", "quality_score"):
                if bad in name_slots:
                    errs.append("出现了合成列名 %s（两轴严禁合成一列）" % bad)

        gr = head.get("grade_rules") or {}
        if gr.get("superseded_by") != "tiers":
            errs.append("grade_rules.superseded_by 必须 = \"tiers\"（两套口径必须声明替换关系，不许并存不说清）")
        mapping = gr.get("mapping_to_confidence_level") or {}
        for old_tier in ("S-Tier", "A-Tier", "B-Tier"):
            if old_tier not in mapping:
                errs.append("grade_rules.mapping_to_confidence_level 缺 %s 的映射" % old_tier)
        if not str(gr.get("source_confidence") or "").strip():
            errs.append("grade_rules.source_confidence 必须写清保留/降级为兼容字段")
        else:
            notes.append("grade_rules → tiers 替换关系 + 旧三档映射 + source_confidence 处置已声明")

        # enums 与 tiers 值域一致
        for axis, vals in (("completeness_tier", ["S", "A", "B", "C"]),
                           ("confidence_level", ["L1", "L2", "L3"])):
            ev = [v for v in (h_en.get(axis) or []) if v is not None]
            if ev != vals:
                errs.append("enums.%s = %r 与 tiers 值域 %r 不一致" % (axis, ev, vals))

        # 四个新列必须真的进了 provenance_fields（“加了元数据段但没加列”也要报）
        need_cols = {"completeness_tier", "confidence_level", "backfilled_fields", "missing_reason"}
        miss_cols = sorted(need_cols - set(h_pv))
        if miss_cols:
            errs.append("rev4 新列没进 provenance_fields：%s" % miss_cols)
        else:
            notes.append("rev4 四列均在 provenance_fields（provenance %d → %d）" % (len(b_pv), len(h_pv)))

        # ⑦ coverage 段：唯一法定分母 + 四值状态 + 两值 verification + 6 个计数键名
        #    这一段是「覆盖率算给谁看」的硬契约，缺一项就有人会把 counties_done 当分母（永远 100%）
        cov = head.get("coverage") or {}
        if not cov:
            errs.append("缺顶层 coverage 段（覆盖率唯一法定分母 + coverage_status + verification 必须写进 SCHEMA）")
        else:
            ce = cov.get("counties_expected") or {}
            if not ce:
                errs.append("coverage.counties_expected 缺失（分母没有固定基准表就等于没有分母）")
            else:
                for k in ("path", "vintage", "sha256", "county_count"):
                    if ce.get(k) in (None, "", [], {}):
                        errs.append("coverage.counties_expected 缺 %s（基准表必须自描述：路径+vintage+指纹+规模）" % k)
                if not str(ce.get("denominator_rule") or "").strip():
                    errs.append("coverage.counties_expected.denominator_rule 缺失（必须写死「唯一法定分母」）")
                banned = {"counties_done", "counties_declared"}
                if not banned.issubset(set(ce.get("deprecated_denominators") or [])):
                    errs.append("coverage.counties_expected.deprecated_denominators 必须显式禁止 %s 当分母"
                                % sorted(banned))
                # 分母必须在仓里真的存在，且 sha256/county_count 能对上（“写了引用但没表”也要报）
                bp = REPO / str(ce.get("path") or "")
                if not ce.get("path") or not bp.exists():
                    errs.append("基准表文件不存在：%s" % (ce.get("path") or "<空>"))
                else:
                    try:
                        bdoc = json.loads(bp.read_text(encoding="utf-8"))
                    except Exception as exc:                       # noqa: BLE001
                        errs.append("基准表解析失败：%s（%s）" % (ce.get("path"), exc))
                        bdoc = {}
                    rows = bdoc.get("counties") or []
                    got = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                                                    separators=(",", ":")).encode("utf-8")).hexdigest()
                    if bdoc and got != ce.get("sha256"):
                        errs.append("基准表 sha256 不符：SCHEMA=%s 实测=%s（分母被改过就是口径被改过）"
                                    % (str(ce.get("sha256"))[:12], got[:12]))
                    if bdoc and len(rows) != bdoc.get("county_count"):
                        errs.append("基准表 county_count=%r 与实际行数 %d 不符"
                                    % (bdoc.get("county_count"), len(rows)))
                    if bdoc and ce.get("county_count") not in (None, len(rows)):
                        errs.append("SCHEMA.counties_expected.county_count=%r 与基准表行数 %d 不符"
                                    % (ce.get("county_count"), len(rows)))
                    if bdoc:
                        notes.append("基准县表实测可用：%d 县 / sha256 对得上" % len(rows))

            cs = cov.get("coverage_status") or {}
            want_cs = ["ok", "empty_upstream_confirmed", "empty_anomaly", "failed"]
            if list(cs.get("values") or []) != want_cs:
                errs.append("coverage.coverage_status.values = %r，期望 %r" % (cs.get("values"), want_cs))
            if "empty" not in (cs.get("deprecated_values") or []):
                errs.append("coverage.coverage_status.deprecated_values 必须含 \"empty\"（旧单值作废要显式声明）")
            if not str(cs.get("migration") or "").strip():
                errs.append("coverage.coverage_status.migration 缺失（旧 empty 产物怎么处理必须写清：只读不改/新产物不许出）")
            if [v for v in (h_en.get("coverage_status") or [])] != want_cs:
                errs.append("enums.coverage_status = %r 与 coverage.coverage_status.values %r 不一致"
                            % (h_en.get("coverage_status"), want_cs))

            vf = cov.get("verification") or {}
            if list(vf.get("values") or []) != ["verified", "unverified"]:
                errs.append("coverage.verification.values = %r，期望 ['verified','unverified']（warn 级标记）"
                            % vf.get("values"))
            if [v for v in (h_en.get("verification") or [])] != ["verified", "unverified"]:
                errs.append("enums.verification 必须 = ['verified','unverified']，且不得混进 coverage_status")
            if "unverified" in (h_en.get("coverage_status") or []):
                errs.append("verification 被塞进了 coverage_status 枚举（它是 warn 标记，不是第五个状态值）")

            # 县界真校验（muse-000153）：几何包必须在、sha256 对得上、3,144 县全覆盖、缺几何=fail 不许 skipped
            cb = cov.get("county_boundary_check") or {}
            if not cb:
                errs.append("coverage.county_boundary_check 缺失（D2 第②道清洗的口径必须写死）")
            else:
                pol = str(cb.get("missing_geometry_policy") or "")
                if "fail" not in pol or "skipped" in pol.split("禁止")[0]:
                    errs.append("coverage.county_boundary_check.missing_geometry_policy 必须是 fail（不许 skipped 静默放过）")
                if not str(cb.get("geometry_sha256") or "").strip():
                    errs.append("coverage.county_boundary_check 缺 geometry_sha256（几何包必须可校验）")
                gsrc = str(cb.get("geometry_source") or "")
                gp = REPO / "config" / "baseline" / "counties_geom.json.gz"
                if "counties_geom.json.gz" not in gsrc or not gp.exists():
                    errs.append("县界几何包不存在或未被声明：config/baseline/counties_geom.json.gz")
                else:
                    gsha = hashlib.sha256(gp.read_bytes()).hexdigest()
                    if gsha != cb.get("geometry_sha256"):
                        errs.append("县界几何包 sha256 不符：SCHEMA=%s 实测=%s"
                                    % (str(cb.get("geometry_sha256"))[:12], gsha[:12]))
                    import gzip as _gz
                    with _gz.open(gp, "rt", encoding="utf-8") as fh:
                        geo = json.load(fh)
                    if len(geo) != 3144:
                        errs.append("县界几何包覆盖 %d 县，期望 3,144" % len(geo))
                    elif not {c.get("county_fips") for c in (bdoc.get("counties") or [])} <= set(geo):
                        errs.append("县界几何包未覆盖基准表全部县（缺 %s）"
                                    % sorted({c.get("county_fips") for c in (bdoc.get("counties") or [])} - set(geo))[:6])
                    else:
                        notes.append("县界几何包实测：3,144/3,144 县 / sha256 对得上（真校验，缺几何=fail）")

            sf = cov.get("status_fields") or {}
            want_keys = {"counties_expected", "counties_done", "counties_declared",
                         "counties_with_any_rows", "counties_with_nad_rows",
                         "counties_nad_substantive"}
            got_keys = set(sf.get("keys") or [])
            if not want_keys.issubset(got_keys):
                errs.append("coverage.status_fields.keys 缺：%s" % sorted(want_keys - got_keys))
            if not str(sf.get("_dispatch_note") or "").strip():
                errs.append("coverage.status_fields 缺 _dispatch_note（派单列了 7 个名字其中 counties_done 重复，必须写明去重口径）")
            if "counties_expected" not in (sf.get("definitions") or {}):
                errs.append("coverage.status_fields.definitions 缺 counties_expected 的定义")
            if not errs:
                notes.append("coverage 段齐：唯一分母（3,144 县基准表）+ coverage_status 四值/deprecated empty + verification 两值 + 6 个计数键名")

    return {"ok": not errs, "errors": errs, "notes": notes,
            "base_rev": base.get("rev"), "head_rev": head.get("rev"),
            "added_provenance": added, "removed_provenance": removed,
            "primary_fields": len(h_pf), "provenance_fields": len(h_pv)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--want-rev", type=int, default=4)
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
