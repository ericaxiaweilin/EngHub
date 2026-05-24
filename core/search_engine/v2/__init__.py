"""
MES 企业级统一搜索模块 v2
对标 Atlassian Rovo 的站内数据搜索引擎
"""

from .models import (
    SearchEntityType,
    SearchDocument,
    SearchQuery,
    SearchHit,
    SearchResponse,
    SearchAction,
    SearchResultLink,
    RelatedContext,
    IndexOperation,
    ROUTE_MAPPING,
    PERMISSION_MAPPING,
)

from .engine import (
    UnifiedSearchEngine,
    ChineseTokenizer,
    InvertedIndex,
    BM25Scorer,
    get_search_engine,
    reset_search_engine,
)

from .data_loader import (
    BusinessDataLoader,
    get_data_loader,
)

__all__ = [
    # Models
    "SearchEntityType",
    "SearchDocument",
    "SearchQuery",
    "SearchHit",
    "SearchResponse",
    "SearchAction",
    "SearchResultLink",
    "RelatedContext",
    "IndexOperation",
    "ROUTE_MAPPING",
    "PERMISSION_MAPPING",
    # Engine
    "UnifiedSearchEngine",
    "ChineseTokenizer",
    "InvertedIndex",
    "BM25Scorer",
    "get_search_engine",
    "reset_search_engine",
    # Data Loader
    "BusinessDataLoader",
    "get_data_loader",
]

__version__ = "2.0.0"
__description__ = "MES 企业级统一搜索引擎 (Rovo-style)"
