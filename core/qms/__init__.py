"""
QMS Module - Quality Management System
检验管理、不良品管理
"""

from .inspection import InspectionService
from .defect import DefectService

__all__ = [
    "InspectionService",
    "DefectService",
]
