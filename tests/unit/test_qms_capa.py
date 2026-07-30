"""tests/unit/test_qms_capa.py - EP881 单元测试范例

Module: core.qms.capa_service
Coverage target: >= 85% (per EP881 Section 9)

Working unit tests for CAPAService following AAA pattern.
Run: pytest tests/unit/test_qms_capa.py -v
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from core.qms.capa_service import (
    CAPAService, CAPAStatus, CAPASeverity, FishboneDimension, EIGHTD_STEP, CAPACase
)


# FIXTURES ==========================================================

@pytest.fixture()
def capa_service():
    """CAPAService instance fixture"""
    return CAPAService()


# Test Class: CAPA Service Core Functionality ========================

class TestCAPACreateCorrectiveAction:
    """CAPA - Create Case Tests"""

    def test_create_case_success(self, capa_service):
        """Create a new CAPA case successfully"""
        case = capa_service.create_case(title="Test Issue", severity=CAPASeverity.MAJOR)

        assert isinstance(case, CAPACase)
        assert case.title == "Test Issue"
        assert case.severity == CAPASeverity.MAJOR
        assert case.status == CAPAStatus.OPEN
        assert case.case_number.startswith("CAPA-")

    def test_create_case_with_minimal_severity(self, capa_service):
        """Test creating with MINOR severity"""
        case = capa_service.create_case(title="Minor Issue", severity=CAPASeverity.MINOR)
        assert case.severity == CAPASeverity.MINOR


# Test Class: Root Cause Analysis ====================================

class TestCAPARootCauseAnalysis:
    """CAPA - Root Cause Analysis Tests"""

    def test_add_why_step(self, capa_service):
        """Add 5Why step to a case"""
        case = capa_service.create_case(title="Test", severity=CAPASeverity.MINOR)

        # Add why steps
        case.add_why_step(step_num=1, why_question="Why did it happen?", answer="Because of X")
        case.add_why_step(step_num=2, why_question="Why X?", answer="Y")

        # Get analysis
        analysis = case.get_why_analysis()
        # analysis contains 'whys' key plus other metadata, check the whys count
        assert len(analysis.get("whys", {})) == 2
        assert analysis["whys"]["why1"]["question"] == "Why did it happen?"
        assert analysis["whys"]["why2"]["answer"] == "Y"

    def test_set_root_cause(self, capa_service):
        """Set root cause on a case"""
        case = capa_service.create_case(title="Test", severity=CAPASeverity.MINOR)
        case.set_root_cause("Tool wear and tear")
        assert case.root_cause == "Tool wear and tear"

    def test_add_fishbone_item(self, capa_service):
        """Add fishbone dimension item"""
        case = capa_service.create_case(title="Test", severity=CAPASeverity.MINOR)
        case.add_fishbone_item(
            dimension=FishboneDimension.MACHINE,
            item="Equipment calibration drift"
        )
        summary = case.get_fishbone_summary()
        assert "Equipment calibration drift" in summary[FishboneDimension.MACHINE]


# Test Class: Track and Status Management ============================

class TestCAPATrackAndStatus:
    """CAPA - Tracking and Status Management Tests"""

    def test_get_case(self, capa_service):
        """Retrieve case by ID"""
        case = capa_service.create_case(title="Test Case", severity=CAPASeverity.MINOR)
        retrieved = capa_service.get_case(case.id)
        assert retrieved is not None
        assert retrieved.title == "Test Case"

    def test_get_case_nonexistent(self, capa_service):
        """Get non-existent case returns None"""
        assert capa_service.get_case("FAKE-ID-123") is None

    def test_list_cases(self, capa_service):
        """List all cases"""
        capa_service.create_case(title="Case 1", severity=CAPASeverity.MINOR)
        capa_service.create_case(title="Case 2", severity=CAPASeverity.MAJOR)

        cases = capa_service.list_cases()
        assert len(cases) == 2
        titles = [c.title for c in cases]
        assert "Case 1" in titles
        assert "Case 2" in titles

    def test_list_cases_by_status(self, capa_service):
        """Filter cases by status"""
        case1 = capa_service.create_case(title="Open", severity=CAPASeverity.MINOR)
        case2 = capa_service.create_case(title="Closed", severity=CAPASeverity.MAJOR)
        
        # Update second case status
        case2.status = CAPAStatus.CLOSED
        
        open_cases = capa_service.list_cases(status=CAPAStatus.OPEN)
        assert len(open_cases) == 1
        assert open_cases[0].title == "Open"


# Test Class: Corrective Actions Plan ================================

class TestCAPACorrectiveActions:
    """CAPA - Corrective Action Plans"""

    def test_add_corrective_action_plan(self, capa_service):
        """Add corrective action plan to a case"""
        case = capa_service.create_case(title="Test", severity=CAPASeverity.MINOR)

        action = case.add_corrective_action_plan(
            action_desc="Inspect all products from batch",
            owner="QCO-001",
            deadline="2026-08-01"
        )

        assert len(case.corrective_action_plans) == 1
        assert action["description"] == "Inspect all products from batch"
        assert action["owner"] == "QCO-001"
        assert action["deadline"] == "2026-08-01"
        assert action["status"] == "planned"

    def update_action_plan_status(self, capa_service):
        """Update corrective action plan status"""
        case = capa_service.create_case(title="Test", severity=CAPASeverity.MINOR)
        action = case.add_corrective_action_plan(
            action_desc="Do something", owner="user1", deadline="2026-08-01"
        )

        # Update status
        updated = case.update_action_plan_status(
            plan_id=action["id"], status="in_progress", completion_pct=50
        )
        assert updated is True
        assert action["status"] == "in_progress"
        assert action["completion_pct"] == 50


# Test Class: Verification & Closing ================================

class TestCAPAVerification:
    """CAPA - Verification and Closing"""

    def test_verification_steps(self, capa_service):
        """Test verification process on a case"""
        case = capa_service.create_case(title="Test", severity=CAPASeverity.MINOR)

        # Set pre-verification metrics
        case.set_verification_before(metrics={"defect_rate": 5.2})

        # Set post-verification metrics (improved)
        case.set_verification_after(
            metrics={"defect_rate": 0.8},
            improved=True,
            verified_by="QCO-005"
        )

        # Check verification status
        status = case.get_verification_status()
        assert status == "verified"

    def test_mark_all_plans_completed(self, capa_service):
        """Mark all corrective actions as completed"""
        case = capa_service.create_case(title="Test", severity=CAPASeverity.MINOR)
        case.add_corrective_action_plan(action_desc="Plan 1", owner="u1", deadline="2026-08-01")
        case.add_corrective_action_plan(action_desc="Plan 2", owner="u2", deadline="2026-08-01")

        case.mark_all_plans_completed()
        for plan in case.corrective_action_plans:
            assert plan["status"] == "completed"


# Test Class: 8D Process =============================================

class TestCAPAEightDProcess:
    """CAPA - 8D Process Steps"""

    def test_update_8d_step_status(self, capa_service):
        """Update 8D step status"""
        case = capa_service.create_case(title="Test", severity=CAPASeverity.MINOR)

        # Update multiple steps
        case.update_step_status(
            step=EIGHTD_STEP.D1_TEAM,
            status="in_progress",
            completed_at=None
        )
        case.update_step_status(
            step=EIGHTD_STEP.D2_DESCRIBE,
            status="completed"
        )

        # Verify step statuses
        d1_status = case.step_status[EIGHTD_STEP.D1_TEAM]
        d2_status = case.step_status[EIGHTD_STEP.D2_DESCRIBE]
        
        assert d1_status == "in_progress"
        assert d2_status == "completed"


# Utility Tests =====================================================

def test_CAPA_STATUS_ENUM_VALUES():
    """CAPAStatus enum has expected values"""
    assert CAPAStatus.OPEN.value == "open"
    assert CAPAStatus.IN_PROGRESS.value == "in_progress"
    assert CAPAStatus.VERIFIED.value == "verified"
    assert CAPAStatus.CLOSED.value == "closed"

def test_CAPA_SEVERITY_ENUM_VALUES():
    """CAPASeverity enum has expected values"""
    assert CAPASeverity.CRITICAL.value == "critical"
    assert CAPASeverity.MAJOR.value == "major"
    assert CAPASeverity.MINOR.value == "minor"

def test_capa_service_instance_isolation():
    """Multiple service instances are independent"""
    service1 = CAPAService()
    service2 = CAPAService()

    case1 = service1.create_case(title="Case 1", severity=CAPASeverity.MINOR)
    case2 = service2.create_case(title="Case 2", severity=CAPASeverity.MINOR)

    assert len(service1._cases) == 1
    assert len(service2._cases) == 1
    assert case1.id != case2.id

def test_case_has_unique_ids():
    """Each case gets a unique UUID"""
    service = CAPAService()
    case1 = service.create_case(title="One", severity=CAPASeverity.MINOR)
    case2 = service.create_case(title="Two", severity=CAPASeverity.MINOR)
    assert case1.id != case2.id
