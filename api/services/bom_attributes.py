"""BOM 行属性解析 + 自制/采购判定规则（用户 10-05 给的工厂口径）。

engflow 上传的 `description` 不是自由文本，而是**分号结构串**：

    名稱;別名/位置;規格;材料;表面處理/顏色;尺寸;圖號或項目號;...

例：`齒輪;;;POM(塑膠鋼)+10%纖維+二硫化鉬;;H58/S22;JM03;`
     `端蓋;車架;左前;ABS PA757S;黑色/Black C;;EP589;`
     `車架組;;;烤漆;DM334;;EP298;`

同传下来的规则（本模块的判据依据）：
1. **L3 层就是半成品**——半成品自己的下层就在同一个上传文件里（不用另外传子件 BOM）；
2. **PCB 及板上电子元器件是外购**——只有 PCB 厂才贴片，所以电子件即使带下级也不当自制；
3. 名称以"圖/图"结尾的是**图纸行**（零件爆炸圖、走線圖、裝櫃示意圖…），
   它是文件不是物料：不建主档、不推路线、不算采购件。

之前我把整串分号文本当品名写进了 `products.product_name`（221 行），
所以这里同时提供 `clean_name()` 与幂等修复入口。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

# 电子元器件/PCB：外购。宁可少判自制，也不给买来的东西编工艺路线。
ELECTRONIC_RE = re.compile(
    r"(PCB|電路板|电路板|線路板|线路板|FPC|電阻|电阻|電容|电容|电感|電感|二極|二三極|"
    r"晶片|芯片|IC|LED|光耦|繼電器|继电器|開關|开关|蜂鳴|发鸣|排線|排线|線束|线束|貼片|贴片)"
)
# 图纸/文档行：名称以"圖/图"结尾（爆炸圖、組立圖、走線圖、裝櫃示意圖…）
DOCUMENT_RE = re.compile(r"(圖|图)$")

# 表面处理/工艺关键字 -> 这些词本身就是"这道件要过哪些车间"的证据。
# 全系统只有这一份工序词表：路线佐证、工位匹配、缺口归集都从这里取，
# 另开一份词表等于让同一个件在不同路径被判成不同工艺（10-05 就是这么散的）。
PROCESS_TOKENS: Dict[str, tuple] = {
    "焊接": ("焊接", "熔接", "鉚接", "铆接", "點焊", "点焊", "銅焊", "铜焊"),
    "涂装": ("烤漆", "噴漆", "喷漆", "涂裝", "涂装", "表面", "噴砂", "砂", "噴粉", "喷粉"),
    "电镀": ("電鍍", "电镀", "鍍白鋅", "镀锌", "鍍鋅", "陽極", "阳极", "氧化", "鋅接", "電著", "电著"),
    "机加": ("CNC", "切削", "車削", "车削", "铣", "鉻", "磨", "研磨", "磨削", "冲压", "沖壓",
             "滲氮", "盐浴", "鹽浴", "加工", "機加工", "切割", "拋光", "抛光", "鉆孔", "钻孔",
             "放電", "放电", "火花"),
    "注塑": ("注塑", "成形", "成型", "POM", "ABS", "PA66", "尼龍", "尼龙", "塑膠", "塑料", "射出"),
    "电控": ("電控", "电控", "馬達", "马达", "發電機", "发电机", "儀表", "仪表", "變頻", "变频",
             "機電", "机电"),
    "装配": ("組立", "组立", "總裝", "总装", "装配", "裝配", "組合", "总成", "總成", "組裝", "组装"),
    "检验": ("檢驗", "检验", "終檢", "终检", "全檢", "全检", "抽檢", "抽检", "品管", "品質",
             "品质", "測試", "测试", "檢測", "检测", "檢查", "检查"),
    "包装": ("包裝", "包装", "裝櫃", "装柜", "紙箱", "纸箱", "彩盒"),
}


def families_in(text: Optional[str]) -> tuple:
    """这段文本里出现了哪些工序族（顺序固定，结果可复现）。

    `text` 既可以是 BOM 行原文（当作证据），也可以是工步/工位名（当作待归类的工序）。
    """
    body = text or ""
    return tuple(
        family for family, tokens in PROCESS_TOKENS.items()
        if any(token in body for token in tokens)
    )


def parse(raw: Optional[str]) -> Dict[str, str]:
    """把分号串拆成具名字段；认不出的位置只保留原文，不硬猜语义。"""
    text = (raw or "").strip()
    if not text:
        return {"name": "", "raw": ""}
    parts = [p.strip() for p in text.split(";")]
    name = parts[0] if parts else ""
    fields = {
        "name": name,
        "alias": parts[1] if len(parts) > 1 else "",
        "spec": parts[2] if len(parts) > 2 else "",
        "material": parts[3] if len(parts) > 3 else "",
        "finish": parts[4] if len(parts) > 4 else "",
        "raw": text,
    }
    return fields


def clean_name(raw: Optional[str]) -> str:
    """品名只取第一段；没有分号的正常品名原样返回。"""
    text = (raw or "").strip()
    if not text:
        return ""
    return text.split(";")[0].strip() or text


def is_document(name_or_raw: Optional[str]) -> bool:
    return bool(DOCUMENT_RE.search(clean_name(name_or_raw)))


def is_electronic(raw: Optional[str]) -> bool:
    return bool(ELECTRONIC_RE.search(raw or ""))


def sourcing_basis(raw: Optional[str], *, has_children: bool) -> Dict[str, Any]:
    """按工厂口径给一件定性：外购/自制/图纸。判据要能跟着结果一起报出去。

    优先级说明：图纸行不是物料（先摘出去）；电子元器件即使带下级也是外购
    （贴片在 PCB 厂做）；其余按结构 —— 有下级 = 要自己装的半成品。
    """
    name = clean_name(raw)
    if is_document(raw):
        return {"item_type": "document", "basis": "drawing_row", "name": name}
    if is_electronic(raw):
        return {"item_type": "buy", "basis": "electronic_purchased", "name": name}
    if has_children:
        return {"item_type": "make", "basis": "has_children", "name": name}
    return {"item_type": "buy", "basis": "leaf", "name": name}


def process_evidence(raw: Optional[str]) -> Dict[str, bool]:
    """从一行文本里读出的工艺证据（烤漆/电镀/机加…），给路线佐证用。"""
    present = set(families_in(raw))
    return {process: process in present for process in PROCESS_TOKENS}


def corpus_of(lines: list) -> str:
    """把若干 BOM 行的属性文本拼成语料，供工序佐证匹配（含品名与整串原文）。"""
    chunks = []
    for line in lines:
        if not line:
            continue
        if isinstance(line, dict):
            chunks.append(str(line.get("material_name") or line.get("description") or ""))
            chunks.append(str(line.get("raw_description") or ""))
        else:
            chunks.append(str(line))
    return " ".join(c for c in chunks if c)
