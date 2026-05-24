"""
MES 生产数据搜索引擎配置
"""
from typing import List, Optional


class SearchEngineConfig:
    """搜索引擎配置"""
    
    # 搜索引擎基础路径
    base_path: str = "/workspace/data/search_index"
    
    # 索引配置
    index_chunk_size: int = 500  # 文本分块大小
    index_overlap: int = 50      # 分块重叠大小
    
    # 搜索配置
    default_top_k: int = 10      # 默认返回结果数
    min_score_threshold: float = 0.3  # 最小相似度阈值
    
    # 数据源配置
    database_url: Optional[str] = None  # 数据库连接 URL
    
    # 缓存配置
    cache_enabled: bool = True
    cache_ttl: int = 300  # 缓存过期时间 (秒)
    
    # 支持的搜索类型
    supported_types: List[str] = [
        "work_order",      # 工单
        "station",         # 工位
        "device",          # 设备
        "material",        # 物料
        "quality",         # 质量
        "inventory",       # 库存
        "production",      # 生产记录
        "defect",          # 缺陷
        "sop",            # 作业指导书
        "all"             # 全局搜索
    ]
