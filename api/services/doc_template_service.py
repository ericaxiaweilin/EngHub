"""统一单据模板引擎（doc_type 注册表驱动，防打地鼠）。

注册表 DOC_TYPES：每类单据 = 配置（标题/数据源SQL/列映射/条款/签字栏）。
加新单据 = 注册表加一条，无需新端点/新函数。

已支持 11 类（SAP MM/PP 单据链）：
rfq 询价单 / quotation 报价单 / pr 采购申请 / po 采购订单 /
gr 收货单 / delivery_note 送货单 / statement 对账函 / invoice 发票 /
work_order 生产工单 / picking_list 领料单 / production_report 生产日报
"""
from typing import Dict, Any, Optional, List

# ═══ 注册表：每类单据的生成配置 ═══
DOC_TYPES: Dict[str, Dict[str, Any]] = {
    "rfq": {
        "title": "询 价 单", "title_en": "REQUEST FOR QUOTATION",
        "parties": [("采购方（Buyer）", "某某机械制造有限公司 · 采购部"), ("供应商（Supplier）", "{supplier_name}"),
                    ("编号", "{doc_code}"), ("日期", "{doc_date}")],
        "query": "SELECT rfq_code, material_code, material_name, quantity, unit, status, created_at FROM rfqs WHERE rfq_code=:c OR id=:c",
        "columns": [("序号", "idx"), ("物料编码", "material_code"), ("物料名称", "material_name"),
                    ("单位", "unit"), ("数量", "quantity")],
        "terms": "请贵司按上述物料报价（含税单价/交期），报价单请于 3 个工作日内回传。",
        "signs": ["采购经办", "供应商确认", "审批"],
    },
    "quotation": {
        "title": "报 价 单", "title_en": "QUOTATION",
        "parties": [("供应商（Supplier）", "{supplier_name}"), ("采购方（Buyer）", "某某机械制造有限公司"),
                    ("编号", "{doc_code}"), ("日期", "{doc_date}")],
        "query": """SELECT r.rfq_code, q.supplier_name, q.unit_price, q.lead_time_days, q.delivery_date,
                           q.payment_terms, q.status, r.material_code, r.material_name, r.quantity, q.created_at
                    FROM quotations q LEFT JOIN rfqs r ON r.id=q.rfq_id
                    WHERE q.id=:c OR q.rfq_id=:c""",
        "columns": [("物料编码", "material_code"), ("物料名称", "material_name"), ("数量", "quantity"),
                    ("含税单价", "unit_price"), ("交期(天)", "lead_time_days"), ("付款条件", "payment_terms")],
        "terms": "以上报价含税含运费，有效期 30 天。",
        "signs": ["供应商盖章", "采购确认"],
    },
    "pr": {
        "title": "采 购 申 请 单", "title_en": "PURCHASE REQUISITION",
        "parties": [("申请部门", "PMC 计划部"), ("申请人", "{created_by}"),
                    ("编号", "{doc_code}"), ("日期", "{doc_date}")],
        "query": "SELECT pr_code, material_code, material_name, qty, unit, status, source, priority, created_by, created_at FROM purchase_requisitions WHERE pr_code=:c OR id=:c",
        "columns": [("序号", "idx"), ("物料编码", "material_code"), ("物料名称", "material_name"),
                    ("单位", "unit"), ("申请数量", "qty")],
        "terms": "请购说明：生产缺料/安全库存补货，请采购寻源询价并回传预计到货时间。审批流程：PMC 申请 → 主管审批 → 采购处理。",
        "signs": ["申请人", "部门主管", "采购接收"],
    },
    "po": {
        "title": "采 购 订 单", "title_en": "PURCHASE ORDER",
        "parties": [("采购方（Buyer）", "某某机械制造有限公司"), ("供应商（Supplier）", "{supplier_name}"),
                    ("编号", "{doc_code}"), ("日期", "{doc_date}")],
        "query": "SELECT po_code, supplier_name, supplier_id, material_code, material_name, qty, unit_price, total_amount, expected_date, status, created_at FROM purchase_orders WHERE po_code=:c OR id=:c",
        "columns": [("序号", "idx"), ("物料编码", "material_code"), ("物料名称", "material_name"),
                    ("数量", "qty"), ("单价", "unit_price"), ("金额", "total_amount"), ("要求交期", "expected_date")],
        "terms": "付款条款：月结 30 天。交期要求：按订单要求日期交货，逾期按合同条款处理。质检要求：到货须附合格证，IQC 检验合格后入库。",
        "signs": ["采购经办", "供应商确认", "财务"],
    },
    "gr": {
        "title": "收 货 单", "title_en": "GOODS RECEIPT",
        "parties": [("供应商", "{supplier_name}"), ("仓库", "{warehouse}"),
                    ("编号", "{doc_code}"), ("日期", "{doc_date}")],
        "query": "SELECT gr_code, po_id, material_code, quantity, qty_accepted, qty_rejected, iqc_status, warehouse, received_by, received_at FROM goods_receipts WHERE gr_code=:c OR id=:c",
        "columns": [("物料编码", "material_code"), ("到货数量", "quantity"), ("合格", "qty_accepted"),
                    ("不良", "qty_rejected"), ("IQC状态", "iqc_status"), ("收货人", "received_by")],
        "terms": "收货经 IQC 检验：合格入账、不良退供应商。",
        "signs": ["收货员", "IQC 检验", "仓库确认"],
    },
    "delivery_note": {
        "title": "送 货 单", "title_en": "DELIVERY NOTE",
        "parties": [("供应商", "{supplier_name}"), ("收货方", "某某机械制造有限公司"),
                    ("编号", "{doc_code}"), ("日期", "{doc_date}")],
        "query": """SELECT ap.id, ap.material_code, ap.quantity, ap.eta_date, ap.transport,
                           ap.status, s.supplier_name, ap.created_at
                    FROM arrival_plans ap LEFT JOIN suppliers s ON s.id=ap.supplier_id
                    WHERE ap.id::text=:c OR ap.po_code=:c""",
        "columns": [("物料编码", "material_code"), ("数量", "quantity"), ("预计到货", "eta_date"),
                    ("运输方式", "transport"), ("状态", "status")],
        "terms": "供应商送货须附送货单/合格证，仓库凭单收货。",
        "signs": ["送货人", "仓库签收"],
    },
    "statement": {
        "title": "对 账 函", "title_en": "MONTHLY STATEMENT",
        "parties": [("供应商", "{supplier_name}"), ("采购方", "某某机械制造有限公司"),
                    ("编号", "{doc_code}"), ("账期", "{period}")],
        "query": "SELECT supplier_name, COUNT(*) AS po_count, COALESCE(SUM(total_amount),0) AS total_amount FROM purchase_orders WHERE supplier_id=:c GROUP BY supplier_name",
        "columns": [("PO单数", "po_count"), ("应付金额", "total_amount")],
        "terms": "请核对上述账期内采购金额，如有差异请在 5 个工作日内反馈，逾期视为确认。",
        "signs": ["供应商确认", "财务审核"],
        "params_note": "code = supplier_id",
    },
    "invoice": {
        "title": "发 票 校验 单", "title_en": "INVOICE MATCHING",
        "parties": [("采购方", "某某机械制造有限公司"), ("编号", "{doc_code}"), ("日期", "{doc_date}")],
        "query": "SELECT po_code, gr_code, supplier_id, invoice_amount, po_amount, gr_amount, diff_amount, status, match_type, checked_by FROM invoice_matching WHERE po_code=:c OR id=:c",
        "columns": [("PO", "po_code"), ("GR", "gr_code"), ("发票金额", "invoice_amount"), ("PO金额", "po_amount"),
                    ("GR金额", "gr_amount"), ("差异", "diff_amount"), ("匹配", "match_type"), ("状态", "status")],
        "terms": "三单匹配（PO/GR/发票）一致方可付款，差异需说明原因。",
        "signs": ["采购经办", "财务审核"],
    },
    "work_order": {
        "title": "生 产 工 单", "title_en": "PRODUCTION WORK ORDER",
        "parties": [("产品", "{product_name}"), ("工单", "{doc_code}"),
                    ("计划数量", "{planned_qty}"), ("交期", "{due_date}")],
        "query": "SELECT work_order_code, product_id, planned_qty, completed_qty, good_qty, status, priority, planned_start, planned_due, created_at FROM work_orders WHERE work_order_code=:c OR id=:c",
        "columns": [("产品", "product_id"), ("计划数量", "planned_qty"), ("已完成", "completed_qty"),
                    ("良品", "good_qty"), ("优先级", "priority"), ("开始", "planned_start"), ("交期", "planned_due"), ("状态", "status")],
        "terms": "生产工单：按工艺路线执行，完工报工并质检。",
        "signs": ["计划员", "车间主管", "质检"],
    },
    "picking_list": {
        "title": "领 料 单", "title_en": "PICKING LIST",
        "parties": [("工单", "{doc_code}"), ("领料部门", "生产车间"), ("日期", "{doc_date}")],
        "query": """SELECT wom.material_code, wom.material_name, wom.required_qty, wom.unit, wom.received_qty, wom.available_qty,
                           wo.work_order_code
                    FROM work_order_materials wom LEFT JOIN work_orders wo ON wo.id=wom.work_order_id
                    WHERE wo.work_order_code=:c OR wom.work_order_id=:c""",
        "columns": [("物料编码", "material_code"), ("物料名称", "material_name"), ("单耗", "qty_per_unit"),
                    ("需求数量", "required_qty"), ("单位", "unit"), ("已领", "received_qty"), ("可领", "available_qty")],
        "terms": "按工单 BOM 领料，领料单需车间主管签字，仓库凭单发料。",
        "signs": ["领料人", "车间主管", "仓管员"],
    },
    "production_report": {
        "title": "生 产 日 报", "title_en": "PRODUCTION REPORT",
        "parties": [("日期", "{doc_date}"), ("班次", "{shift}")],
        "query": """SELECT pr.report_code, wo.work_order_code, pr.good_qty, pr.defect_qty, pr.scrap_qty,
                           pr.shift, pr.operator_id, pr.created_at
                    FROM production_reports pr LEFT JOIN work_orders wo ON wo.id=pr.work_order_id
                    WHERE pr.report_code=:c OR pr.id=:c""",
        "columns": [("工单", "work_order_code"), ("良品", "good_qty"), ("不良", "defect_qty"),
                    ("报废", "scrap_qty"), ("班次", "shift"), ("操作工", "operator_id")],
        "terms": "生产日报：每日产出汇总，良率 = 良品/(良品+不良+报废)。",
        "signs": ["班组长", "PMC 确认"],
    },
}

