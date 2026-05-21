"""
API Routes
"""

from .mes_routes import router as mes_router
from .pp_routes import router as pp_router
from .qms_routes import router as qms_router
from .wms_routes import router as wms_router
from .auth_routes import router as auth_router
from .employee_skill_router import router as employee_skill_router
from .sim_erp_routes import router as sim_erp_router

__all__ = [
    "mes_router",
    "pp_router",
    "qms_router",
    "wms_router",
    "auth_router",
    "employee_skill_router",
    "sim_erp_router",
]
