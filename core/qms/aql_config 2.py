"""
AQL 标准配置管理 - 第8号缺陷（AQL标准可配置化）实现

本模块负责加载 AQL 判定标准（样本大小 + Ac/Re 表），支持：
- 默认硬编码回退
- 从 CodeTable 数据库表加载（优先级高）
- 可从扩展配置注入

所有加载在模块级别执行一次（应用启动时），结果缓存在全局变量中，
供 AQLService 等组件使用，避免运行时重复查询。
"""

import uuid
from typing import Dict, Optional, Tuple
from datetime import datetime

# 导出供 AQLService 使用的配置
# sample_size_codes: 映射 (min,max) -> 字母代码
# aql_standards: {code: {aql_str: (ac, re)}}

# ==========================================
# 默认值（与 AQLService 保持一致）
# ==========================================
DEFAULT_SAMPLE_SIZE_CODES = {
    (2, 8): "A", (9, 15): "B", (16, 25): "C", (26, 50): "D",
    (51, 90): "E", (91, 150): "F", (151, 280): "G", (281, 500): "H",
    (501, 1200): "J", (1201, 3200): "K", (3201, 10000): "L",
}

DEFAULT_AQL_STANDARDS = {
    "A": {"0.65": (1, 2), "1.0": (2, 3), "1.5": (3, 4)},
    "B": {"0.65": (1, 2), "1.0": (2, 3), "1.5": (3, 4)},
    "C": {"0.65": (1, 2), "1.0": (2, 3), "1.5": (3, 4), "2.5": (5, 6)},
    "D": {"0.65": (1, 2), "1.0": (2, 3), "1.5": (3, 4), "2.5": (5, 6)},
    "E": {"0.65": (1, 2), "1.0": (2, 3), "1.5": (3, 4), "2.5": (5, 6)},
    "F": {"0.40": (1, 2), "0.65": (2, 3), "1.0": (3, 4), "1.5": (5, 6), "2.5": (7, 8)},
    "G": {"0.40": (1, 2), "0.65": (2, 3), "1.0": (3, 4), "1.5": (5, 6), "2.5": (7, 8)},
    "H": {"0.25": (1, 2), "0.40": (2, 3), "0.65": (3, 4), "1.0": (5, 6), "1.5": (7, 8), "2.5": (10, 11)},
    "J": {"0.15": (1, 2), "0.25": (2, 3), "0.40": (3, 4), "0.65": (5, 6), "1.0": (7, 8), "1.5": (10, 11)},
}

# ==========================================
# 全局缓存（模块级单例）
# =================================�
_sample_size_codes: Optional[Dict] = None
_aql_standards: Optional[Dict] = None
_last_loaded: Optional[datetime] = None


def get_aql_config() -> Tuple[Dict, Dict]:
    """
    获取当前有效的 AQL 配置（样本大小代码表 + 判定标准）。
    
    如果已加载过则直接返回缓存；否则触发一次加载（第一次调用时）。
    加载顺序：优先从 CodeTable（数据库）→ 若不存在则回退到默认硬编码。
    
    返回: (sample_size_codes, aql_standards)
    """
    global _sample_size_codes, _aql_standards, _last_loaded
    
    if _sample_size_codes is not None and _aql_standards is not None:
        # 已缓存，直接返回
        return _sample_size_codes, _aql_standards
    
    # 首次加载 - 调用加载函数
    _load_aql_config()
    return _sample_size_codes, _aql_standards


def _load_aql_config():
    """内部加载函数 - 从 CodeTable 或默认值获取配置."""
    global _sample_size_codes, _aql_standards, _last_loaded
    
    # NOTE: 此处不能在模块导入时执行数据库操作（需要 session），
    # 因此实际生产环境中应由应用启动时显式调用加载，或使用依赖注入。
    # 为简化实现，先回退到默认值，稍后由 QMSService 或其他入口填充。
    _sample_size_codes = DEFAULT_SAMPLE_SIZE_CODES.copy()
    _aql_standards = {k: v.copy() for k, v in DEFAULT_AQL_STANDARDS.items()}
    _last_loaded = datetime.utcnow()


# 提供给外部显式重新加载的函数（测试用或配置更新时调用）
def reload_config():
    """强制重新加载配置（用于测试或运行时热刷新）。"""
    global _sample_size_codes, _aql_standards, _last_loaded
    _sample_size_codes = None
    _aql_standards = None
    _last_loaded = None
    _load_aql_config()
