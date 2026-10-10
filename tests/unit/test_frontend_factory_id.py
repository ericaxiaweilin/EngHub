"""厂区 id 只有一个来源：frontend/src/utils/factory.ts。

10-09 实测的病灶：12 个页面各自硬编码 `const FACTORY = 'F001'` / `'factory-sh-01'`，
而真实数据只在 FAC_MECH_001（inventory 11,228 行）与 FAC_ELEC_DEMO_2026（4 行）——
`factory-sh-01` 在 168 张带 factory_id 的表里**一行都没有**，`F001` 只有 24 行
（20 chat_sessions、1 inspection_tasks、2 maintenance_tasks、1 plans，inventory 0 行）。
于是界面查的是不存在的厂区，读起来像"功能很弱"，其实是接错了人群。

这条断言存在的理由：`utils/factory.ts` 早就写好了唯一来源（还带 LEGACY 名单兜底），
但没人拦住新页面再抄一个字面量。
"""
import io
import os
import re

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src"))
# 唯一允许出现厂区字面量的地方：util 自己（LEGACY 名单 + fallback 默认值）
ALLOWED = os.path.join("utils", "factory.ts")
LITERAL = re.compile(r"const FACTORY\s*=\s*['\"]([^'\"]*)['\"]")
DEAD = {"F001", "factory-sh-01", "F01"}


def _files():
    out = []
    for dirpath, dirs, names in os.walk(SRC):
        dirs[:] = [d for d in dirs if d != "node_modules"]
        for n in names:
            if n.endswith((".tsx", ".ts")):
                out.append(os.path.join(dirpath, n))
    return out


def test_frontend_source_root_is_the_real_one():
    """扫不到目录不许当成"没有硬编码" —— 空集合不等于通过。"""
    assert os.path.isdir(SRC), "找不到 frontend/src（%s），这条断言没在保护任何东西" % SRC


def test_no_page_hardcodes_a_dead_factory_id():
    files = _files()
    assert len(files) > 50, "只扫到 %s 个前端文件，扫描范围不对" % len(files)
    bad = []
    for path in files:
        rel = os.path.relpath(path, SRC)
        if rel == ALLOWED:
            continue
        body = io.open(path, encoding="utf-8", errors="ignore").read()
        for m in LITERAL.finditer(body):
            if m.group(1) in DEAD:
                bad.append("%s -> %s" % (rel, m.group(1)))
    assert not bad, "这些页面把厂区写死在不存在的 id 上，应走 utils/factory.ts: %s" % bad


def test_pages_use_the_single_factory_source():
    """反向也要成立：改写不是把常量删掉就完事，页面必须真的调用唯一来源。"""
    users = [p for p in _files() if "getActiveFactoryId" in
             io.open(p, encoding="utf-8", errors="ignore").read()]
    names = {os.path.relpath(p, SRC) for p in users}
    for rel in (os.path.join("pages", "wms", "WmsCenter.tsx"),
                os.path.join("pages", "wms", "WmsTerminal.tsx"),
                os.path.join("pages", "wms", "StockAlerts.tsx")):
        assert rel in names, "%s 没接上唯一厂区来源" % rel
