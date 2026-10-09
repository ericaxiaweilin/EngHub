"""引擎读数一条命令：闸门 → 五层判线格 → 三格画像 → 账本人群 → 收件箱 → 闸门计时。

为什么要有这个脚本：这一天的排查里，"登录 + 带对参数打接口 + 手拼 JSON"这套动作被重做了十几次，
手工拼出来的错至少五类 —— 漏 `factory_id` query 参数、ssh heredoc 吃掉引号、列名靠猜、
管道把退出码偷走、正则组号写错。脚本直接调服务层函数：不需要 token、不猜列名、也不碰 shell 引号。

用法 —— 必须在**容器里**跑（宿主 python 没装 asyncpg，脚本要真连库）::

    docker exec -i enghub-backend-1 python - < scripts/engine_status.py
    docker exec -i enghub-backend-1 python - --only ledger,timers < scripts/engine_status.py
    docker exec -i enghub-backend-1 python - FAC_ELEC_DEMO_2026 < scripts/engine_status.py

（`scripts/` 没有挂进容器，所以走 stdin；从 stdin 跑时没有 `__file__`，
仓库根要退回 `getcwd()`。宿主上直跑会在 import 阶段给出同样一句提示。）

只读：只调查询与判据函数；唯一可能的写是 layered_acceptance 的缓存，脚本结尾统一 rollback，
不动工单、不动台账、不发催办。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

def _root() -> str:
    """仓库根：从文件跑取脚本上级；从 stdin 跑（容器里那种用法）没有 __file__，退回 cwd。"""
    here = globals().get("__file__")
    base = os.path.dirname(os.path.abspath(here)) if here else os.getcwd()
    return os.path.dirname(base) if os.path.basename(base) == "scripts" else base


ROOT = _root()
sys.path.insert(0, ROOT)

BLOCKS = ("gate", "layers", "capability", "ledger", "inbox", "timers")


def _load_env() -> list[str]:
    """在仓库根跑时要自己吃 .env：scripts/ 没挂进容器，宿主 shell 里也没有 DATABASE_URL。

    只把键名带出去，值一个字不打（.env 里是真凭证）。
    """
    path = os.path.join(ROOT, ".env")
    seen: list[str] = []
    if not os.path.exists(path):
        return seen
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ and val:
                os.environ[key] = val
                seen.append(key)
    return seen


def _w(title: str) -> None:
    print(f"\n{'━' * 8} {title} {'━' * (56 - len(title))}")


async def show_layers(db, fid: str, refresh: bool) -> dict:
    from api.services.engine_layers import layered_acceptance
    from api.services.virtual_run import default_models

    # 机种与接口同一入口取（路由用的就是这个，脚本自己挑一套就等于另立一条路径）
    models = await default_models(db, fid, n=5)
    report = await layered_acceptance(db, fid, models, use_cache=not refresh)
    g = report.get("gate") or {}
    _w("闸门（第一个不过线的层以上不许对外引用）")
    print(f"  first_unmet_layer = {g.get('first_unmet_layer')}   "
          f"reportable_through = {g.get('reportable_through')}")

    _w("五层判线格")
    for L in report.get("layers") or []:
        marks = {"pass": "✓", "fail": "✗", "not_computable": "—", "reported": "·"}
        print(f"  {L.get('layer')} {L.get('name')}")
        for m in L.get("metrics") or []:
            v = m.get("value")
            thr = m.get("threshold")
            line = f"    {marks.get(m.get('state'), '?')} {m.get('metric')} = {v}"
            if thr is not None:
                line += f" ({m.get('sense')} {thr})"
            if m.get("n") is not None:
                line += f" [n={m.get('n')}]"
            print(line)
            if m.get("state") in ("fail", "not_computable"):
                why = m.get("missing") or m.get("basis") or ""
                print(f"        └ {str(why)[:150]}")
    return report


async def show_capability(db, fid: str, report: dict) -> None:
    from api.services.engine_capability import capability_profile
    from api.services.virtual_run import default_models

    models = await default_models(db, fid, n=5)
    prof = await capability_profile(db, fid, models, layers=report)
    _w("人的三格：总结 / 分析 / 推演")
    for name, block in (prof.get("verdict") or {}).items():
        print(f"  {name}: {block.get('state')}")
        for row in block.get("failed") or []:
            print(f"      ✗ {row}")
    s = prof.get("summary") or {}
    if s:
        print(f"  总结格实测：n={s.get('replies_with_claims')} 条带数字答复，"
              f"无出处 {s.get('numbers_unbacked')} 条，分类 "
              f"{json.dumps(s.get('unbacked_kinds'), ensure_ascii=False)}")
        print(f"  缺口点名率 = {s.get('gap_disclosure_rate')}"
              f"（分母 {s.get('replies_with_engine_gaps')} 轮）")
    a = prof.get("analysis") or {}
    if a:
        print(f"  分析格实测：方向可信 {a.get('trustworthy_rate')}、"
              f"可当动作 {a.get('actionable_rate')}、拒绝把 0 效果写成动作 "
              f"{a.get('refuses_noise_advice')}")
    print(f"  推演格引用的是 L1..L4 同名实测值，不另算一套尺： "
          f"{json.dumps(prof.get('forecast') or {}, ensure_ascii=False)[:200]}")


async def show_ledger(db, fid: str) -> None:
    from api.services.prediction_ledger import delivery_accuracy

    acc = await delivery_accuracy(db, fid)
    _w("交期准度：留痕法账本（当时说了哪天 vs 实际哪天）")
    print(f"  记账 {acc.get('orders_recorded')} 张、成对 {acc.get('paired')} 对"
          f"（判线要 ≥{acc.get('min_pairs')} 对）、MAPE={acc.get('mape')}、state={acc.get('state')}")
    print(f"  人群对照: {json.dumps(acc.get('population'), ensure_ascii=False)}")
    if acc.get("missing"):
        print(f"  算不出的原因: {acc['missing']}")


async def show_inbox(db, fid: str) -> None:
    from api.services.engine_watchdog import data_findings

    _w("收件箱：引擎自己报的数据缺口（巡检同源，这里只列不动库）")
    found = await data_findings(db, fid)
    if not found:
        print("  （本轮没有未达线的格子）")
    for f in found:
        print(f"  · {str(f.get('title'))[:120]}")


async def show_timers(db) -> None:
    from sqlalchemy import text

    _w("闸门计时与逐轮心跳（engine_loop_state）")
    rows = (await db.execute(text(
        "SELECT loop_name, last_tick_at, ticks, failures, last_status, last_detail, host"
        " FROM engine_loop_state ORDER BY last_tick_at DESC NULLS LAST"))).mappings().all()
    for r in rows:
        print(f"  {r['loop_name']:<24} tick={str(r['last_tick_at'])[:19]} "
              f"ticks={r['ticks']} fail={r['failures']} status={r['last_status']} "
              f"host={str(r['host'])[:12]}")
        det = r["last_detail"]
        if isinstance(det, str):
            try:
                det = json.loads(det)
            except Exception:  # noqa: BLE001
                det = None
        g = (det or {}).get("gates_seconds_since_last") if isinstance(det, dict) else None
        if isinstance(g, dict):
            print("      闸门距今: " + ", ".join(
                f"{k}={'—' if v is None else str(v) + 's'}" for k, v in sorted(g.items())))


async def run(fid: str, refresh: bool, only: list[str]) -> None:
    try:
        from database.db_config import db_config
    except ModuleNotFoundError as exc:      # 宿主 python 没装依赖时会在这里失败
        print(f"起不来：{exc.name} 不在当前 python 里 —— 在容器里跑：\n"
              "  docker exec -i enghub-backend-1 python - < scripts/engine_status.py",
              file=sys.stderr)
        raise SystemExit(2)

    async with db_config.session_factory() as db:
        report = await show_layers(db, fid, refresh) if {"layers", "gate", "capability"} & set(only) \
            else {}
        if "capability" in only:
            await show_capability(db, fid, report)
        if "ledger" in only:
            await show_ledger(db, fid)
        if "inbox" in only:
            await show_inbox(db, fid)
        if "timers" in only:
            await show_timers(db)
        await db.rollback()   # 只读：任何查询都不落成写


def main() -> int:
    ap = argparse.ArgumentParser(description="EngHub 引擎读数（只读）")
    ap.add_argument("factory_id", nargs="?", default="FAC_MECH_001")
    ap.add_argument("--refresh", action="store_true",
                    help="绕过分层验收的 15 分钟缓存，重跑一次探针（慢几十秒）")
    ap.add_argument("--only", default=",".join(BLOCKS),
                    help="逗号分隔的块：" + ",".join(BLOCKS))
    args = ap.parse_args()
    loaded = _load_env()
    if loaded:
        # 只报键名：.env 里是真凭证，把值带进日志就等于把它交出去
        print(f"（从 .env 补了 {len(loaded)} 个环境变量：{', '.join(sorted(loaded)[:8])}"
              f"{'…' if len(loaded) > 8 else ''}）")
    if not os.getenv("DATABASE_URL"):
        print("缺少 DATABASE_URL —— 在仓库根跑（那里有 .env），或先导出连接串", file=sys.stderr)
        return 2
    only = [b.strip() for b in args.only.split(",") if b.strip() in BLOCKS]
    asyncio.run(run(args.factory_id, args.refresh, only))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
