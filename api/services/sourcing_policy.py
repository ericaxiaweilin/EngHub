"""厂区采购政策：同一料号在机械厂和电子厂可以买可做。

用户的工厂口径（10-05）：钢铁/机械厂 —— PCB、电子元器件这类买；电子厂 —— 机械部件买。
这在 SAP 里就是 plant 级 MRP 类型：自制还是外购不是物料的单值属性，而是
「这个厂有没有干这道活的车间」。所以政策的判据是**本厂能做什么**，而不是料号叫什么。

三条硬规矩（越界就不判，退回结构+工序字样推导）：
1. 只在厂区性质明确、且证据**单一方向**时才判：一个装配件的子树里既有"焊接/烤漆"又有"電控"，
   说明它既有机加工又有电气工作（例：帶線束的組件），这种不判，交推导；
2. 政策永远不"造"出自制：它只能把"该买的"从 make 里摘出去，不能把没证据的东西判成做；
3. 每一行的 `basis` 写清是哪条政策放行的（`factory_policy:xxx`），出错能一眼看到是哪条规则。
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# 厂区的"本厂工序"：站得住的依据是厂区自己的工位主数据（机械厂有焊接/涂装/机加/注塑车间，
# 电子厂有 SMT/贴片/DIP）。这里写成常量而不是查库，是因为它相当于工艺部的章程，
# 该由人改而不是让程序从工位名猜出来。
MECH_PLANT = "FAC_MECH_001"
ELEC_PLANT = "FAC_ELEC_DEMO_2026"

PLANT_OWN_FAMILIES: Dict[str, set] = {
    MECH_PLANT: {"焊接", "涂装", "电镀", "机加", "注塑", "装配", "检验", "包装"},
    ELEC_PLANT: {"电控", "装配", "检验", "包装"},
}
# 别人家的活：出现在外厂专属族里，本厂没有对应车间
PLANT_FOREIGN_FAMILIES: Dict[str, set] = {
    MECH_PLANT: {"电控"},          # 机械厂没有 SMT/贴片/电子件车间：电控类组件外购
    ELEC_PLANT: {"焊接", "涂装", "电镀", "机加", "注塑"},   # 电子厂不做金属加工/注塑
}
# 电子元器件即使写了制程，也是买（只有 PCB 厂才贴片）—— 与 bom_attributes 的口径一致
ELECTRONIC_FAMILY = "电控"



# 源声明的物料分类（engflow part_master → 镜像 enghub_bom_items.component_type）。
# 这是你说的那类"字幕标记"的真身：10-05 实测快照 719 个料号里 680 个有值。
# 权力仍然只有一条 —— 只用来把该买的摘出去，**不用来把东西判成自制**：
# structural_part / assembly 只说明"它是结构件/总成"，不代表本厂一定自己做（买成品支架很常见），
# 所以那两类继续要求有工序字样证据，政策不替工厂造自制。
ALWAYS_BUY_DECLARED = ("raw_material", "hardware", "packaging", "label")
PLANT_BUY_DECLARED = {
    MECH_PLANT: ("electronic_component", "control_board"),   # 机械厂不做贴片：电子件按源声明买
    ELEC_PLANT: ("packaging", "label"),                      # 电子厂包装标贴本来就买
}


def declared_buy(factory_id: str, component_type: Optional[str]) -> Optional[str]:
    """源声明判外购时返回依据文字；不判返回 None。"""
    ctype = str(component_type or "").strip().lower()
    if not ctype or ctype == "unknown":
        return None
    if ctype in ALWAYS_BUY_DECLARED:
        return f"source_declared:{ctype}"
    if ctype in PLANT_BUY_DECLARED.get(str(factory_id), ()):
        return f"source_declared:{ctype}@{factory_id}"
    return None

def decide(factory_id: str, families: Tuple[str, ...], *, has_children: bool,
           evidence: Tuple[str, ...] = ()
           ) -> Optional[Tuple[str, str]]:
    """返回 (item_type, basis)；判不了返回 None，由调用方退回结构推导。

    `evidence` 是子树里真正命中的关键字。理由必须把它们写出来 —— 只写"本厂无电控工序"
    会让人以为这个料号是电子件，而实际上可能是它的子树里挂了一根儀表線（10-05 就是这么误读过）。
    """
    own = PLANT_OWN_FAMILIES.get(str(factory_id))
    if own is None:
        return None            # 不认识的厂区不判，别拿默认政策套到所有厂
    present = set(families or ())
    foreign = PLANT_FOREIGN_FAMILIES[factory_id]
    if not present:
        return None            # 无工序字样时本来就已经按"反推外购"处理，政策不重复表态
    hits_own = present & own
    hits_foreign = present & foreign
    # 只沾外厂的活、本厂一样不沾 —— 判买
    if hits_foreign and not hits_own:
        words = "/".join(str(w) for w in (evidence or hits_foreign))
        return ("buy", f"factory_policy:{factory_id}-子树证据只有{'/'.join(sorted(hits_foreign))}"
                       f"（命中字样 {words}），本厂没有做这类活的车间")
    # 既沾本厂又沾外厂（带线束的焊件、带塑胶件的机加件）—— 不判，交推导
    if hits_foreign and hits_own:
        return None
    return None
