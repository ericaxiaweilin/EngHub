"""
MES 生产数据搜索引擎模块
提供全文搜索、模糊匹配、多条件过滤功能
"""
from .config import SearchEngineConfig
from .engine import MESSearchEngine, SearchResult, SearchIndex

__all__ = [
    "SearchEngineConfig",
    "MESSearchEngine",
    "SearchResult",
    "SearchIndex"
]

# 默认搜索引擎实例
_default_engine: MESSearchEngine = None


def get_search_engine() -> MESSearchEngine:
    """获取默认搜索引擎实例"""
    global _default_engine
    if _default_engine is None:
        _default_engine = MESSearchEngine()
    return _default_engine


def initialize_search_engine(config: SearchEngineConfig = None) -> MESSearchEngine:
    """初始化搜索引擎"""
    global _default_engine
    _default_engine = MESSearchEngine(config)
    return _default_engine
