"""引擎进程 —— 无人任务中心的后台循环跑在这里，不跑在 API worker 里。

    docker compose -f docker/docker-compose.minimal.yml up -d engine
    curl http://<服务器>:18889/health

为什么单独一个进程：uvicorn 是 `--workers 2`，循环写在 startup handler 里
就会两套 worker 各起一遍（重复下单、重复报工），而且 create_task 的返回值
没人存，asyncio 只持弱引用 —— 实测结果是 API 一切正常、引擎静默停摆。

`--workers 1` 是这套循环的硬要求，不是可以优化的细节。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.services.engine_heartbeat import read_states
from api.services.engine_runner import start_engine_loops, stop_engine_loops

HEART_LOOP = "periodic-scheduler"
# 心跳超过 4 个间隔没更新就判死（30s 一轮 -> 2 分钟），给 compose 的健康检查用
STALE_FACTOR = 4

app = FastAPI(title="EngHub Engine", version="1.0")


@app.on_event("startup")
async def _boot() -> None:
    await start_engine_loops()


@app.on_event("shutdown")
async def _halt() -> None:
    """关停要有收尾这一步：没有它，循环是被进程直接拆掉的，
    last_error 里就留下"循环返回，引擎已停止该任务" —— 一次正常重启在读数上像一次故障。"""
    await stop_engine_loops()


def verdict(states) -> tuple:
    heart = next((s for s in states if s["loop"] == HEART_LOOP), None)
    if not heart:
        return False, "引擎心跳表里没有 periodic-scheduler 的记录"
    limit = int(heart["interval_seconds"] or 30) * STALE_FACTOR
    stale = heart.get("stale_seconds")
    if stale is None:
        return False, "periodic-scheduler 还没跳过第一轮"
    if stale > limit:
        return False, f"心跳已 {round(stale)} 秒未更新（阈值 {limit} 秒）"
    if heart.get("failures"):
        return True, f"活着，但累计失败 {heart['failures']} 次，最近一次：{(heart.get('last_error') or '')[:120]}"
    return True, "活着"


@app.get("/health")
async def health():
    states = await read_states()
    alive, reason = verdict(states)
    body = {
        "service": "enghub-engine",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "engine_alive": alive,
        "reason": reason,
        "loops": states,
    }
    return JSONResponse(status_code=200 if alive else 503, content=body)
