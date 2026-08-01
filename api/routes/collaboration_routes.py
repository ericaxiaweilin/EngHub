"""
岗位协同网络路由 - 跨岗位信息流+决策边界
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional, Dict, Any
from uuid import uuid4
import json

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User

router = APIRouter(prefix="/api/v1/collaboration", tags=["岗位协同网络"])


@router.get("/network")
async def get_network(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取完整协同网络（岗位+事件+边界全景）"""
    from api.services.collaboration_service import CollaborationService
    svc = CollaborationService(db)
    return await svc.get_network(factory_id)


@router.get("/event-rule")
async def query_event_rule(
    event_key: str = Query(..., description="事件标识"),
    current_user: User = Depends(get_current_user),
):
    """查询单个事件的协同规则（通知谁/谁决策/边界）"""
    from api.services.collaboration_service import CollaborationService
    svc = CollaborationService(None)
    return await svc.query_event_rule(event_key)


@router.get("/check-permission")
async def check_permission(
    role_key: str = Query(..., description="岗位标识"),
    action: str = Query(..., description="要执行的动作"),
    current_user: User = Depends(get_current_user),
):
    """检查某岗位是否有权执行某动作（边界检查）"""
    from api.services.collaboration_service import CollaborationService
    svc = CollaborationService(None)
    return await svc.check_permission(role_key, action)


@router.get("/role-boundaries")
async def get_role_boundaries(
    role_key: str = Query(..., description="岗位标识"),
    current_user: User = Depends(get_current_user),
):
    """获取某岗位的完整权限边界（能做/不能做/协同连接）"""
    from api.services.collaboration_service import CollaborationService
    svc = CollaborationService(None)
    return await svc.get_role_boundaries(role_key)


@router.post("/simulate-event")
async def simulate_event(
    factory_id: str = Query(...),
    event_key: str = Query(..., description="事件标识"),
    context: Dict[str, Any] = {},
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """模拟事件触发：展示协同流程（谁通知/谁决策/当前level下系统做什么）"""
    from api.services.collaboration_service import CollaborationService
    svc = CollaborationService(db)
    return await svc.simulate_event(factory_id, event_key, context)


@router.get("/chatbot-rules")
async def chatbot_rules(
    current_user: User = Depends(get_current_user),
):
    """给chatbot的协同规则（用于AI助手的边界判断）"""
    from api.services.collaboration_service import CollaborationService
    svc = CollaborationService(None)
    return await svc.chatbot_rules()


async def _ensure_im_schema(db: AsyncSession) -> None:
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS im_groups (
            id VARCHAR(36) PRIMARY KEY,
            factory_id VARCHAR(50),
            name VARCHAR(100) NOT NULL,
            description VARCHAR(500),
            group_type VARCHAR(30) DEFAULT 'ops',
            org_node_id VARCHAR(50),
            owner_id VARCHAR(50),
            avatar_color VARCHAR(20) DEFAULT '#1677ff',
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
    """))
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS im_messages (
            id VARCHAR(36) PRIMARY KEY,
            group_id VARCHAR(36),
            sender_id VARCHAR(50),
            sender_name VARCHAR(100),
            msg_type VARCHAR(20) DEFAULT 'text',
            content TEXT NOT NULL,
            command_type VARCHAR(50),
            command_payload JSONB DEFAULT '{}'::jsonb,
            reply_to_id VARCHAR(36),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """))


def _default_im_groups(factory_id: str, owner_id: str) -> list[dict[str, Any]]:
    suffix = factory_id[-4:].replace("_", "")
    return [
        {
            "id": f"im-{suffix}-rcc-command",
            "name": "RCC指挥调度群",
            "description": "厂长/RCC/计划/生产/设备/质量联动，承接指挥中心决策和异常升级。",
            "group_type": "rcc",
            "org_node_id": "rcc",
            "owner_id": owner_id,
            "avatar_color": "#1677ff",
        },
        {
            "id": f"im-{suffix}-prod-exception",
            "name": "生产异常处理群",
            "description": "报工异常、设备停机、物料短缺、安灯呼叫统一在 Chatbot 内闭环。",
            "group_type": "exception",
            "org_node_id": "production",
            "owner_id": owner_id,
            "avatar_color": "#fa8c16",
        },
        {
            "id": f"im-{suffix}-quality-linkage",
            "name": "质量联动群",
            "description": "IQC/IPQC/OQC/SPC/8D 质量问题拉通生产、IE 和仓储。",
            "group_type": "quality",
            "org_node_id": "quality",
            "owner_id": owner_id,
            "avatar_color": "#722ed1",
        },
    ]


