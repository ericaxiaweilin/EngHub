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


def test_spawned_but_never_ticked_is_an_incident_once_the_grace_is_past():
    """只记到 spawned 且已过 2 个预期间隔 = 起了进程没人证明它在跑。"""
    assert _kinds([_state("commander-watch", alive=False, last_status="spawned",
                          state="spawned-unverified", stale_seconds=900)]) == \
        {("commander-watch", NEVER)}


def test_a_long_but_live_cycle_is_not_an_alarm():
    """10-07 真发生过的误报：调度器一轮里落进 6 小时那道闸门时单轮 >240 秒，
    新鲜度判线（2×120）会判它断写并连挂两条催办。挂催办要再宽一倍才挂。"""
    assert _kinds([_state("periodic-scheduler", alive=False, stale_seconds=273)]) == set()
    assert _kinds([_state("periodic-scheduler", alive=False, stale_seconds=400)]) == set()
    assert _kinds([_state("periodic-scheduler", alive=False, stale_seconds=1000)]) == \
        {("periodic-scheduler", STALLED)}


def test_a_loop_that_just_came_up_is_not_an_alarm():
    """引擎重启的头几分钟所有循环都停在 spawned；没有宽限就会一次挂出 N 条假警报。

    这正是 10-07 火警演练里真发生过的：巡检把刚起来的 3 个循环报成"从未确认在跑"，
    十几分钟后又自己关掉 —— 待办成了重启的副产品，不是故障。
    """
    assert _kinds([_state("commander-watch", alive=False, last_status="spawned",
                          state="spawned-unverified", interval_seconds=300,
                          stale_seconds=38.0)]) == set()


def test_repeated_failures_are_an_alarm_even_with_fresh_timestamps():
    """每轮都崩会把 last_tick_at 一直刷新；只等"没动静"就永远等不到，所以按自述状态判。"""
    assert _kinds([_state("routing-backfill", alive=False, last_status="failed",
                          stale_seconds=12.0)]) == {("routing-backfill", FAILED)}


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
                          stale_seconds=9000,
                          window_ticks=100, window_failures=20,
                          window_crash_rate=0.2)]) == {
        ("routing-backfill", STALLED), ("routing-backfill", CRASH)}


def test_loops_stalling_together_are_reported_as_one_process_not_n_bugs():
    """引擎循环共用一个进程：一起停跳时人该先看进程，不该被 N 条独立故障牵着逐个查代码。"""
    states = [_state(n, alive=False, stale_seconds=900) for n in
              ("periodic-scheduler", "followup-scanner", "commander-watch")]
    found = findings(states, crash_rate_limit=LIMIT, min_window_ticks=MIN_TICKS)
    assert len(found) == 3
    assert all(f["evidence"]["loops_not_ticking"] == 3 for f in found)
    assert "同时有 3 个循环没在跳" in found[0]["description"]
    assert "docker ps enghub-engine" in found[0]["description"]


def test_single_stall_does_not_claim_a_process_outage():
    found = findings([_state("periodic-scheduler", alive=False, stale_seconds=9000),
                      _state("followup-scanner")],
                     crash_rate_limit=LIMIT, min_window_ticks=MIN_TICKS)
    assert len(found) == 1
    assert "同时有" not in found[0]["description"]


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
    a = findings([_state(alive=False, stale_seconds=9000,
                         last_tick_at="2026-10-07 00:00:00")],
                 crash_rate_limit=LIMIT, min_window_ticks=MIN_TICKS)[0]
    b = findings([_state(alive=False, stale_seconds=9000,
                         last_tick_at="2026-10-07 06:30:00")],
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
    # 字段要和 OPEN_SQL 真查出来的那几列一致：对账比的是 title+description+sig 三样，
    # 夹具少给 description 就会把"签名没变别动库"测成"每轮都刷新"（线上不会，OPEN_SQL 选了这列）。
    return {"id": task_id, "title": finding["title"],
            "description": finding.get("description"), "status": "open",
            "payload": {"category": CATEGORY, "loop": finding["loop"],
                        "kind": finding["kind"], "sig": sig or finding["sig"]}}


def test_new_fault_creates_one_task_and_recovery_closes_it():
    found = findings([_state(alive=False, stale_seconds=9000)], crash_rate_limit=LIMIT,
                     min_window_ticks=MIN_TICKS)
    assert [a["action"] for a in plan_actions([], found)] == ["create"]
    task = _open_task(found[0])
    assert [a["action"] for a in plan_actions([task], [])] == ["close"]


def test_same_fault_same_signature_does_not_touch_the_db():
    found = findings([_state(alive=False, stale_seconds=9000)], crash_rate_limit=LIMIT,
                     min_window_ticks=MIN_TICKS)
    actions = plan_actions([_open_task(found[0])], found)
    assert [a["action"] for a in actions] == ["unchanged"]


def test_changed_reading_refreshes_the_same_task_instead_of_adding_one():
    found = findings([_state(alive=False, stale_seconds=9000,
                             last_tick_at="2026-10-07 06:00:00")],
                     crash_rate_limit=LIMIT, min_window_ticks=MIN_TICKS)
    old = _open_task(found[0], sig="periodic-scheduler|stalled|2026-10-07 00:00:00 UTC")
    actions = plan_actions([old], found)
    assert [a["action"] for a in actions] == ["refresh"]
    assert actions[0]["task_id"] == "t-1"


def test_duplicate_open_tasks_for_one_fault_are_merged():
    """旧版本重复挂出来的条目，靠对账收掉，收件箱里一个故障只留一条。"""
    found = findings([_state(alive=False, stale_seconds=9000)], crash_rate_limit=LIMIT,
                     min_window_ticks=MIN_TICKS)
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
    assert "× 2（新鲜度判线再宽一倍的挂线）" in found["description"]
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
