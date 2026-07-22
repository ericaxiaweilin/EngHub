import React from 'react'
import { Drawer, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'

const { Text } = Typography

export interface DrillDownDrawerProps {
  open: boolean
  onClose: () => void
  /** 抽屉标题，如 "今日良品产出 · 追溯" */
  title: string
  /** 顶部大数字展示，如 "1,644 件" */
  headline?: React.ReactNode
  /** 计算公式，直接回答"这个数怎么来的"，如 "1,644 = 788 + 748 + 108（3 条报工）" */
  formula?: string
  columns: ColumnsType<any>
  records: any[]
  /** 点击某条原始记录继续下钻（如跳详情） */
  onRowClick?: (record: any) => void
  width?: number
}

/**
 * 数字下钻抽屉：点击聚合数字后弹出，展示构成该数字的原始记录清单 + 计算公式。
 * 是"数据可追溯到最底层"的核心交互组件。
 */
const DrillDownDrawer: React.FC<DrillDownDrawerProps> = ({
  open, onClose, title, headline, formula, columns, records, onRowClick, width = 760,
}) => {
  return (
    <Drawer title={title} open={open} onClose={onClose} width={width} destroyOnClose>
      {(headline || formula) && (
        <div
          style={{
            marginBottom: 16, padding: '12px 16px', background: '#f0f5ff',
            borderRadius: 6, border: '1px solid #adc6ff',
          }}
        >
          {headline && (
            <div style={{ fontSize: 24, fontWeight: 600, color: '#1890ff', lineHeight: 1.3 }}>{headline}</div>
          )}
          {formula && <Text type="secondary" style={{ fontSize: 13 }}>{formula}</Text>}
        </div>
      )}
      <Table
        columns={columns}
        dataSource={records.map((r, i) => ({ ...r, key: r.id ?? r.key ?? i }))}
        pagination={false}
        size="small"
        scroll={records.length > 12 ? { y: 420 } : undefined}
        onRow={onRowClick
          ? (record) => ({ onClick: () => onRowClick(record), style: { cursor: 'pointer' } })
          : undefined}
      />
      <div style={{ marginTop: 12 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          共 {records.length} 条原始记录{onRowClick ? ' · 点击任意一行可继续下钻' : ''}
        </Text>
      </div>
    </Drawer>
  )
}

export default DrillDownDrawer
