"""预计出勤 = 在册人数 × 天气折算率。天气不靠问人，靠北宁的历史雨量推。

用户 10-06 给的标定：**好天 97%、雨 92%、暴雨 70%**，并且明确"随机吧，按北宁地区历史雨量推"。
厂里真实考勤停在 2026-08-22（近 30 天 0 条），所以这一维只能是**预计**，不是实测。

天气依据分三层，按可信度排（读数里必须说清用了哪层）：
1. **当日实况天气** —— 实测优先，能取到就用；
2. **北宁近 3 年逐日雨量的按月分布**做定档抽样 —— 仿真时钟推进的那些日子没有天气预报，
   按当月历史档位抽一个。同一个日期永远抽到同一档（可复现；随机数不可复现就等于每次重排交期都不一样）；
3. 两层都拿不到 → **不折算**。绝不拿 97% 当默认值，那等于把"没查到"报成"人都到齐了"。

阈值是我定的，理由写在这好让人推翻：`>=30mm` 算暴雨 —— 北宁 2023-2025 共 1,096 天里 50 天（4.6%）
落在这一档，最湿 5 天是 111.5 / 104.6 / 89.1 / 68.9 / 67.5mm；越南官方"mưa lớn"是 24 小时 50mm，
但那更接近"成灾"而不是"工人淋雨停手"。`>=1mm` 算雨天。两个阈值都可用环境变量改。

红线：**不往 `attendance` 表写生成记录**。那张表是现场打卡表，灌进去就和真打卡分不开 ——
这次刚清完一批"自己造的自己读"的数据（假 IE 工时、拿自写报工反推工时）。
"""
from __future__ import annotations

import hashlib
import os
from datetime import date as ddate
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

# 天气按**区域**取，不是一个全局坐标：越南南北气候差很多，北宁（河内东侧工业区）雨季 5-9 月，
# 胡志明市是南部工业重地、雨季更长更热。一套数盖不住两个厂，所以两个区域都留着。
# 厂区→区域走 `factories.config->>'weather_region'`；没配就用默认区域，并在读数里说明是默认 —— 不猜。
REGIONS: Dict[str, Dict[str, Any]] = {
    "bacninh": {"label": "北宁 Bắc Ninh", "lat": 21.186, "lon": 106.046},
    "hochiminh": {"label": "胡志明市 TP.HCM", "lat": 10.8231, "lon": 106.6297},
}
DEFAULT_REGION = os.getenv("ATTENDANCE_REGION", "bacninh")
FACTORY_TZ = os.getenv("FACTORY_TIMEZONE", "Asia/Ho_Chi_Minh")

# 显式给了经纬度就当成自定义区域（新厂/外迁时不必改代码）
_CUSTOM_LAT = os.getenv("FACTORY_LATITUDE")
_CUSTOM_LON = os.getenv("FACTORY_LONGITUDE")
if _CUSTOM_LAT and _CUSTOM_LON:
    REGIONS["custom"] = {"label": "自定义坐标", "lat": float(_CUSTOM_LAT), "lon": float(_CUSTOM_LON)}
    DEFAULT_REGION = "custom"


def region_meta(key: str) -> Dict[str, Any]:
    return REGIONS.get(key) or REGIONS[DEFAULT_REGION]


def region_coords(key: str) -> Tuple[float, float]:
    meta = region_meta(key)
    return float(meta["lat"]), float(meta["lon"])


async def resolve_region(db, factory_id: str) -> Tuple[str, str]:
    """这个厂区按哪个区域的天气：配置里写了就用配置，没写用默认并把来源说清。"""
    import json as _json

    row = (await db.execute(text(
        "SELECT config FROM factories WHERE id = :fid"
    ), {"fid": factory_id})).mappings().first()
    config = (row["config"] if row else None) or {}
    if isinstance(config, str):
        try:
            config = _json.loads(config) or {}
        except ValueError:
            config = {}
    want = str((config or {}).get("weather_region") or "").strip().lower()
    if want in REGIONS:
        return want, "厂区配置 factories.config.weather_region"
    return DEFAULT_REGION, f"厂区没配 weather_region，按默认区域（{region_meta(DEFAULT_REGION)['label']}）"


