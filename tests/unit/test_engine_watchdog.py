"""引擎健康巡检：判据、签名、对账动作。

只测纯函数（findings / plan_actions / 文案），不碰库 —— 动库那条路在预演接口里看得到。
"""
from api.services.engine_watchdog import (
    CATEGORY,
    CRASH,
    EXITED,
    FAILED,
    NEVER,
    ONE_SHOT_LOOPS,
    STALLED,
    findings,
    plan_actions,
)

LIMIT = 0.01
MIN_TICKS = 12


def _state(loop="periodic-scheduler", **over):
    base = {
        "loop": loop, "alive": True, "state": "ticking", "last_status": "tick",
        "stale_seconds": 40.0, "last_tick_at": "2026-10-07 02:00:00",
        "started_at": "2026-10-06 09:00:00", "interval_seconds": 120,
        "host": "enghub-engine", "pid": 1, "ticks": 900, "failures": 0,
        "last_error": None, "recent_errors": [],
        "window_started_at": "2026-10-06 14:56:51", "window_ticks": 138,
        "window_failures": 0, "window_crash_rate": 0.0,
    }
    base.update(over)
    return base


def _kinds(states):
    return {(f["loop"], f["kind"]) for f in findings(states, crash_rate_limit=LIMIT,
                                                     min_window_ticks=MIN_TICKS)}


# ── 判据 ────────────────────────────────────────────────────────────────────
def test_healthy_loops_raise_nothing():
    assert findings([_state(), _state("followup-scanner")],
                    crash_rate_limit=LIMIT, min_window_ticks=MIN_TICKS) == []


def test_stale_heartbeat_is_a_finding():
    got = findings([_state(alive=False, stale_seconds=5 * 3600)],
                   crash_rate_limit=LIMIT, min_window_ticks=MIN_TICKS)
    assert [f["kind"] for f in got] == [STALLED]
    assert got[0]["severity"] == "critical"


def test_one_shot_task_exiting_is_not_an_incident():
    """skill-seed 跑完退出是设计如此；把它当"引擎停了"催人是假警报。"""
    assert "skill-seed" in ONE_SHOT_LOOPS
    assert _kinds([_state("skill-seed", alive=False, state="exited",
                          last_status="exited", stale_seconds=41000)]) == set()


def test_infinite_loop_returning_is_an_incident():
    assert _kinds([_state("followup-scanner", alive=False, state="exited",
                          last_status="exited")]) == {("followup-scanner", EXITED)}


def test_crashed_loop_that_never_resumed_is_an_incident():
    assert _kinds([_state("routing-backfill", alive=False, last_status="failed",
                          recent_errors=[{"at": "2026-10-07T01:00:00",
                                          "error": "ValueError: bad param"}])]) == \
        {("routing-backfill", FAILED)}


def test_spawned_but_never_ticked_is_an_incident():
    assert _kinds([_state("commander-watch", alive=False, last_status="spawned",
                          state="spawned-unverified")]) == {("commander-watch", NEVER)}


def test_crash_rate_only_judged_inside_the_window_and_over_the_line():
    assert _kinds([_state("routing-backfill", window_ticks=100, window_failures=3,
                          window_crash_rate=0.03)]) == {("routing-backfill", CRASH)}
    # 窗口只攒了 10 跳（少于 12）就不足以下判断 —— 和 L1 判据同一个门槛
    assert _kinds([_state("routing-backfill", window_ticks=10, window_failures=5,
                          window_crash_rate=0.5)]) == set()
    # 1/138 = 0.7% 没越 1%，不挂
    assert _kinds([_state("routing-backfill", window_ticks=138, window_failures=1,
                          window_crash_rate=round(1 / 138, 5))]) == set()


def test_crash_and_stall_are_separate_findings_for_the_same_loop():
    assert _kinds([_state("routing-backfill", alive=False, last_status="tick",
                          window_ticks=100, window_failures=20,
                          window_crash_rate=0.2)]) == {
        ("routing-backfill", STALLED), ("routing-backfill", CRASH)}


# ── 签名：什么算"同一条故障" ─────────────────────────────────────────────────
def test_aging_stall_does_not_change_the_signature():
    """断写每 10 分钟"更久了一点"不是新故障；拿它当签名会把待办刷成日志。"""
    a = findings([_state(alive=False, stale_seconds=5 * 3600)], crash_rate_limit=LIMIT,
                 min_window_ticks=MIN_TICKS)[0]
    b = findings([_state(alive=False, stale_seconds=5.2 * 3600)], crash_rate_limit=LIMIT,
                 min_window_ticks=MIN_TICKS)[0]
    assert a["sig"] == b["sig"]
    assert "5.2 小时" in b["description"]      # 时长仍然报给人看，只是不进签名


