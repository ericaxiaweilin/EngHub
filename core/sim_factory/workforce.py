"""
工人生成模块
============

按工段 ``单班人数 × 班次`` 确定性生成仿真花名册（姓名 / 工种 / 技能 / 班次 / 出勤），
并计算工段级人力统计（平均技能、平均出勤、人力利用率）。

- 生成只依赖 ``seed + section_id``，相同参数下结果可复现；
- 人力利用率 = 工段总负荷工时 / (在岗总人数 × 每班工时 × 计划期工作日数)，
  与产能负荷模型挂钩，>1 表示需要加班才能消化。
"""

from __future__ import annotations

import random
from typing import Callable, Dict, List

from .models import FactorySimConfig, SectionWorkforce, WorkerDef

# 常见中文姓氏池
_SURNAMES = (
    "王李张刘陈杨赵黄周吴徐孙胡朱高林何郭马罗梁宋郑谢韩唐冯于董萧程曹袁邓许傅沈曾彭吕苏卢蒋蔡贾丁魏薛叶阎余潘杜戴夏钟汪田任姜范方石姚谭廖邹熊金陆郝孔白崔康毛邱秦江史顾侯邵孟龙万段雷钱汤尹黎易常武乔贺赖龚文"
)

# 常见中文名字池（单字，与姓氏拼成两字名）
_GIVEN = (
    "伟芳娜敏静丽强磊军洋勇艳杰娟涛明超霞平刚辉华玲飞丹萍峰鑫鹏博浩宇轩志强海涛晓雪梅婷玉春志明建国建华秀兰桂英文海燕"
)

# 技能等级加权池（偏向 3~4 级熟练工，符合真实工厂分布）
_SKILL_POOL = [1, 2, 3, 3, 3, 4, 4, 4, 4, 5]


def _infer_role(section_name: str) -> str:
    """工段名 → 工种名兜底（场景未显式配置 role_name 时使用）。"""
    return f"{section_name}操作工"


def generate_workforce(
    config: FactorySimConfig,
    load: Dict[str, List[float]],
    is_workday: Callable[[str, int], bool],
    horizon: int,
) -> List[SectionWorkforce]:
    """为每个工段生成花名册与人力统计。

    - 工段携带 ``real_workers``（来自 HR 花名册）时，映射真实员工（姓名/技能/班次/
      性别/身高体重），技能等级与出勤来自真实档案；
    - 否则按 ``seed + section_id`` 确定性合成（姓名/技能/出勤随机但可复现）。

    :param config: 仿真配置
    :param load: 工段 × 日 负荷工时矩阵（含波动后的最终负荷）
    :param is_workday: (workshop_id, day) -> 是否工作日
    :param horizon: 计划期天数
    """
    workforce: List[SectionWorkforce] = []
    for s in config.sections:
        role = s.role_name or _infer_role(s.name)
        workers: List[WorkerDef] = []
        shift_headcount: Dict[int, int] = {}
        skill_sum = 0
        att_sum = 0.0

        if s.real_workers:
            # ── 真实花名册：映射 HR 员工 ──
            headcount = len(s.real_workers)
            for i, rw in enumerate(s.real_workers):
                shift = rw.shift if 1 <= rw.shift <= max(s.shifts_per_day, 1) else 1
                shift_headcount[shift] = shift_headcount.get(shift, 0) + 1
                attendance = rw.attendance_rate if rw.attendance_rate is not None else 0.95
                workers.append(WorkerDef(
                    worker_id=f"{s.section_id}-RW{str(i + 1).zfill(3)}",
                    name=rw.name,
                    section_id=s.section_id,
                    section_name=s.name,
                    role=rw.role or role,
                    skill_level=rw.skill_level,
                    shift=shift,
                    attendance_rate=attendance,
                    gender=rw.gender,
                    height_cm=rw.height_cm,
                    weight_kg=rw.weight_kg,
                ))
                skill_sum += rw.skill_level
                att_sum += attendance
        else:
            # ── 合成花名册：确定性随机 ──
            headcount = s.workers * s.shifts_per_day
            rng = random.Random(f"{config.seed}-{s.section_id}")
            for i in range(headcount):
                shift = (i % s.shifts_per_day) + 1
                shift_headcount[shift] = shift_headcount.get(shift, 0) + 1
                name = rng.choice(_SURNAMES) + rng.choice(_GIVEN)
                skill = rng.choice(_SKILL_POOL)
                attendance = round(rng.uniform(0.88, 0.99), 3)
                workers.append(WorkerDef(
                    worker_id=f"{s.section_id}-W{str(i + 1).zfill(3)}",
                    name=name,
                    section_id=s.section_id,
                    section_name=s.name,
                    role=role,
                    skill_level=skill,
                    shift=shift,
                    attendance_rate=attendance,
                ))
                skill_sum += skill
                att_sum += attendance

        workdays = sum(1 for d in range(horizon) if is_workday(s.workshop_id, d))
        available_hours = headcount * s.hours_per_shift * max(workdays, 1)
        total_load = sum(load.get(s.section_id, []))
        utilization = total_load / available_hours if available_hours > 0 else 0.0

        workforce.append(SectionWorkforce(
            section_id=s.section_id,
            name=s.name,
            headcount=headcount,
            per_shift=s.workers,
            shift_headcount=shift_headcount,
            avg_skill=round(skill_sum / headcount, 2) if headcount else 0.0,
            avg_attendance=round(att_sum / headcount, 3) if headcount else 0.0,
            labor_utilization=round(utilization, 3),
            workers=workers,
        ))
    return workforce
