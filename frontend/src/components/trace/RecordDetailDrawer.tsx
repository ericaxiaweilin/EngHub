import React from 'react'
import { Drawer, Descriptions, Table, Divider } from 'antd'
import type { ColumnsType } from 'antd/es/table'

export interface DetailField {
  label: string
  key: string
  /** 自定义渲染（如状态标签、时间格式化、可点链接） */
  render?: (value: any, record: any) => React.ReactNode
  span?: number
}

export interface RelatedSection {
  title: string
  records: any[]
  columns: ColumnsType<any>
  onRowClick?: (record: any) => void
}

export interface RecordDetailDrawerProps {
  open: boolean
  onClose: () => void
  title: string
  record: any
  /** 全字段清单（Descriptions 展示） */
  fields: DetailField[]
  /** 关联记录区块（如该报工所属工单的其他报工） */
  related?: RelatedSection[]
  /** 抽屉头部右侧附加内容（如"已修改"痕迹标签） */
  extra?: React.ReactNode
  width?: number
}

/**
 * 记录详情抽屉：展示单条原始记录的全部字段（唯一编号/时间/经手人/修改痕迹），
 * 并可挂载关联记录表，实现"记录 → 关联实体"的追溯跳转。
 */
const RecordDetailDrawer: React.FC<RecordDetailDrawerProps> = ({
  open, onClose, title, record, fields, related, extra, width = 680,
}) => {
  return (
    <Drawer title={title} open={open} onClose={onClose} width={width} destroyOnClose extra={extra}>
      {record && (
        <>
          <Descriptions bordered column={2} size="small">
            {fields.map((f) => (
              <Descriptions.Item key={f.key} label={f.label} span={f.span}>
                {f.render ? f.render(record[f.key], record) : (record[f.key] ?? '-')}
              </Descriptions.Item>
            ))}
          </Descriptions>

          {(related || []).map((sec) => (
            <div key={sec.title} style={{ marginTop: 16 }}>
              <Divider orientation="left" style={{ margin: '8px 0' }}>
                {sec.title}（{sec.records.length}）
              </Divider>
              <Table
                columns={sec.columns}
                dataSource={sec.records.map((r, i) => ({ ...r, key: r.id ?? i }))}
                pagination={false}
                size="small"
                onRow={sec.onRowClick
                  ? (rec) => ({ onClick: () => sec.onRowClick!(rec), style: { cursor: 'pointer' } })
                  : undefined}
              />
            </div>
          ))}
        </>
      )}
    </Drawer>
  )
}

export default RecordDetailDrawer
