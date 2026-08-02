"""
自动化等级配置服务
==================
核心理念：系统有L3全自动的能力，但给工厂选择权。
不是所有工厂都能消化全自动方案——按管理成熟度选Level。

Level定义：
- L0 纯手工：系统只记录，全部人做
- L1 辅助提醒：系统预警+建议，人决定+人执行
- L2 半自动：标准件自动执行，异常人处理
- L3 全自动：全部自动+异常自动升级（不需要人盯）

工作流列表（每条可独立配置level）：
- self_report    操作工自助报工
- auto_iqc       收货自动触发IQC
- auto_dispatch  自动派工
- auto_procure   自动采购（比价+下单）
- delivery_ctrl  交期管控（倒计时+预警）
- escalation     异常升级
- auto_report    自动报表（日报/月报）
"""
import logging
from typing import Dict, Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_logger = logging.getLogger("automation_level")

# ═══ 工作流定义（每条工作流在每个Level下的行为） ═══

WORKFLOW_DEFINITIONS = {
    "self_report": {
        "name": "操作工自助报工",
        "levels": {
            0: "操作工填纸质报工条 → 文员录入系统",
            1: "操作工扫码填报 → 系统提示异常 → 文员确认",
            2: "操作工扫码填报 → 系统自动校验+完工 → 异常通知班组长",
            3: "操作工扫码填报 → 全自动校验+完工+异常升级 → 0文员",
        },
        "default_level": 1,
    },
    "auto_iqc": {
        "name": "收货自动触发IQC",
        "levels": {
            0: "仓库收货 → 电话通知品质部 → 品质文员安排检验",
            1: "仓库收货 → 系统提醒品质部有待检 → 人安排",
            2: "仓库收货 → 自动创建IQC任务+抽样 → 检验员执行",
            3: "仓库收货 → 自动IQC+自动判定(历史数据) → 只异常才通知人",
        },
        "default_level": 1,
    },
    "auto_dispatch": {
        "name": "自动派工",
        "levels": {
            0: "调度员手动排工单到工位 → 纸质派工单",
            1: "系统推荐派工方案 → 调度员确认 → 下发",
            2: "标准工单自动派发 → 异常(插单/设备故障)人处理",
            3: "全自动派发+异常自动重排 → 0调度员",
        },
        "default_level": 1,
    },
    "auto_procure": {
        "name": "自动采购",
        "levels": {
            0: "MRP出需求 → 采购员手动比价+下单+跟催",
            1: "MRP出需求 → 系统推荐供应商 → 采购员确认下单",
            2: "标准件自动比价下单(<阈值) → 非标/大额人处理",
            3: "全自动比价+下单+跟催+评分 → 只谈判需人",
        },
        "default_level": 1,
    },
    "delivery_ctrl": {
        "name": "交期管控",
        "levels": {
            0: "跟单员手动查进度 → 手动通知客户",
            1: "系统算红黄绿灯 → 跟单员看 → 人通知",
            2: "系统自动预警+自动通知销售 → 超期自动升级",
            3: "全自动追踪+AI回客户+自动调排产 → 0跟单员",
        },
        "default_level": 1,
    },
    "escalation": {
        "name": "异常升级",
        "levels": {
            0: "异常靠人发现 → 人报告 → 人处理",
            1: "系统发现异常 → 通知当事人 → 人处理",
            2: "系统发现+分级 → 自动通知对应级别 → 超时升级",
            3: "全自动分级+升级+处理SOP推送 → 5分钟闭环",
        },
        "default_level": 2,
    },
    "auto_report": {
        "name": "自动报表",
        "levels": {
            0: "文员手动做Excel日报 → 发群",
            1: "系统生成报表草稿 → 文员确认 → 发",
            2: "系统自动生成+自动推送 → 异常才通知人",
            3: "全自动生成+推送+异常标注+趋势分析 → 0统计员",
        },
        "default_level": 2,
    },
}


