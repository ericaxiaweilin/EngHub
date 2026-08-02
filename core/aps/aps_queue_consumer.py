"""
APS 队列消费者服务 - #11 PS事件解耦的消费者端

负责轮询 APS调度请求队列表，执行业务排程并更新请求状态。
此服务应作为后台守护进程或定时任务（cron/schedule）持续运行。

依赖项：
- SQLAlchemy AsyncSession
- api.services.aps_service.ApsService
- database.models.APSRequest, ApsSchedule

使用方式：
    python -c "from core.aps.aps_queue_consumer import run_consumer; run_consumer()"
    
或在 cron 中定期调用：
    */5 * * * * cd /path/to/enghub && python -c "from core.aps.aps_queue_consumer import run_consumer; run_consumer()"
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import db_config
from database.models import APSRequest
from api.services.aps_service import ApsService

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
)
logger = logging.getLogger(__name__)

# 配置参数
POLL_INTERVAL_SECONDS = 10  # 轮询间隔（秒）


async def get_session() -> AsyncSession:
    """获取数据库会话"""
    return db_config.session_factory()


async def process_request(db: AsyncSession, request: APSRequest) -> bool:
    """
    处理单个 APS 调度请求
    
    Args:
        db: 数据库会话
        request: APSRequest 对象
        
    Returns:
        True if success, False if failed
    """
    try:
        logger.info(f"开始处理请求 {request.id} for factory={request.factory_id}")
        
        # 更新请求状态为处理中
        request.status = 'in_progress'
        request.updated_at = datetime.utcnow()
        await db.commit()
        
        # 创建 APS 服务并执行排程
        # 注意：ApsService 需要传入自己的 session，这里复用当前 session
        aps_service = ApsService(db)
        schedule_result = await aps_service.generate_schedule(
            factory_id=request.factory_id,
            mode=request.mode,
            horizon_days=request.horizon_days,
            optimize_for=request.optimize_for,
            updated_by=f"queue_consumer_{request.id}"
        )
        
        logger.info(f"排程完成 {request.id}, 生成方案: {schedule_result.get('schedule_code', 'unknown')}")
        
        # 更新请求为已完成
        request.status = 'completed'
        request.completed_at = datetime.utcnow()
        request.error_message = None
        await db.commit()
        
        return True
        
    except Exception as e:
        logger.error(f"处理请求 {request.id} 失败: {e}")
        # 记录错误信息
        request.retry_count += 1
        request.updated_at = datetime.utcnow()
        
        if request.retry_count >= request.max_retries:
            # 超过最大重试次数，标记为失败
            request.status = 'failed'
            request.error_message = str(e)
            logger.warning(f"请求 {request.id} 已达到最大重试次数，标记为失败")
        else:
            # 保持 pending 以便下次重试
            request.status = 'pending'
        
        await db.commit()
        return False


async def consume_pending_requests(db: AsyncSession, limit: int = 50) -> int:
    """
    从队列表获取 pending 状态的请求并处理
    
    Args:
        db: 数据库会话
        limit: 一次处理的请求最大数量
        
    Returns:
        已处理的请求数量
    """
    # 获取待处理请求（简单查询，实际生产建议用 FOR UPDATE SKIP LOCKED 防止并发重复）
    stmt = select(APSRequest).where(
        APSRequest.status == 'pending'
    ).order_by(APSRequest.created_at.asc()).limit(limit)
    
    result = await db.execute(stmt)
    requests = result.scalars().all()
    
    logger.info(f"发现 {len(requests)} 个待处理请求")
    
    successful = 0
    for req in requests:
        try:
            if await process_request(db, req):
                successful += 1
        except Exception as e:
            logger.error(f"处理请求 {req.id} 时发生异常: {e}")
            # 确保请求被回滚到 pending 或 failed 状态
            req.retry_count += 1
            req.status = 'failed'
            req.error_message = str(e)
            await db.commit()
    
    return successful


async def run_consumer(persistent: bool = True, interval: int = POLL_INTERVAL_SECONDS):
    """
    运行 APS 队列消费者
    
    Args:
        persistent: 如果为 True，则持续轮询；如果为 False，则只处理一轮后立即退出
        interval: 轮询间隔时间（秒，仅在持久模式下生效）
    """
    session = None
    try:
        session = db_config.session_factory()
        
        if persistent:
            logger.info("APS 队列消费者已启动（持久模式，轮询间隔 = {}秒）".format(interval))
            while True:
                try:
                    count = await consume_pending_requests(session, limit=50)
                    if count > 0:
                        logger.info(f"本轮处理了 {count} 个请求")
                    else:
                        # 空轮询时稍作等待以减轻数据库压力
                        await asyncio.sleep(interval)
                except Exception as e:
                    logger.error(f"消费者轮询出错: {e}")
                    await asyncio.sleep(interval)
        else:
            # 一次性模式（用于 cron 任务等触发式调用）
            count = await consume_pending_requests(session, limit=100)
            logger.info(f"一次性处理完成: {count} 个请求")
            
    finally:
        if session:
            await session.close()
            logger.info("数据库会话已关闭")


# =============================================================================
# 脚本入口点
# =============================================================================
if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='APS 队列消费者服务')
    parser.add_argument('--persistent', '-p', action='store_true',
                        help='持久运行模式（默认仅执行单次）')
    parser.add_argument('--interval', '-i', type=int, default=POLL_INTERVAL_SECONDS,
                        help='轮询间隔时间（秒，仅在持久模式下生效）')
    args = parser.parse_args()
    
    if args.persistent:
        logger.info("启动持久化 APS 队列消费者...")
        run_consumer(persistent=True, interval=args.interval)
    else:
        logger.info("执行一次性 APS 队列消费...")
        # 同步运行异步函数
        asyncio.run(run_consumer(persistent=False))
