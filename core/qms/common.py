"""QMS公共枚举和常量 - 供inspection和defect模块共享"""

from enum import Enum


class InspectionType(str, Enum):
    """检验类型"""
    IQC = "iqc"         # 来料检验
    IPQC = "ipqc"       # 过程检验
    FQC = "fqc"         # 最终检验
    OQC = "oqc"         # 出货检验


class InspectionStatus(str, Enum):
    """检验状态"""
    PENDING = "pending"       # 待检验
    IN_PROGRESS = "in_progress"  # 检验中
    PASSED = "passed"         # 合格
    FAILED = "failed"         # 不合格
    REJECTED = "rejected"     # 拒收


class AQLLevel(str, Enum):
    """AQL检验水平"""
    GENERAL_I = "general_i"
    GENERAL_II = "general_ii"
    GENERAL_III = "general_iii"
    SPECIAL_S1 = "special_s1"
    SPECIAL_S2 = "special_s2"


# Defect-related enums (moved from defect.py to avoid circular import)
class DefectStatus(str, Enum):
    """缺陷状态"""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class DefectType(str, Enum):
    """缺陷类型"""
    APPEARANCE = "appearance"
    DIMENSION = "dimension"
    FUNCTION = "function"
    PERFORMANCE = "performance"
    MATERIAL = "material"
    PROCESS = "process"
    OTHER = "other"


class Severity(str, Enum):
    """严重等级"""
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    OBSERVATION = "observation"


class DispositionType(str, Enum):
    """处置方式"""
    REWORK = "rework"
    REPAIR = "repair"
    SCRAP = "scrap"
    CONCESSION = "concession"
    RETURN = "return"


class OcapStatus(str, Enum):
    """OCAP状态"""
    PENDING = "pending"
    TRIGGERED = "triggered"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"