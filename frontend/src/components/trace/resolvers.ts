/**
 * ID 可读化解析器：把裸 UUID / 外键 ID 还原为人类可读的编码或名称。
 * 各页面用"已拉取"的列表数据构建 Map，无需额外请求。
 * 这是"数据可追溯"的基础——外键必须可读、可认，否则追溯链在用户眼前是断的。
 */

export interface StationLike { id: string; station_code: string; station_name: string }
export interface WorkOrderLike { id: string; work_order_code: string }
export interface EquipmentLike { id: string; equipment_code: string; equipment_name: string }
export interface ProductLike { id: string; product_code: string; product_name: string }

/** 工位 ID（或编码）→ "编码 名称"，解析不到则原样返回（兜底不丢信息） */
export const makeStationResolver = (stations: StationLike[]) => {
  const byId = new Map(stations.map((s) => [s.id, s]))
  const byCode = new Map(stations.map((s) => [s.station_code, s]))
  return (idOrCode?: string | null): string => {
    if (!idOrCode) return '-'
    const s = byId.get(idOrCode) || byCode.get(idOrCode)
    return s ? `${s.station_code} ${s.station_name}` : idOrCode
  }
}

/** 工单 ID → 工单号 */
export const makeWorkOrderResolver = (orders: WorkOrderLike[]) => {
  const byId = new Map(orders.map((o) => [o.id, o]))
  return (id?: string | null): string => {
    if (!id) return '-'
    return byId.get(id)?.work_order_code || id
  }
}

/** 设备 ID → "编码 名称" */
export const makeEquipmentResolver = (equipment: EquipmentLike[]) => {
  const byId = new Map(equipment.map((e) => [e.id, e]))
  return (id?: string | null): string => {
    if (!id) return '-'
    const e = byId.get(id)
    return e ? `${e.equipment_code} ${e.equipment_name}` : id
  }
}

/** 产品 ID → "编码 名称"，解析不到则原样返回（兑底不丢信息） */
export const makeProductResolver = (products: ProductLike[]) => {
  const byId = new Map(products.map((p) => [p.id, p]))
  return (id?: string | null): string => {
    if (!id) return '-'
    const p = byId.get(id)
    return p ? `${p.product_code} ${p.product_name}` : id
  }
}