class AutomationLevelService:
    """自动化等级配置管理"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_level(self, factory_id: str, workflow_key: str) -> int:
        """获取某工厂某工作流的当前自动化等级"""
        result = await self.db.execute(text("""
            SELECT automation_level FROM automation_config
            WHERE factory_id = :fid AND workflow_key = :wk
        """), {"fid": factory_id, "wk": workflow_key})
        row = result.first()
        if row:
            return row[0]
        # 未配置 → 返回默认等级
        wf = WORKFLOW_DEFINITIONS.get(workflow_key)
        return wf["default_level"] if wf else 1

    async def set_level(
        self, factory_id: str, workflow_key: str, level: int, updated_by: str = "admin"
    ) -> Dict[str, Any]:
        """设置某工厂某工作流的自动化等级"""
        if level < 0 or level > 3:
            return {"success": False, "error": "等级必须是 0-3"}

        wf = WORKFLOW_DEFINITIONS.get(workflow_key)
        if not wf:
            return {"success": False, "error": f"未知工作流: {workflow_key}"}

        # upsert
        await self.db.execute(text("""
            INSERT INTO automation_config (id, factory_id, workflow_key, workflow_name, automation_level, description, updated_by, updated_at)
            VALUES (gen_random_uuid(), :fid, :wk, :name, :level, :desc, :by, NOW())
            ON CONFLICT (factory_id, workflow_key)
            DO UPDATE SET automation_level = :level, description = :desc, updated_by = :by, updated_at = NOW()
        """), {
            "fid": factory_id, "wk": workflow_key,
            "name": wf["name"], "level": level,
            "desc": wf["levels"][level], "by": updated_by,
        })
        await self.db.commit()

        return {
            "success": True,
            "factory_id": factory_id,
            "workflow": workflow_key,
            "workflow_name": wf["name"],
            "level": level,
            "behavior": wf["levels"][level],
        }

    async def get_config(self, factory_id: str) -> Dict[str, Any]:
        """获取工厂全部工作流的自动化等级配置"""
        result = await self.db.execute(text("""
            SELECT workflow_key, automation_level, updated_at
            FROM automation_config WHERE factory_id = :fid
        """), {"fid": factory_id})
        configured = {row[0]: {"level": row[1], "updated_at": str(row[2])} for row in result.fetchall()}

        workflows = []
        total_auto = 0
        for key, wf in WORKFLOW_DEFINITIONS.items():
            cfg = configured.get(key, {})
            level = cfg.get("level", wf["default_level"])
            total_auto += level
            workflows.append({
                "key": key,
                "name": wf["name"],
                "level": level,
                "level_label": f"L{level}",
                "behavior": wf["levels"][level],
                "all_levels": wf["levels"],
                "configured": key in configured,
            })

        max_total = len(WORKFLOW_DEFINITIONS) * 3
        maturity_pct = round(total_auto / max_total * 100, 1) if max_total else 0

        # 成熟度评级
        if maturity_pct >= 80:
            maturity = "🟢 高度自动化（接近无人化）"
        elif maturity_pct >= 50:
            maturity = "🟡 中度自动化（标准自动+异常人处理）"
        elif maturity_pct >= 25:
            maturity = "🟠 初级自动化（系统辅助为主）"
        else:
            maturity = "🔴 手工为主（系统仅记录）"

        return {
            "factory_id": factory_id,
            "maturity_score": maturity_pct,
            "maturity_label": maturity,
            "total_workflows": len(WORKFLOW_DEFINITIONS),
            "avg_level": round(total_auto / len(WORKFLOW_DEFINITIONS), 1),
            "workflows": workflows,
            "recommendation": self._recommend(workflows),
        }

    async def batch_set_level(
        self, factory_id: str, level: int, updated_by: str = "admin"
    ) -> Dict[str, Any]:
        """一键设置全厂所有工作流到同一等级（快速切换）"""
        if level < 0 or level > 3:
            return {"success": False, "error": "等级必须是 0-3"}

        results = []
        for key, wf in WORKFLOW_DEFINITIONS.items():
            r = await self.set_level(factory_id, key, level, updated_by)
            results.append(r)

        return {
            "success": True,
            "factory_id": factory_id,
            "level": level,
            "level_label": f"L{level}",
            "description": f"全厂切换到 L{level}",
            "workflows_updated": len(results),
            "behaviors": {r["workflow_name"]: r["behavior"] for r in results if r.get("success")},
        }

    async def simulate_switch(
        self, factory_id: str, workflow_key: str, target_level: int
    ) -> Dict[str, Any]:
        """模拟切换等级：展示切换前后的行为差异（不实际修改）"""
        wf = WORKFLOW_DEFINITIONS.get(workflow_key)
        if not wf:
            return {"error": f"未知工作流: {workflow_key}"}

        current = await self.get_level(factory_id, workflow_key)

        return {
            "workflow": workflow_key,
            "workflow_name": wf["name"],
            "current_level": current,
            "current_behavior": wf["levels"][current],
            "target_level": target_level,
            "target_behavior": wf["levels"][target_level],
            "impact": self._assess_impact(workflow_key, current, target_level),
        }

    def _assess_impact(self, workflow_key: str, from_level: int, to_level: int) -> Dict[str, Any]:
        """评估等级切换的影响"""
        if to_level > from_level:
            direction = "升级（减少人工）"
            if to_level >= 3:
                risk = "需确保异常升级通道畅通，建议先跑1周L2再升L3"
            elif to_level >= 2:
                risk = "低风险，标准流程自动，异常仍有人处理"
            else:
                risk = "无风险，仅增加提醒"
        elif to_level < from_level:
            direction = "降级（增加人工）"
            risk = "无风险，随时可降回"
        else:
            direction = "不变"
            risk = "无"

        # 省人估算
        headcount_saved = {
            "self_report": {2: 1, 3: 2},
            "auto_iqc": {2: 0.5, 3: 1},
            "auto_dispatch": {2: 0.5, 3: 1},
            "auto_procure": {2: 1, 3: 2},
            "delivery_ctrl": {2: 1, 3: 2},
            "escalation": {2: 0, 3: 0.5},
            "auto_report": {2: 1, 3: 2},
        }
        saved = headcount_saved.get(workflow_key, {}).get(to_level, 0)

        return {
            "direction": direction,
            "risk": risk,
            "estimated_headcount_saved": saved,
            "prerequisite": self._prerequisite(workflow_key, to_level),
        }

    def _prerequisite(self, workflow_key: str, level: int) -> str:
        """升级前置条件"""
        prereqs = {
            ("self_report", 2): "需确保操作工有扫码终端（手机/PDA）",
            ("self_report", 3): "需运行L2稳定2周+异常升级通道已验证",
            ("auto_iqc", 2): "需IQC检验员在岗（系统只创建任务，量测仍需人）",
            ("auto_iqc", 3): "需有≥3个月历史检验数据支撑自动判定",
            ("auto_dispatch", 2): "需工位+设备数据完整，工单有优先级",
            ("auto_dispatch", 3): "需运行L2稳定+设备故障自动重排已验证",
            ("auto_procure", 2): "需供应商价格表完整+审批阈值已设定",
            ("auto_procure", 3): "需运行L2稳定+供应商评分体系已建立",
            ("delivery_ctrl", 2): "需订单交期数据完整",
            ("delivery_ctrl", 3): "需AI客服对接客户通知渠道",
            ("escalation", 3): "需各级主管联系方式+值班表已配置",
            ("auto_report", 2): "需报工数据实时（依赖self_report≥L2）",
            ("auto_report", 3): "需所有数据源实时+推送通道已配置",
        }
        return prereqs.get((workflow_key, level), "无特殊前置条件")

    def _recommend(self, workflows: List[Dict]) -> str:
        """根据当前配置给出升级建议"""
        low = [w for w in workflows if w["level"] <= 1]
        if not low:
            return "当前配置较成熟，可考虑逐步升级到L3"

        # 找最容易升级的
        easy_upgrades = []
        for w in low:
            if w["key"] in ("auto_report", "escalation", "delivery_ctrl"):
                easy_upgrades.append(w["name"])

        if easy_upgrades:
            return f"建议优先升级: {', '.join(easy_upgrades)}（风险低、见效快）"
        return f"建议从 {low[0]['name']} 开始升级到L2"
