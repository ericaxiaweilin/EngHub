#!/usr/bin/env python3
"""指挥官策略回放 / A-B 评估器（只读，不写库、不触发执行）。

commander_decision_log 每轮存了「全精度输入态 + 决策 + policy_version」。本脚本把它
当**语料**用，回答两个问题：

1. **回放校验**：用当前策略重跑历史输入态，决策是否等价？
   —— 这是落盘可信度的自检：不等价说明快照丢了信息，或策略已变（policy_version 变了）。
2. **阈值 A/B**：把 SURPLUS/DEFICIT 阈值换成变体，哪些历史状态会**改变模式与决策**？
   —— 这是"策略变更是否有数据可依"的落点。

用法：
    python scripts/commander_policy_replay.py                      # 回放校验 + 模式分布
    python scripts/commander_policy_replay.py --ab surplus=1.1     # 单阈值 A/B
    python scripts/commander_policy_replay.py --ab surplus=1.1 --ab deficit=0.7

注意：A/B 只在 mode_source='policy' 的行上有意义 —— forced/override 是人工作出的决定，
不能算成策略效果。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg  # noqa: E402

from api.services import factory_commander as fc  # noqa: E402
from api.services.factory_commander import (  # noqa: E402
    FactoryCommander,
    FactoryState,
    OrderMode,
)

_THRESHOLD_NAMES = {
    "surplus": "SURPLUS_RATIO_THRESHOLD",
    "deficit": "DEFICIT_RATIO_THRESHOLD",
}


def _rebuild(snapshot) -> FactoryState:
    """从落盘快照重建 FactoryState（快照字段与 dataclass 一一对应）。"""
    snap = json.loads(snapshot) if isinstance(snapshot, str) else dict(snapshot)
    snap["order_mode"] = OrderMode(snap["order_mode"])
    return FactoryState(**snap)


def _sig_objs(decisions) -> list:
    return [(d.action.value, d.priority, d.target) for d in decisions]


def _sig_rows(decisions) -> list:
    rows = json.loads(decisions) if isinstance(decisions, str) else decisions
    return [(d["action"], d["priority"], d.get("target")) for d in rows]


async def _fetch():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        return await conn.fetch(
            "select factory_id, cycle_id, mode, mode_source, state_snapshot, decisions, "
            "policy_version, created_at from commander_decision_log order by created_at"
        )
    finally:
        await conn.close()


async def main() -> int:
    ap = argparse.ArgumentParser(description="指挥官策略回放 / A-B（只读）")
    ap.add_argument("--ab", action="append", default=[],
                    help="阈值变体，如 surplus=1.1 / deficit=0.7（可重复）")
    args = ap.parse_args()

    rows = await _fetch()
    if not rows:
        print("语料为空：commander_decision_log 还没有记录。")
        print("先跑几轮指挥官：POST /api/v1/commander/cycle  {\"factory_id\": ..., \"auto_execute\": false}")
        return 1

    factories = sorted({r["factory_id"] for r in rows})
    versions = sorted({r["policy_version"] for r in rows})
    print(f"语料：{len(rows)} 行 | 工厂 {len(factories)} 个 {factories} | policy_version {versions}")
    print()

    cmd = FactoryCommander(None)  # _assess_order_mode / _decide 不依赖 db

    # ── 1. 回放校验 ────────────────────────────────────────────────
    ok, mismatches = 0, []
    policy_rows = []
    for r in rows:
        st = _rebuild(r["state_snapshot"])
        st.order_mode = cmd._assess_order_mode(st)
        dec = await cmd._decide(st)
        if _sig_objs(dec) == _sig_rows(r["decisions"]):
            ok += 1
        else:
            mismatches.append(r["cycle_id"])
        if r["mode_source"] == "policy":
            policy_rows.append(r)

    print(f"[1] 回放校验：{ok}/{len(rows)} 决策等价"
          f"{'（全部一致）' if ok == len(rows) else ' —— 不一致 ' + str(len(mismatches)) + ' 行'}")
    for cid in mismatches[:5]:
        print(f"      mismatch cycle={cid}")
    print(f"    来源分布：{dict(Counter(r['mode_source'] for r in rows))}")
    print(f"    模式分布（全部）：{dict(Counter(r['mode'] for r in rows))}")
    print(f"    policy 语料（可用于 A/B）：{len(policy_rows)} 行，"
          f"模式分布 {dict(Counter(r['mode'] for r in policy_rows))}")
    print()

    if not args.ab:
        print("未指定 --ab，跳过策略 A/B。")
        return 0

    # ── 2. 阈值 A/B ───────────────────────────────────────────────
    override = {}
    for kv in args.ab:
        if "=" not in kv:
            print(f"--ab 参数格式错误：{kv}（应为 surplus=1.1）")
            return 2
        key, val = kv.split("=", 1)
        key = key.strip()
        if key not in _THRESHOLD_NAMES:
            print(f"未知阈值：{key}（可选 {list(_THRESHOLD_NAMES)}）")
            return 2
        override[_THRESHOLD_NAMES[key]] = float(val)

    baseline = {k: getattr(fc, k) for k in override}
    print(f"[2] 阈值 A/B：变体 {override}（基线 {baseline}）")

    if not policy_rows:
        print("    policy 来源语料为 0，无法评估（当前语料都是 forced/override）。")
        return 0

    flips = []
    try:
        for name, val in override.items():
            setattr(fc, name, val)
        for r in policy_rows:
            base_mode = _rebuild(r["state_snapshot"]).order_mode.value  # 落盘时的模式
            st = _rebuild(r["state_snapshot"])
            st.order_mode = cmd._assess_order_mode(st)
            if st.order_mode.value != base_mode:
                dec = await cmd._decide(st)
                flips.append((r["factory_id"], r["cycle_id"], base_mode,
                              st.order_mode.value, len(_sig_rows(r["decisions"])), len(dec)))
    finally:
        for name, val in baseline.items():
            setattr(fc, name, val)  # 还原，绝不让进程内状态泄漏

    print(f"    策略敏感度：{len(policy_rows)} 行 policy 语料中 **{len(flips)} 行模式改变**")
    for fid, cid, a, b, n0, n1 in flips[:15]:
        print(f"      {fid} {cid[:8]}: {a} -> {b} | 决策数 {n0} -> {n1}")
    if len(flips) > 15:
        print(f"      ...另有 {len(flips) - 15} 行")
    print()
    print("提示：语料多样性 = 结论可信度上限。若 N 个工厂只有 N 种状态，"
          "任何阈值变体都只能在这 N 个点上被检验。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
