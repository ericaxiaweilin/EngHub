"""厂区采购政策：判得了就判，判不了就退回推导，绝不硬扳。"""

import pytest

pytestmark = [pytest.mark.unit]

from api.services.sourcing_policy import ELEC_PLANT, MECH_PLANT, decide


def test_mech_plant_buys_pure_electrical_assembly():
    """机械厂只有电子件的活（電控/馬達）→ 买，即便它有下级也轮不到本厂做。"""
    verdict = decide(MECH_PLANT, ("电控",), has_children=True, evidence=("儀表", "線材"))
    assert verdict and verdict[0] == "buy"
    assert "命中字样 儀表/線材" in verdict[1], "理由要带真正命中的字样，不能只写族名"


def test_mech_plant_keeps_mechanical_assembly_as_make():
    assert decide(MECH_PLANT, ("焊接", "涂装"), has_children=True) is None
    assert decide(MECH_PLANT, ("机加", "注塑"), has_children=True) is None


def test_mixed_work_is_left_to_derivation_not_guessed():
    """带线束的焊件：本厂有焊接、外厂有电控 —— 政策不判，交结构+工序字样推导。"""
    assert decide(MECH_PLANT, ("焊接", "电控"), has_children=True) is None
    assert decide(ELEC_PLANT, ("装配", "机加"), has_children=True) is None


def test_electronics_plant_buys_pure_mechanical_parts():
    verdict = decide(ELEC_PLANT, ("机加", "注塑"), has_children=True)
    assert verdict and verdict[0] == "buy"
    assert "本厂没有做这类活的车间" in verdict[1]


def test_unknown_plant_and_no_evidence_are_no_ops():
    """不认识的厂区不能拿默认政策套；没有工序字样的走的是"反推外购"那条路。"""
    assert decide("FAC_SOMETHING_ELSE", ("电控",), has_children=True) is None
    assert decide(MECH_PLANT, (), has_children=True) is None


def test_policy_never_invents_self_made():
    """政策的权力只有"把该买的摘出去"，不能把没证据的东西判成自制。"""
    for plant in (MECH_PLANT, ELEC_PLANT):
        for families in ((), ("电控",), ("焊接",), ("机加", "电控")):
            verdict = decide(plant, families, has_children=True)
            assert verdict is None or verdict[0] == "buy"
