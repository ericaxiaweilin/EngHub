"""地基判词的三态：有对象 / 只有裸 SQL / 全仓零引用 —— 别把"没实现"读成"没人用"。

为什么单独测这个纯函数：`Base.metadata` 一个信号会误判。10-09 实测
`inventory_freezes` / `stock_alerts` / `wms_transfer_requests` / `safety_stock_config`
都没映射成 ORM 对象，但代码在用它们（裸 SQL）；而 `wms_barcodes` / `wms_inventory_pools`
/ `wms_inventory_pool_members` / `wms_rfid_tags` / `wms_automation_jobs` 是真零引用。
把后者也叫"实现了没人用"就是给厂里递了个错结论 —— 那五张的功能从没实现过。
"""
from api.services.wms_audit import WMS_DOMAIN_TABLES, classify_table, table_references


def test_mapped_table_is_wired_even_without_raw_sql():
    assert classify_table("inventory", in_db=True, mapped=True, referenced=False) == "wired"


def test_unmapped_but_referenced_is_raw_sql_only_not_orphan():
    """反向（这一步最容易判错）：没对象不等于没功能。"""
    for name in ("inventory_freezes", "stock_alerts", "wms_transfer_requests",
                 "safety_stock_config"):
        assert classify_table(name, in_db=True, mapped=False, referenced=True) == "raw_sql_only"


def test_zero_reference_table_is_orphan():
    """正向：表建了、没人引用 —— 判"从没实现过"，不判"空表"。"""
    for name in ("wms_barcodes", "wms_inventory_pools", "wms_inventory_pool_members",
                 "wms_rfid_tags", "wms_automation_jobs"):
        assert classify_table(name, in_db=True, mapped=False, referenced=False) == "orphan"


def test_absent_table_is_not_reported_as_empty():
    """库里根本没这张表时，不许落成"0 行的空表" —— 那是把"没有"读成"还没人用"。"""
    assert classify_table("wms_barcodes", in_db=False, mapped=False, referenced=True) == "missing"


def test_table_references_excludes_the_audit_module_itself():
    """自证防护：wms_audit.py 的注释里点名了这五张表，扫描必须把自己排除掉，
    否则它们会被判成 raw_sql_only，"零引用"这件事就永远报不出来。"""
    refs = table_references()
    assert refs is not None, "扫不到源码却返回空集，等于把'测不出'当'全都没引用'"
    for name in ("wms_barcodes", "wms_rfid_tags", "wms_automation_jobs",
                 "wms_inventory_pools", "wms_inventory_pool_members"):
        assert name in WMS_DOMAIN_TABLES
        assert name not in refs, f"{name} 只在该审计模块自己的注释里出现过，不该算引用"