async def _seed_im_groups_if_empty(db: AsyncSession, factory_id: str, owner_id: str) -> None:
    count = (await db.execute(
        text("SELECT COUNT(*)::int FROM im_groups WHERE factory_id=:fid AND is_active=true"),
        {"fid": factory_id},
    )).scalar() or 0
    if count:
        return
    for group in _default_im_groups(factory_id, owner_id):
        await db.execute(text("""
            INSERT INTO im_groups
                (id, factory_id, name, description, group_type, org_node_id, owner_id, avatar_color, is_active, created_at, updated_at)
            VALUES
                (:id, :factory_id, :name, :description, :group_type, :org_node_id, :owner_id, :avatar_color, true, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET
                name=EXCLUDED.name,
                description=EXCLUDED.description,
                group_type=EXCLUDED.group_type,
                org_node_id=EXCLUDED.org_node_id,
                owner_id=EXCLUDED.owner_id,
                avatar_color=EXCLUDED.avatar_color,
                is_active=true,
                updated_at=NOW()
        """), {**group, "factory_id": factory_id})
        await db.execute(text("""
            INSERT INTO im_messages
                (id, group_id, sender_id, sender_name, msg_type, content, command_type, command_payload, created_at)
            VALUES
                (:id, :group_id, 'system', '系统', 'system', :content, 'group_bootstrap', '{}'::jsonb, NOW() - INTERVAL '30 minutes')
            ON CONFLICT (id) DO NOTHING
        """), {
            "id": f"{group['id']}-welcome",
            "group_id": group["id"],
            "content": f"{group['name']}已建立，可在 Chatbot 内发起群协同和工单呼叫。",
        })
    await db.commit()


@router.get("/im/groups")
async def list_im_groups(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Chatbot 内网通讯群列表。"""
    await _ensure_im_schema(db)
    await _seed_im_groups_if_empty(db, factory_id, current_user.username)
    result = await db.execute(text("""
        SELECT
            g.id, g.factory_id, g.name, g.description, g.group_type,
            g.org_node_id, g.owner_id, g.avatar_color, g.is_active,
            g.created_at, g.updated_at,
            COUNT(m.id)::int AS message_count,
            MAX(m.created_at) AS last_message_at
        FROM im_groups g
        LEFT JOIN im_messages m ON m.group_id = g.id
        WHERE g.factory_id = :fid AND g.is_active = true
        GROUP BY g.id
        ORDER BY COALESCE(MAX(m.created_at), g.created_at) DESC
    """), {"fid": factory_id})
    return {"groups": [dict(row) for row in result.mappings().all()]}


@router.post("/im/groups", status_code=201)
async def create_im_group(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建 Chatbot 群。"""
    await _ensure_im_schema(db)
    factory_id = payload.get("factory_id") or getattr(current_user, "factory_id", None)
    if not factory_id:
        raise HTTPException(status_code=400, detail="factory_id required")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="群名称不能为空")
    group_id = str(uuid4())
    await db.execute(text("""
        INSERT INTO im_groups
            (id, factory_id, name, description, group_type, org_node_id, owner_id, avatar_color, is_active, created_at, updated_at)
        VALUES
            (:id, :factory_id, :name, :description, :group_type, :org_node_id, :owner_id, :avatar_color, true, NOW(), NOW())
    """), {
        "id": group_id,
        "factory_id": factory_id,
        "name": name[:100],
        "description": (payload.get("description") or "")[:500],
        "group_type": payload.get("group_type") or "custom",
        "org_node_id": payload.get("org_node_id"),
        "owner_id": current_user.username,
        "avatar_color": payload.get("avatar_color") or "#1677ff",
    })
    await db.commit()
    return {"id": group_id, "factory_id": factory_id, "name": name}


@router.get("/im/groups/{group_id}/messages")
async def list_im_messages(
    group_id: str,
    limit: int = Query(80, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """群消息列表。"""
    await _ensure_im_schema(db)
    group = (await db.execute(
        text("SELECT id FROM im_groups WHERE id=:id AND is_active=true"),
        {"id": group_id},
    )).first()
    if not group:
        raise HTTPException(status_code=404, detail="群不存在")
    result = await db.execute(text("""
        SELECT id, group_id, sender_id, sender_name, msg_type, content,
               command_type, command_payload, reply_to_id, created_at
        FROM im_messages
        WHERE group_id=:group_id
        ORDER BY created_at DESC
        LIMIT :limit
    """), {"group_id": group_id, "limit": limit})
    rows = [dict(row) for row in result.mappings().all()]
    rows.reverse()
    return {"messages": rows}


@router.post("/im/groups/{group_id}/messages", status_code=201)
async def create_im_message(
    group_id: str,
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发送群消息。"""
    await _ensure_im_schema(db)
    content = (payload.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="消息不能为空")
    group = (await db.execute(
        text("SELECT id FROM im_groups WHERE id=:id AND is_active=true"),
        {"id": group_id},
    )).first()
    if not group:
        raise HTTPException(status_code=404, detail="群不存在")
    msg_id = str(uuid4())
    sender_name = current_user.full_name or current_user.username
    await db.execute(text("""
        INSERT INTO im_messages
            (id, group_id, sender_id, sender_name, msg_type, content, command_type, command_payload, reply_to_id, created_at)
        VALUES
            (:id, :group_id, :sender_id, :sender_name, :msg_type, :content, :command_type, CAST(:command_payload AS jsonb), :reply_to_id, NOW())
    """), {
        "id": msg_id,
        "group_id": group_id,
        "sender_id": current_user.username,
        "sender_name": sender_name,
        "msg_type": payload.get("msg_type") or "text",
        "content": content,
        "command_type": payload.get("command_type"),
        "command_payload": json.dumps(payload.get("command_payload") or {}, ensure_ascii=False),
        "reply_to_id": payload.get("reply_to_id"),
    })
    await db.commit()
    return {
        "id": msg_id,
        "group_id": group_id,
        "sender_id": current_user.username,
        "sender_name": sender_name,
        "msg_type": payload.get("msg_type") or "text",
        "content": content,
    }
