"""引擎后台循环的唯一启动入口（独立进程，不再塞在 API worker 里）。

原来这 5 个循环在 main.py 的 startup handler 里 create_task，而 uvicorn 跑
`--workers 2`：两个 worker 各起一套（真跑起来会重复下单、重复报工），而且
create_task 的返回值一个都没存 —— asyncio 只持弱引用，任务可能跑一半被 GC。
实测后果：API 全部正常，引擎却静默停摆（最后一条自主虚拟工厂报工停在 00:12，
之后十几小时没有任何自主动作，而 startup handler 确实执行过两次）。

现在：循环只在这个独立进程里跑；API worker 不再启动它们，只读心跳。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Tuple

from api.services.engine_heartbeat import record

logger = logging.getLogger(__name__)

# 崩溃后重启前的退避，避免坏循环把 CPU 点着
RESTART_BACKOFF_SECONDS = 30

_tasks: "set[asyncio.Task]" = set()

# 关停时在跑的循环会收到取消，它们自己 catch 后 return —— 那是收尾，不是故障。
# 没有这个标记，每次 docker stop 都会在 last_error 里留下"循环返回，引擎已停止该任务"，
# 收件箱与心跳页下次被人读成"引擎挂过"。
_shutting_down = False

# 跑完就该退出的那一个（种子技能）不算停摆；其它循环返回都要被拉起来。
ONE_SHOT_LOOPS = frozenset({"skill-seed"})


def _mark_shutting_down() -> None:
    """把"进程在收尾"记在模块里：循环是被取消后 return 的，那不该记成故障。

    uvicorn 关停时先取消任务、再走 lifespan 的 shutdown，所以只靠 shutdown 钩子设标记
    会晚一步 —— 实测一次 docker restart 连刷三行"循环返回，引擎已停止该任务"，
    读数上看像引擎挂过。信号先到，标记就先到。
    """
    global _shutting_down
    _shutting_down = True


def install_shutdown_signal() -> None:
    """给自己装 SIGTERM/SIGINT 的收尾标记；装不上就退回原判定，不把信号处理搞坏。"""
    import signal

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _mark_shutting_down)
        except (AttributeError, NotImplementedError, ValueError, RuntimeError):
            logger.debug("[engine] %s 装不上收尾标记，关停判定退回宽限", sig.name)


def _loop_makers() -> List[Tuple[str, Callable[[], Coroutine[Any, Any, Any]], bool]]:
    """(循环名, 协程工厂, 是否自己报每轮心跳)。

    periodic-scheduler 是引擎的心脏（30 秒一轮、真实耗时叠加）；model-warmup /
    followup-scanner / commander-watch / routing-backfill 也都逐轮报心跳，
    报的是这一轮真实干了多少活，不再只证明"起了没崩"。
    """
    import main as enghub_main
    from api.routes.chat_routes import model_warmup_loop
    from api.services.factory_commander import commander_watch_loop
    from api.services.followup_task_service import followup_scanner_loop
    from api.services.routing_backfill import routing_backfill_loop
    from scripts.seed_skills_startup import run_skill_seed

    return [
        ("periodic-scheduler", enghub_main._periodic_scheduler, True),
        ("model-warmup", model_warmup_loop, False),
        ("skill-seed", run_skill_seed, False),
        ("followup-scanner", followup_scanner_loop, False),
        ("commander-watch", commander_watch_loop, False),
        ("routing-backfill", routing_backfill_loop, True),
    ]


async def _supervise(name: str, maker: Callable[[], Coroutine[Any, Any, Any]],
                     ticking: bool) -> None:
    await record(name, "spawned", detail={"ticking": ticking})
    while True:
        try:
            await maker()
            # 无限循环不该返回。返回了分三种，判错一种就是事故：
            #   ① 进程在收尾 —— 记 stopped，不写 last_error（否则每次重启都像挂过）；
            #   ② 本来就是一次性任务 —— 记 exited，照旧不再拉起；
            #   ③ 引擎还在跑、没人让它停 —— 那不是"结束"，是停摆：退避后重启。
            #     10-06 心跳停摆几个小时就是这么来的：循环返回后监督者直接 return。
            if _shutting_down:
                await record(name, "stopped", detail={"reason": "引擎关停，循环收尾退出"})
                logger.info("[engine] %s 随关停退出", name)
                return
            if name in ONE_SHOT_LOOPS:
                await record(name, "exited", detail={"reason": "一次性任务跑完"})
                logger.info("[engine] %s 是一次性任务，跑完退出", name)
                return
            await record(name, "restarting", error="循环返回但引擎仍在运行，退避后重启")
            logger.warning("[engine] %s 意外返回，%s 秒后重启", name, RESTART_BACKOFF_SECONDS)
            await asyncio.sleep(RESTART_BACKOFF_SECONDS)
            continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("[engine] %s 异常退出: %s", name, exc)
            await record(name, "failed", error=f"{type(exc).__name__}: {exc}")
            await asyncio.sleep(RESTART_BACKOFF_SECONDS)


async def start_engine_loops() -> Dict[str, int]:
    """起全部引擎循环并强引用住任务。"""
    install_shutdown_signal()
    started: Dict[str, int] = {}
    for name, maker, ticking in _loop_makers():
        task = asyncio.create_task(_supervise(name, maker, ticking), name=f"engine:{name}")
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        started[name] = id(task)
        logger.info("[engine] 已启动 %s", name)
    return started


async def stop_engine_loops() -> None:
    _mark_shutting_down()
    for task in list(_tasks):
        task.cancel()