# 编号列映射（doc_code 的来源列）
CODE_COLUMNS = {
    "rfq": "rfq_code", "quotation": "id", "pr": "pr_code", "po": "po_code",
    "gr": "gr_code", "delivery_note": "id", "statement": "supplier_name",
    "invoice": "po_code", "work_order": "work_order_code", "picking_list": "work_order_code",
    "production_report": "report_code",
}


# ═══ HTML 渲染 ═══
def _style() -> str:
    return """
    <style>
      body { font-family: "PingFang SC", "Microsoft YaHei", sans-serif; margin: 24px; color: #222; }
      .doc-header { display: flex; justify-content: space-between; border-bottom: 2px solid #333; padding-bottom: 12px; }
      .doc-title { font-size: 24px; font-weight: 700; }
      .doc-no { font-size: 14px; color: #555; margin-top: 4px; }
      .doc-parties { display: flex; justify-content: space-between; margin: 16px 0; flex-wrap: wrap; }
      .party-box { width: 45%; font-size: 13px; line-height: 1.8; margin-bottom: 8px; }
      .party-label { font-weight: 700; margin-bottom: 4px; }
      table.items { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px; }
      table.items th { background: #f0f0f0; border: 1px solid #ccc; padding: 8px; text-align: left; }
      table.items td { border: 1px solid #ccc; padding: 8px; }
      table.items td.num { text-align: right; }
      .doc-meta { font-size: 13px; line-height: 2; margin: 12px 0; }
      .doc-total { text-align: right; font-size: 15px; font-weight: 700; margin: 8px 0; }
      .doc-footer { margin-top: 32px; font-size: 12px; color: #777; border-top: 1px solid #ddd; padding-top: 8px; }
      .sign-row { display: flex; justify-content: space-between; margin-top: 48px; font-size: 13px; }
      .sign-box { width: 30%; text-align: center; }
      .sign-line { border-top: 1px solid #333; margin-top: 32px; padding-top: 4px; }
    </style>
    """


