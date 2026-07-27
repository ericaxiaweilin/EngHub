"""
API Routes
"""

from .mes_routes import router as mes_router
from .ie_routes import router as ie_router
from .ie_routes_extended import router as ie_advanced_router
from .pp_routes import router as pp_router
from .qms_routes import router as qms_router
from .wms_routes import router as wms_router
from .auth_routes import router as auth_router
from .sim_erp_routes import router as sim_erp_router
from .sim_factory_routes import router as sim_factory_router
from .chat_routes import router as chat_router
from .tms_routes import router as tms_router
from .code_table_routes import router as code_table_router
from .aps_routes import router as aps_router

try:
    from .employee_skill_router import router as employee_skill_router
except ImportError:
    employee_skill_router = None

__all__ = [
    "mes_router",
    "ie_router",
    "ie_advanced_router",
    "pp_router",
    "qms_router",
    "wms_router",
    "auth_router",
    "employee_skill_router",
    "sim_erp_router",
    "sim_factory_router",
    "chat_router",
    "tms_router",
    "code_table_router",
    "aps_router",
]
