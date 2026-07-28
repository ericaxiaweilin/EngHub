    async def complete_work_order(
        self, 
        work_order_id: str,
        completed_qty: Optional[int] = None,
        good_qty: Optional[int] = None,
        defect_qty: Optional[int] = None,
        user=None,
    ) -> Optional[WorkOrder]:
        """生产中/待入库 → 已完成（审核门槛：品质角色 + 实际产出 + 父子完工约束 + 检验通过）"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        # 审核门槛 1：品质确认（厂长 / 品质经理）
        self._require_role(user, "complete")
        
        children = await self._get_children(work_order_id)
        if children:
            # 父子约束：主工单自身不生产，须全部子工单完工后才能完工，数量自动汇总
            unfinished = [c for c in children if c.status not in [WOStatus.COMPLETED, WOStatus.CLOSED]]
            if unfinished:
                codes = "、".join(
                    f"{c.work_order_code}（{WOStatus.DISPLAY.get(c.status, c.status)}）" for c in unfinished
                )
                raise ValueError(f"子工单未全部完工，主工单不可完工。未完工子工单：{codes}")
            if work_order.status not in [WOStatus.RELEASED, WOStatus.IN_PROGRESS, WOStatus.PENDING_INBOUND]:
                raise ValueError(f"只能完成已下达/生产中/待入库的工单，当前状态: {work_order.status}")
            # 数量由子工单自动汇总，不接受手工传入
            for k, v in self._aggregate_children_qty(children).items():
                setattr(work_order, k, v)
        else:
            if work_order.status not in [WOStatus.IN_PROGRESS, WOStatus.PENDING_INBOUND]:
                raise ValueError(f"只能完成生产中/待入库的工单，当前状态: {work_order.status}")
            if completed_qty is not None:
                work_order.completed_qty = completed_qty
            if good_qty is not None:
                work_order.good_qty = good_qty
            if defect_qty is not None:
                work_order.defect_qty = defect_qty
        
        # ========== QMS-MES 联动：检验前置检查 ==========
        # 检查该工单是否存在FAIL状态的检验记录（如有则阻止完工）
        try:
            from database.models import QualityInspection
            
            fail_check_stmt = select(QualityInspection).where(
                QualityInspection.work_order_id == work_order.id,
                QualityInspection.result == 'FAIL',
                QualityInspection.factory_id == work_order.factory_id,
            )
            fail_result = await self.db.execute(fail_check_stmt)
            failed_inspections = fail_result.scalars().all()
            
            if failed_inspections:
                failed_codes = [insp.id for insp in failed_inspections]
                raise ValueError(
                    f"工单 {work_order.work_order_code} 存在未通过的检验(s): {failed_codes}，"
                    "请先处理不合格项并通过复检验证后方可完工"
                )
            
            # 另外检查是否有 PENDING（待处理）的检验并警告
            pending_check_stmt = select(QualityInspection).where(
                QualityInspection.work_order_id == work_order.id,
                QualityInspection.result == 'PENDING',
                QualityInspection.factory_id == work_order.factory_id,
            )
            pending_result = await self.db.execute(pending_check_stmt)
            pending_inspections = pending_result.scalars().all()
            
            if pending_inspections:
                print(f"[WARN] 工单 {work_order.work_order_code} 仍有 {len(pending_inspections)} 个待处理检验，但允许继续完工")
                
        except Exception as e:
            if "ValueError" in str(type(e)):
                raise  # 业务错误直接抛出
            print(f"[WARN] 检验状态检查异常: {e}")
            # 检验检查失败不阻止完工，仅记录警告
        
        # ===============================================
        
        # 审核门槛 2：有实际产出才能完工
        if not (work_order.completed_qty or 0) > 0:
            raise ValueError("完工数量为 0：无实际产出不能完工（请先报工）")
        
        from_status = work_order.status
        work_order.status = WOStatus.COMPLETED
        work_order.actual_complete = datetime.utcnow()
        work_order.updated_at = datetime.utcnow()
        work_order.completed_by = getattr(user, "username", None) or "system"
        self._log_status(work_order, "complete", from_status, WOStatus.COMPLETED, user)
        
        # ========== MES-WMS 集成：触发成品入库 ==========
        try:
            wms_service = WmsService(db=self.db)
            
            # 获取产品信息以确认成品物料
            product_stmt = select(Product).where(
                Product.id == work_order.product_id,
                Product.factory_id == work_order.factory_id
            )
            product_result = await self.db.execute(product_stmt)
            product = product_result.scalar_one_or_none()
            
            if product:
                # 使用实际完工数量作为入库数量
                inbound_qty = work_order.completed_qty or 0
                
                if inbound_qty > 0:
                    # 检查是否有之前预留的库存并尝试释放转换
                    reserved_qty = getattr(work_order, 'reserved_qty', 0) or 0
                    
                    if reserved_qty > 0:
                        # 有预留：将预留转为正式入库
                        release_qty = min(reserved_qty, inbound_qty)
                        
                        # 查找对应的库存记录
                        inv_stmt = select(Inventory).where(
                            Inventory.factory_id == work_order.factory_id,
                            Inventory.material_id == product.id,
                            Inventory.warehouse_id == work_order.reserved_warehouse
                        )
                        inv_result = await self.db.execute(inv_stmt)
                        inventory = inv_result.scalar_one_or_none()
                        
                        if inventory:
                            # 更新库存：增加可用和在手数量
                            inventory.available_qty += release_qty
                            inventory.total_qty += release_qty
                            inventory.updated_at = datetime.utcnow()
                            
                            # 写入库存流水（入库类型）
                            txn = await wms_service.record_transaction(
                                factory_id=work_order.factory_id,
                                material_id=product.id,
                                transaction_type="inbound",
                                quantity=inbound_qty,
                                inventory_id=inventory.id,
                                reference_type="work_order",
                                reference_id=work_order.id,
                                operator=getattr(user, "username", None) or "system",
                                remark=f"Work Order {work_order.work_order_code} completed - finished goods inbound (released reservation)"
                            )
                            await self.db.add(txn)
                            print(f"[WMS Integration] Created inbound for {inbound_qty} units of product {product.id} (Work Order: {work_order.work_order_code})")
                        else:
                            # 如果库存记录不存在，先创建
                            new_inv = Inventory(
                                id=str(uuid.uuid4()),
                                factory_id=work_order.factory_id,
                                material_id=product.id,
                                warehouse_id=work_order.reserved_warehouse,
                            )