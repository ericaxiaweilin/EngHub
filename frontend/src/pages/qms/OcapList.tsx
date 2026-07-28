import React, { useEffect, useState } from 'react'
import { Table, Button, Space, Card, message, Row, Col, Tag } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { getDefects, Defect } from '../../services/mes'
import { getStoredUser, hasPermission } from '../../services/auth'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'

const OcapList: React.FC = () => {
  const user = getStoredUser()
  const factoryId = user?.factoryId || 'F01'
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<Defect[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const navigate = useNavigate()

  const fetchData = async () => {
    setLoading(true)
    try {
      // 获取所有 OCAP 状态为 triggered/in_progress 的缺陷
      const res = await getDefects({
        factory_id: factoryId,
        page,
        page_size: 20,
        ocap_status: ['triggered', 'in_progress'],
      })
      setData(res.items || [])
      setTotal(res.total || 0)
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '获取OCAP记录失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [fetchData, page])

  const columns: ColumnsType<Defect> = [
    { title: '不良单号', dataIndex: 'defect_code', key: 'code', width: 140, render: (v: string, r: Defect) => v || r.id },
    { title: '缺陷类型', dataIndex: 'defect_type', key: 'type', width: 100, render: (v: string) => v || '-' },
    { title: '严重等级', dataIndex: 'severity', key: 'sev', width: 90, render: (v: string) => {
      const map = { critical: 'red', major: 'orange', minor: 'default', observation: 'blue' }
      return <Tag color={map[v] || 'default'}>{v || '-'}</Tag>
    }},
    { title: 'OCAP状态', dataIndex: 'ocap_status', key: 'ocap', width: 100, render: (v: string) => {
      const map: Record<string, string> = { triggered: '已触发', in_progress: '处理中', closed: '已关闭' }
      return <Tag color={v === 'triggered' ? 'warning' : v === 'in_progress' ? 'processing' : 'success'}>{map[v] || v || '-'}</Tag>
    }},
    { title: '根因', dataIndex: 'root_cause', key: 'cause', ellipsis: true, render: (v: string) => v || '未分析' },
    { title: '纠正措施', dataIndex: 'corrective_action', key: 'corrective', ellipsis: true, render: (v: string) => v || '未填写' },
    { title: '预防措施', dataIndex: 'preventive_action', key: 'preventive', ellipsis: true, render: (v: string) => v || '未填写' },
    { title: '责任部门', dataIndex: 'responsible_dept', key: 'dept', width: 120 },
    { title: '创建时间', dataIndex: 'created_at', key: 'time', width: 130, render: (v: string) => v ? dayjs(v).format('MM-DD HH:mm') : '-' },
    {
      title: '操作', key: 'action', width: 150, fixed: 'right' as const,
      render: (_, record: Defect) => (
        <Space size="small">
          <Button 
            size="small" 
            type="primary"
            onClick={() => navigate(`/qms/ocaps/${record.id}`)}
          >
            详情
          </Button>
        </Space>
      )
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={24}>
          <Card size="small" extra={<Button icon={<ReloadOutlined />} onClick={fetchData}>刷新</Button>}>
            <Space>
              <Button type="primary" onClick={() => setPage(1)}>重置筛选</Button>
              <span style={{ color: '#888' }}>共 {total} 条 OCAP 记录</span>
            </Space>
          </Card>
        </Col>
      </Row>

      <Table
        columns={columns}
        dataSource={data}
        loading={loading}
        rowKey="id"
        pagination={{
          current: page,
          total,
          pageSize: 20,
          showSizeChanger: false,
          onChange: setPage,
        }}
      />
    </div>
  )
}

export default OcapList