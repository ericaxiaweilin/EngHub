"""
PP Module - Production Planning
Master Production Schedule (MPS), Material Requirements Planning (MRP)
"""

from .plan import MPSService

# 这里原来还导出 MRPService：那个类不接数据库，BOM/库存/物料主档/供应商
# 全是 _init_sample_data() 里硬编码的 PRODUCT-A/B 演示数据，而线上 MRP 端点
# 一行都没用它（自己查真表）。留着只会让人以为 MRP 需求是从它算出来的 —— 
# 真实实现见 api/services/bom_source.py + api/routes/pp_routes.py 的 /mrp/calculate。
__all__ = [
    "MPSService",
]