def _fmt(val: Any) -> str:
    if val is None:
        return "-"
    if isinstance(val, float) or isinstance(val, int):
        return f"{float(val):,.2f}".rstrip("0").rstrip(".")
    if hasattr(val, "strftime"):
        return str(val)[:10]
    return str(val)


def render_doc(doc_type: str, row: Dict[str, Any], doc_code: str, doc_date: str,
               extra: Optional[Dict[str, Any]] = None) -> str:
    """注册表驱动渲染：标题/双方/明细表/条款/签字栏。"""
    cfg = DOC_TYPES.get(doc_type)
    if not cfg:
        return f"<h3>未知单据类型 {doc_type}</h3>"
    extra = extra or {}
    # parties 渲染（支持 {field} 占位）
    parties_html = ""
    parties = []
    for label, val in cfg["parties"]:
        for k, v in {**row, **extra}.items():
            if isinstance(v, (str, int, float)):
                val = val.replace("{" + k + "}", _fmt(v))
        val = val.replace("{doc_code}", doc_code).replace("{doc_date}", doc_date)
        val = val.replace("{period}", str(extra.get("period") or doc_date))
        parties.append((label, val))
    half = max(1, (len(parties) + 1) // 2)
    for i in range(0, len(parties), half):
        chunk = parties[i:i + half]
        boxes = "".join(f'<div class="party-box"><div class="party-label">{l}</div><div>{v}</div></div>'
                        for l, v in chunk)
        parties_html += f'<div class="doc-parties">{boxes}</div>'

    # 明细表
    rows_html = ""
    for i, (label, key) in enumerate(cfg["columns"], 1):
        val = row.get(key, "-")
        rows_html += f"<tr><td>{i}</td>"
        for _, k in cfg["columns"]:
            v = row.get(k, "-")
            cls = "num" if isinstance(v, (int, float)) else ""
            rows_html += f'<td class="{cls}">{_fmt(v)}</td>'
        rows_html += "</tr>"
        break  # 单行明细（聚合单据），多行单据扩展用 items
    # 多行：如果 row 里有 items 列表则渲染全部
    if row.get("_items"):
        rows_html = ""
        for i, it in enumerate(row["_items"], 1):
            rows_html += "<tr><td>{}</td>".format(i)
            for _, k in cfg["columns"]:
                v = it.get(k, "-")
                cls = "num" if isinstance(v, (int, float)) else ""
                rows_html += f'<td class="{cls}">{_fmt(v)}</td>'
            rows_html += "</tr>"

    signs = "".join(f'<div class="sign-box"><div class="sign-line">{s}</div></div>' for s in cfg["signs"])
    return f"""<html><head><meta charset="utf-8">{_style()}</head><body>
    <div class="doc-header">
      <div>
        <div class="doc-title">{cfg["title"]}</div>
        <div class="doc-no">{cfg["title_en"]} · {doc_code}</div>
      </div>
      <div style="text-align:right; font-size:13px; line-height:1.8;">
        <div>日期：{doc_date}</div>
      </div>
    </div>
    {parties_html}
    <table class="items">
      <tr><th>序号</th>{''.join(f'<th>{l}</th>' for l, _ in cfg["columns"])}</tr>
      {rows_html}
    </table>
    <div class="doc-meta">{cfg["terms"]}</div>
    <div class="sign-row">{signs}</div>
    <div class="doc-footer">本单据由企业数字员工系统生成 · {doc_code} · 打印时间 {__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
    </body></html>"""