# 默认区域坐标（给了厂区没配区域时的兜底；按厂区取区域的调用请用 resolve_region）
FACTORY_LAT, FACTORY_LON = region_coords(DEFAULT_REGION)


FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

RATE_DRY = float(os.getenv("ATTENDANCE_RATE_DRY", "0.97"))
RATE_RAIN = float(os.getenv("ATTENDANCE_RATE_RAIN", "0.92"))
RATE_STORM = float(os.getenv("ATTENDANCE_RATE_STORM", "0.70"))
RAIN_MM = float(os.getenv("ATTENDANCE_RAIN_MM", "1.0"))
STORM_MM = float(os.getenv("ATTENDANCE_STORM_MM", "30.0"))
HISTORY_YEARS = max(1, int(os.getenv("ATTENDANCE_HISTORY_YEARS", "3")))

ATTENDANCE_GAP_SQL = text("""
    SELECT MAX(date::date) AS last_real_date, COUNT(DISTINCT operator_id) AS people_with_records
    FROM attendance WHERE factory_id = :fid
""")

HEADCOUNT_BASE_SQL = text("""
    SELECT COUNT(*) AS active_roster
    FROM hr_employees WHERE factory_id = :fid AND status = 'active'
""")

_SEVERITY = {"dry": 0, "rain": 1, "storm": 2}
_BANDS = ("dry", "rain", "storm")
# 雷暴/短时强降水即使累计雨量不大，现场也是"下大了"那一档
_STORM_CODES = {65, 82, 95, 96, 99}
_RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 66, 71, 73, 75, 80, 81, 85}

_LIVE_CACHE: Dict[str, Dict[str, Any]] = {}
_CLIMATE_CACHE: Dict[str, Dict[str, Any]] = {}


def band_of_amount(precip_mm: Optional[float]) -> Optional[str]:
    if precip_mm is None:
        return None
    if precip_mm >= STORM_MM:
        return "storm"
    if precip_mm >= RAIN_MM:
        return "rain"
    return "dry"


def band_of_code(weather_code: Optional[int]) -> Optional[str]:
    if weather_code is None:
        return None
    code = int(weather_code)
    if code in _STORM_CODES:
        return "storm"
    if code in _RAIN_CODES:
        return "rain"
    return "dry"


def weather_condition(precip_mm: Optional[float], weather_code: Optional[int] = None) -> str:
    """折成 dry / rain / storm —— 雨量与天气码取**更严重**的那一档。

    不只读雨量的理由：2026-10-06 实测 21.7mm（按累计量只是"雨"）配 WMO 95（雷暴），
    雷暴天工人照样淋、照样停手，按 92% 折算就是往乐观偏。
    """
    bands = [b for b in (band_of_amount(precip_mm), band_of_code(weather_code)) if b]
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


def band_shares(series: List[Tuple[ddate, Optional[float]]]) -> Dict[str, Any]:
    """日雨量序列 → 按月档位分布 + 当月平均折算率。纯函数，好拿历史数据对撞。"""
    months: Dict[int, List[int]] = {m: [0, 0, 0] for m in range(1, 13)}
    observed = missing = 0
    for day, mm in series:
        if mm is None:
            missing += 1
            continue
        months[day.month][_SEVERITY[band_of_amount(mm)]] += 1
        observed += 1
    out: Dict[str, Any] = {}
    for m, counts in months.items():
        tot = sum(counts)
        if not tot:
            continue
        shares = {_BANDS[i]: counts[i] / tot for i in range(3)}
        out[str(m)] = {
            "days": tot,
            "dry": round(shares["dry"], 4),
            "rain": round(shares["rain"], 4),
            "storm": round(shares["storm"], 4),
            "average_rate": round(sum(attendance_rate(b) * shares[b] for b in _BANDS), 4),
        }
    return {"months": out, "observed_days": observed, "missing_days": missing}


