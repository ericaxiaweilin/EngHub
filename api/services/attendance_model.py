"""按天气折算预计出勤 —— 考勤断了不等于不能算人，但算出来的必须叫"预计"。

用户 10-06 给的标定：**天气好 97%、雨天 92%、暴雨 70%** 出勤。
同时厂里的真实考勤停在 2026-08-22（近 30 天 0 条），所以这一维现在只有"在册人数"，没有"今天到了多少人"。

两条底线：
1. **不往 `attendance` 表里写生成记录**。那张表是现场事实的表，灌进去就和真打卡分不开 ——
   我们刚清掉一批这种"自己造的自己读"的数据（假 IE 工时、自写报工反推工时）。
   预计出勤只作为读数输出，来源、天气、折算率全部随行标注。
2. **天气取不到就不折算**。取不到时返回 `rate=None` 并说明原因，
   而不是默默按 97% 算 —— 那等于把"没查到"报成"人都到齐了"。

坐标沿用环境预警那一条基线（`alert_intelligence_service` 里的胡志明市工业区），
不在这里另立第二个厂址；哪天厂址进主档了，两边一起改。
"""
from __future__ import annotations

import os
from datetime import date as ddate
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import text

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
FACTORY_LAT = float(os.getenv("FACTORY_LATITUDE", "10.8231"))
FACTORY_LON = float(os.getenv("FACTORY_LONGITUDE", "106.6297"))
FACTORY_TZ = os.getenv("FACTORY_TIMEZONE", "Asia/Ho_Chi_Minh")

# 用户给的三档折算率（可覆盖，覆盖后 basis 里要写清是谁改的）
RATE_DRY = float(os.getenv("ATTENDANCE_RATE_DRY", "0.97"))
RATE_RAIN = float(os.getenv("ATTENDANCE_RATE_RAIN", "0.92"))
RATE_STORM = float(os.getenv("ATTENDANCE_RATE_STORM", "0.70"))
# 分档阈值：日累计降水（mm）。WMO 码里 63/65/80/81/82 是雨到暴雨，这里以雨量为准、码兜底。
RAIN_MM = float(os.getenv("ATTENDANCE_RAIN_MM", "1.0"))
STORM_MM = float(os.getenv("ATTENDANCE_STORM_MM", "50.0"))

ATTENDANCE_GAP_SQL = text("""
    SELECT MAX(date::date) AS last_real_date, COUNT(DISTINCT operator_id) AS people_with_records
    FROM attendance WHERE factory_id = :fid
""")

HEADCOUNT_BASE_SQL = text("""
    SELECT COUNT(*) AS active_roster
    FROM hr_employees WHERE factory_id = :fid AND status = 'active'
""")

# 同一天只取一次天气：链条每 15 分钟一轮，没必要每轮都打外部接口
_WEATHER_CACHE: Dict[str, Dict[str, Any]] = {}


_SEVERITY = {"dry": 0, "rain": 1, "storm": 2}

# WMO 天气码分档：雷暴/短时强降水即使累计雨量不大，现场也是"下大了"的那一档
_STORM_CODES = {65, 82, 95, 96, 99}
_RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 66, 71, 73, 75, 80, 81, 85}


def weather_condition(precip_mm: Optional[float], weather_code: Optional[int] = None) -> str:
    """把天气折成 dry / rain / storm —— 雨量与天气码两个信号里**取更严重的那一档**。

    为什么不是只读雨量：实测今天 21.7mm（按累计量只算"雨"）配 WMO 95（雷暴）。
    雷暴天工人照样淋、照样停手，按 92% 折算就是往乐观偏。
    两个信号都没有时才返回 unknown，由调用方决定"不折算"，不默认成晴天。
    """
    bands = []
    if precip_mm is not None:
        bands.append("storm" if precip_mm >= STORM_MM else ("rain" if precip_mm >= RAIN_MM else "dry"))
    if weather_code is not None:
        code = int(weather_code)
        bands.append("storm" if code in _STORM_CODES else ("rain" if code in _RAIN_CODES else "dry"))
    if not bands:
        return "unknown"
    return max(bands, key=lambda band: _SEVERITY[band])


def attendance_rate(condition: str) -> Optional[float]:
    return {"dry": RATE_DRY, "rain": RATE_RAIN, "storm": RATE_STORM}.get(condition)


