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


def _loop_makers() -> List[Tuple[str, Callable[[], Coroutine[Any, Any, Any]], bool]]:
    """(循环名, 协程工厂, 是否自己报每轮心跳)。

    只有 periodic-scheduler 会逐轮写心跳（它就是引擎的心脏，30 秒一轮）；
    其余四个内部各自 sleep，这里只记录启动与崩溃，不谎报"还在跳"。
    """
    import main as enghub_main
    from api.routes.chat_routes import model_warmup_loop
    from api.services.factory_commander import commander_watch_loop
    from api.services.followup_task_service import followup_scanner_loop
    from scripts.seed_skills_startup import run_skill_seed

    return [
        ("periodic-scheduler", enghub_main._periodic_scheduler, True),
        ("model-warmup", model_warmup_loop, False),
        ("skill-seed", run_skill_seed, False),
        ("followup-scanner", followup_scanner_loop, False),
        ("commander-watch", commander_watch_loop, False),
    ]


async def _supervise(name: str, maker: Callable[[], Coroutine[Any, Any, Any]],
                     ticking: bool) -> None:
    await record(name, "spawned", detail={"ticking": ticking})
    while True:
        try:
            await maker()
            # 无限循环不该返回；返回了就说明它自己结束了，如实记下
            await record(name, "exited", error="循环返回，引擎已停止该任务")
            logger.warning("[engine] %s 自行结束，不再重启", name)
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("[engine] %s 异常退出: %s", name, exc)
            await record(name, "failed", error=f"{type(exc).__name__}: {exc}")
            await asyncio.sleep(RESTART_BACKOFF_SECONDS)


async def start_engine_loops() -> Dict[str, int]:
    """起全部引擎循环并强引用住任务。"""
    started: Dict[str, int] = {}
    for name, maker, ticking in _loop_makers():
        task = asyncio.create_task(_supervise(name, maker, ticking), name=f"engine:{name}")
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        started[name] = id(task)
        logger.info("[engine] 已启动 %s", name)
    return started


async def stop_engine_loops() -> None:
    for task in list(_tasks):
        task.cancel()