def draw_band(month_shares: Dict[str, Any], key: str) -> Optional[str]:
    """按当月历史分布定档。md5 而不是 random：仿真要能重算对账。"""
    if not month_shares:
        return None
    cut = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    acc = 0.0
    for band in _BANDS:
        acc += float(month_shares.get(band) or 0)
        if cut <= acc:
            return band
    return "storm"


async def fetch_climatology(region: str = DEFAULT_REGION, force: bool = False) -> Dict[str, Any]:
    """某个区域近 N 年日雨量 → 按月档位分布。取不到就如实报取不到。"""
    lat, lon = region_coords(region)
    cache_key = "%s,%s" % (lat, lon)
    if _CLIMATE_CACHE.get(cache_key) and not force:
        return _CLIMATE_CACHE[cache_key]
    out: Dict[str, Any] = {"ok": False, "months": {}, "reason": None}
    try:
        import httpx

        end = datetime.utcnow().date() - timedelta(days=3)
        start = end.replace(year=end.year - HISTORY_YEARS)
        url = (f"{ARCHIVE_URL}?latitude={lat}&longitude={lon}"
               f"&start_date={start.isoformat()}&end_date={end.isoformat()}"
               f"&daily=precipitation_sum&timezone={FACTORY_TZ}")
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.get(url)
        payload = resp.json() or {}
        daily = payload.get("daily") or {}
        times = daily.get("time") or []
        amounts = daily.get("precipitation_sum") or []
        series = [(ddate.fromisoformat(t), amounts[i] if i < len(amounts) else None)
                  for i, t in enumerate(times)]
        if not series:
            out["reason"] = str(payload.get("reason") or "历史气象接口没返回数据")
        else:
            agg = band_shares(series)
            out.update({
                "ok": True, **agg,
                "window": f"{start.isoformat()}~{end.isoformat()}",
                "region": region,
                "location": f"{lat},{lon}（{region_meta(region)['label']}，{FACTORY_TZ}）",
                "thresholds": {"rain_ge_mm": RAIN_MM, "storm_ge_mm": STORM_MM},
                "bands_source": f"近 {HISTORY_YEARS} 年逐日雨量实测（open-meteo 历史归档）",
            })
            _CLIMATE_CACHE[cache_key] = out
    except Exception as exc:  # 外部接口：超时/DNS/限流都算取不到
        out["reason"] = f"历史气象取不到：{type(exc).__name__}"
    return out


async def regional_climatology() -> Dict[str, Any]:
    """所有区域的按月分布：南部与北部并排放，别拿一个区域盖住另一个厂。"""
    return {key: await fetch_climatology(key) for key in REGIONS}


async def fetch_live_weather(on: ddate, region: str = DEFAULT_REGION) -> Dict[str, Any]:
    """当日/近期实况；超出预报窗口的日期直接判不可用，交给气候档。"""
    lat, lon = region_coords(region)
    today = datetime.utcnow().date()
    if on < today - timedelta(days=2) or on > today + timedelta(days=6):
        return {"ok": False, "precip_mm": None, "weather_code": None,
                "reason": "该日期超出预报接口可取范围，改用历史雨量分布"}
    key = f"{lat},{lon},{on.isoformat()}"
    if key in _LIVE_CACHE:
        return _LIVE_CACHE[key]
    out: Dict[str, Any] = {"ok": False, "precip_mm": None, "weather_code": None}
    try:
        import httpx

        day = on.isoformat()
        url = (f"{FORECAST_URL}?latitude={lat}&longitude={lon}"
               f"&daily=precipitation_sum,weather_code&timezone={FACTORY_TZ}"
               f"&start_date={day}&end_date={day}")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
        daily = (resp.json() or {}).get("daily") or {}
        precip = (daily.get("precipitation_sum") or [None])[0]
        code = (daily.get("weather_code") or [None])[0]
        if precip is None and code is None:
            out["reason"] = "气象接口没返回这一天的数据"
        else:
            out.update({"ok": True, "precip_mm": precip,
                        "weather_code": int(code) if code is not None else None})
    except Exception as exc:
        out["reason"] = f"气象接口取不到：{type(exc).__name__}"
    _LIVE_CACHE[key] = out
    return out