def test_a_second_stall_after_recovery_is_a_new_signature():
    a = findings([_state(alive=False, last_tick_at="2026-10-07 00:00:00")],
                 crash_rate_limit=LIMIT, min_window_ticks=MIN_TICKS)[0]
    b = findings([_state(alive=False, last_tick_at="2026-10-07 06:30:00")],
                 crash_rate_limit=LIMIT, min_window_ticks=MIN_TICKS)[0]
    assert a["sig"] != b["sig"]


def test_crash_signature_buckets_the_rate():
    def sig(rate):
        return findings([_state("routing-backfill", window_ticks=100,
                                window_failures=int(rate * 100), window_crash_rate=rate)],
                       crash_rate_limit=LIMIT, min_window_ticks=MIN_TICKS)[0]["sig"]

    assert sig(0.09) == sig(0.093)          # 4% 以内的抖动算同一条
    assert sig(0.09) != sig(0.3)


# ── 对账动作 ────────────────────────────────────────────────────────────────
def _open_task(finding, task_id="t-1", sig=None):
    return {"id": task_id, "title": finding["title"], "status": "open",
            "payload": {"category": CATEGORY, "loop": finding["loop"],
                        "kind": finding["kind"], "sig": sig or finding["sig"]}}


def test_new_fault_creates_one_task_and_recovery_closes_it():
    found = findings([_state(alive=False)], crash_rate_limit=LIMIT, min_window_ticks=MIN_TICKS)
    assert [a["action"] for a in plan_actions([], found)] == ["create"]
    task = _open_task(found[0])
    assert [a["action"] for a in plan_actions([task], [])] == ["close"]


def test_same_fault_same_signature_does_not_touch_the_db():
    found = findings([_state(alive=False)], crash_rate_limit=LIMIT, min_window_ticks=MIN_TICKS)
    actions = plan_actions([_open_task(found[0])], found)
    assert [a["action"] for a in actions] == ["unchanged"]


def test_changed_reading_refreshes_the_same_task_instead_of_adding_one():
    found = findings([_state(alive=False, last_tick_at="2026-10-07 06:00:00")],
                     crash_rate_limit=LIMIT, min_window_ticks=MIN_TICKS)
    old = _open_task(found[0], sig="periodic-scheduler|stalled|2026-10-07 00:00:00 UTC")
    actions = plan_actions([old], found)
    assert [a["action"] for a in actions] == ["refresh"]
    assert actions[0]["task_id"] == "t-1"


def test_duplicate_open_tasks_for_one_fault_are_merged():
    """旧版本重复挂出来的条目，靠对账收掉，收件箱里一个故障只留一条。"""
    found = findings([_state(alive=False)], crash_rate_limit=LIMIT, min_window_ticks=MIN_TICKS)
    actions = plan_actions([_open_task(found[0], "keep"), _open_task(found[0], "extra")], found)
    assert sorted(a["action"] for a in actions) == ["close_duplicate", "unchanged"]
    assert [a["task_id"] for a in actions if a["action"] == "close_duplicate"] == ["extra"]


def test_unpayloaded_legacy_task_is_closed_not_matched():
    """没写 loop/kind 的历史条目匹配不上任何判据，按"这条故障已不在"关掉。"""
    legacy = {"id": "legacy", "title": "引擎｜老催办", "status": "open", "payload": None}
    actions = plan_actions([legacy], [])
    assert [a["action"] for a in actions] == ["close"]


# ── 催办上的字（人真正读到的那一行） ─────────────────────────────────────────
def test_stall_text_names_the_loop_the_deadline_and_how_to_check():
    found = findings([_state(alive=False, stale_seconds=2 * 3600, interval_seconds=120)],
                     crash_rate_limit=LIMIT, min_window_ticks=MIN_TICKS)[0]
    assert "periodic-scheduler" in found["title"]
    assert "心跳断写" in found["title"]
    assert "2 × 120 秒" in found["description"]
    assert "UTC" in found["description"]            # 不写时区就会被当成本地时间差 8 小时
    assert "/api/v1/pmc/engine-layers" in found["description"]
    assert found["block_reason"].startswith("periodic-scheduler")


def test_crash_text_carries_both_sides_of_the_ratio_and_the_line():
    found = findings([_state("routing-backfill", window_ticks=137, window_failures=4,
                             window_crash_rate=round(4 / 137, 5))],
                     crash_rate_limit=LIMIT, min_window_ticks=MIN_TICKS)[0]
    assert "4/137" in found["title"]
    assert "2.9%" in found["title"]
    assert "判线 ≤1%" in found["description"]


def test_last_error_ring_is_carried_into_the_task_verbatim():
    found = findings([_state("routing-backfill", alive=False, last_status="failed",
                             recent_errors=[{"at": "2026-10-07T01:00:00",
                                             "error": "asyncpg.exceptions.TooManyConnectionsError"}])],
                     crash_rate_limit=LIMIT, min_window_ticks=MIN_TICKS)[0]
    assert "TooManyConnectionsError" in found["description"]
