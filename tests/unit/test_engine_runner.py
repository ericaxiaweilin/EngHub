"""引擎循环的收尾判定：关停要留"stopped"，无人值守的循环不能一次返回就永久沉默。

两点都是实测逼出来的：`docker restart` 时 uvicorn 先取消任务、再走 shutdown 钩子，
标记晚一步，日志就连刷"循环返回，引擎已停止该任务"，读数上像引擎挂过；
而 `_supervise` 原本对任何正常返回都 `return`（不再重启）—— 一次意外收尾
就等于这条循环从此静默停摆，无人工厂最怕的就是这个。
"""
import asyncio

import pytest

pytestmark = [pytest.mark.unit]

from api.services import engine_runner as er


@pytest.fixture(autouse=True)
def _clean_state():
    er._shutting_down = False
    yield
    er._shutting_down = False


async def _noop_sleep(_seconds):
    return


def _returns_after(rounds):
    """跳几轮就自己返回的循环：模拟被取消后 catch 住并收尾退出的那种写法。"""
    state = {"calls": 0}

    async def loop():
        state["calls"] += 1
        await asyncio.sleep(0)
        if state["calls"] >= rounds:
            return
        return

    return loop, state


def test_shutdown_mark_makes_the_exit_read_as_stopped_not_failed(monkeypatch):
    seen = []

    async def fake_record(name, status="tick", detail=None, error=None, **kw):
        seen.append({"status": status, "error": error, "detail": detail})

    monkeypatch.setattr(er, "record", fake_record)
    er._mark_shutting_down()
    loop, _state = _returns_after(1)
    asyncio.run(er._supervise("followup-scanner", loop, False))
    assert seen[-1]["status"] == "stopped", seen
    assert not seen[-1]["error"], "正常关停不许写进 last_error（下次读心跳的人会当成故障）"


def test_one_shot_task_still_exits_without_an_error_line(monkeypatch):
    seen = []

    async def fake_record(name, status="tick", detail=None, error=None, **kw):
        seen.append({"status": status, "error": error})

    monkeypatch.setattr(er, "record", fake_record)
    loop, state = _returns_after(1)
    asyncio.run(er._supervise("skill-seed", loop, False))
    assert state["calls"] == 1, "一次性任务不能被反复拉起"
    assert seen[-1]["status"] == "exited" and not seen[-1]["error"]


def test_a_resident_loop_that_returns_is_restarted_not_left_silent(monkeypatch):
    """引擎还在跑、没人让它停 —— 返回就是停摆，必须再拉起。"""
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            return
        raise asyncio.CancelledError()

    recorded = []

    async def fake_record(name, status="tick", detail=None, error=None, **kw):
        recorded.append(status)

    monkeypatch.setattr(er, "record", fake_record)
    monkeypatch.setattr(er.asyncio, "sleep", _noop_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(er._supervise("commander-watch", flaky, False))
    assert calls["n"] == 3, calls
    assert recorded.count("restarting") == 2, recorded


def test_signal_hook_install_never_breaks_loop_startup(monkeypatch):
    class _NoHandlers:
        def add_signal_handler(self, *a, **kw):
            raise NotImplementedError()

    monkeypatch.setattr(er.asyncio, "get_running_loop", lambda: _NoHandlers())
    er.install_shutdown_signal()          # 装不上也不能抛：起循环比记收尾重要
    assert er._shutting_down is False


def test_one_shot_list_is_explicit():
    assert er.ONE_SHOT_LOOPS == frozenset({"skill-seed"}), "常驻循环不能被悄悄列成一次性任务"