async def expected_attendance(db, factory_id: str, *, on: Optional[ddate] = None) -> Dict[str, Any]:
    """某一天预计多少人到岗：在册 × 天气折算率，并说清天气是哪来的。"""
    on = on or ddate.today()
    base = (await db.execute(HEADCOUNT_BASE_SQL, {"fid": factory_id})).mappings().first()
    gap = (await db.execute(ATTENDANCE_GAP_SQL, {"fid": factory_id})).mappings().first()
    roster = int(base["active_roster"] or 0) if base else 0

    region, region_source = await resolve_region(db, factory_id)
    live = await fetch_live_weather(on, region)
    climate = await fetch_climatology(region) if not live.get("ok") else {}
    month_shares = (climate.get("months") or {}).get(str(on.month)) if climate else None

    if live.get("ok"):
        condition = weather_condition(live.get("precip_mm"), live.get("weather_code"))
        weather_basis = "当日实况天气"
    elif month_shares:
        lat, lon = region_coords(region)
        condition = draw_band(month_shares, f"{lat},{lon},{on.isoformat()}")
        weather_basis = (f"{region_meta(region)['label']}近 {HISTORY_YEARS} 年逐日雨量按月分布定档"
                         f"（同日期永远同结果，仿真可重算）")
    else:
        condition = "unknown"
        weather_basis = "实况与历史雨量都没取到"

    rate = attendance_rate(condition)
    present = expected_headcount(roster, condition)
    last_real = gap["last_real_date"] if gap else None
    stale_days = (on - last_real).days if isinstance(last_real, ddate) else None

    return {
        "date": on.isoformat(),
        "roster_active": roster,
        "weather": {
            "condition": condition,
            "source": weather_basis,
            "precip_mm": live.get("precip_mm") if live.get("ok") else None,
            "weather_code": live.get("weather_code") if live.get("ok") else None,
            "month_climatology": month_shares or None,
            "live_reason": None if live.get("ok") else live.get("reason"),
            "region": region,
            "region_source": region_source,
            "location": "%s,%s（%s）" % (*region_coords(region), region_meta(region)["label"]),
            "window": climate.get("window"),
        },
        "rates_calibration": {"dry": RATE_DRY, "rain": RATE_RAIN, "storm": RATE_STORM,
                              "rain_over_mm": RAIN_MM, "storm_over_mm": STORM_MM,
                              "source": "用户口述 2026-10-06（好天97% / 雨92% / 暴雨70%）"},
        "expected_rate": rate,
        "expected_present": present,
        "expected_absent": (roster - present) if present is not None else None,
        "real_attendance": {
            "last_record_date": str(last_real) if last_real else None,
            "stale_days": stale_days,
            "note": "attendance 是现场打卡表：预计出勤只出读数，不回填这张表",
        },
        "basis": "天气折算·用户标定（不是打卡实测）" if rate else "算不出：天气依据没取到，不折算",
        "verdict": (
            f"天气没有依据 → 出勤这一维只能报在册 {roster} 人，不给折算数" if rate is None else
            f"{condition}（{weather_basis}）→ 按 {rate:.0%} 折算，在册 {roster} 人"
            f"预计到岗 {present} 人、缺 {roster - present} 人；这是估算不是打卡"
        ),
    }