def expected_headcount(roster: int, condition: str) -> Optional[int]:
    rate = attendance_rate(condition)
    if rate is None or roster <= 0:
        return None
    return int(round(roster * rate))


async def fetch_weather(on: ddate) -> Dict[str, Any]:
    """取某天的日累计降水与天气码。取不到就说取不到，不给默认天气。"""
    key = f"{FACTORY_LAT},{FACTORY_LON},{on.isoformat()}"
    if key in _WEATHER_CACHE:
        return _WEATHER_CACHE[key]
    out: Dict[str, Any] = {"ok": False, "precip_mm": None, "weather_code": None}
    try:
        import httpx

        day = on.isoformat()
        url = (f"{WEATHER_URL}?latitude={FACTORY_LAT}&longitude={FACTORY_LON}"
               f"&daily=precipitation_sum,weather_code&timezone={FACTORY_TZ}"
               f"&start_date={day}&end_date={day}")
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(url)
        daily = (resp.json() or {}).get("daily") or {}
        precip = (daily.get("precipitation_sum") or [None])[0]
        code = (daily.get("weather_code") or [None])[0]
        if precip is None and code is None:
            out["reason"] = "气象接口没返回这一天的数据"
        else:
            out.update({"ok": True, "precip_mm": precip,
                        "weather_code": int(code) if code is not None else None})
    except Exception as exc:  # 外部接口：超时/DNS/限流都算取不到
        out["reason"] = f"气象接口取不到：{type(exc).__name__}"
    _WEATHER_CACHE[key] = out
    return out


async def expected_attendance(db, factory_id: str, *, on: Optional[ddate] = None) -> Dict[str, Any]:
    """今天（或指定日）预计多少人到岗：在册人数 × 天气折算率，全程带依据。"""
    on = on or ddate.today()
    base = (await db.execute(HEADCOUNT_BASE_SQL, {"fid": factory_id})).mappings().first()
    gap = (await db.execute(ATTENDANCE_GAP_SQL, {"fid": factory_id})).mappings().first()
    weather = await fetch_weather(on)
    condition = weather_condition(weather.get("precip_mm"), weather.get("weather_code"))
    rate = attendance_rate(condition)
    roster = int(base["active_roster"] or 0) if base else 0

    last_real = gap["last_real_date"] if gap else None
    stale_days = None
    if last_real:
        stale_days = (on - (last_real if hasattr(last_real, "year") else ddate.today())).days

    out = {
        "date": on.isoformat(),
        "roster_active": roster,
        "weather": {
            "ok": weather.get("ok"),
            "condition": condition,
            "precip_mm": weather.get("precip_mm"),
            "weather_code": weather.get("weather_code"),
            "location": f"{FACTORY_LAT},{FACTORY_LON}（{FACTORY_TZ}，与车间环境预警同一坐标）",
            "reason": weather.get("reason"),
        },
        "rates_calibration": {"dry": RATE_DRY, "rain": RATE_RAIN, "storm": RATE_STORM,
                              "storm_over_mm": STORM_MM, "rain_over_mm": RAIN_MM,
                              "source": "用户口述 2026-10-06（好天97% / 雨92% / 暴雨70%）"},
        "expected_rate": rate,
        "expected_present": expected_headcount(roster, condition) if rate else None,
        "expected_absent": (roster - expected_headcount(roster, condition))
        if rate and expected_headcount(roster, condition) is not None else None,
        "real_attendance": {
            "last_record_date": str(last_real) if last_real else None,
            "stale_days": stale_days,
            "note": "attendance 表是现场打卡表；预计出勤不写进这张表，只作读数输出",
        },
        "basis": ("天气折算·用户标定（不是打卡实测）" if rate else "算不出：天气数据没取到，不折算"),
    }
    if not rate:
        out["verdict"] = (f"考勤停在 {str(last_real)[:10] if last_real else '没有记录'}，"
                          f"今天天气也没取到 → 出勤这一维没有可信值，只能报在册 {roster} 人")
    else:
        out["verdict"] = (f"{condition}（降水 {weather.get('precip_mm')}mm）→ 按 {rate:.0%} 折算，"
                          f"在册 {roster} 人预计到岗 {out['expected_present']} 人，"
                          f"缺 {out['expected_absent']} 人；这是估算不是打卡")
    return out
