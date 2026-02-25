import React, { useEffect, useState } from 'react'
import { Row, Col, Card, Statistic, Table, Tag, Spin, message } from 'antd'
import { getWorkOrders, WorkOrder } from '../services/mes'

const Dashboard: React.FC = () => {
  const [loading, setLoading] = useState(false)
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([])
  const [stats, setStats] = useState({
    todayOutput: 0,
    yieldRate: 98.5,
    activeOrders: 0,
    pendingDefects: 0,
  })

  useEffect(() => {
    fetchData()
  }, [])

  const fetchData = async () => {
    setLoading(true)
    try {
      const result = await getWorkOrders({ limit: 10 })
      setWorkOrders(result.items || [])
      setStats(prev => ({
        ...prev,
        activeOrders: result.items?.filter((wo: WorkOrder) => wo.status === 'in_progress').length || 0,
      }))
    } catch (error) {
      console.error('Failed to fetch data:', error)
    } finally {
      setLoading(false)
    }
  }

  const statusMap: Record<string, { color: string; text: string }> = {
    pending: { color: 'default', text: '待排产' },
    in_progress: { color: 'processing', text: '生产中' },
    completed: { color: 'success', text: '已完成' },
    cancelled: { color: 'error', text: '已取消' },
  }

  const columns = [
    { title: '工单号', dataIndex: 'work_order_code', key: 'work_order_code' },
    { title: '产品ID', dataIndex: 'product_id', key: 'product_id' },
    { title: '计划数', dataIndex: 'planned_qty', key: 'planned_qty' },
    { title: '完成数', dataIndex: 'completed_qty', key: 'completed_qty' },
    { title: '状态', dataIndex: 'status', key: 'status', render: (status: string) => {
      const { color, text } = statusMap[status] || { color: 'default', text: status }
      return <Tag color={color}>{text}</Tag>
    }},
  ]

  return (
    <div>
      <h2 style={{ marginBottom: '24px' }}>生产看板</h2>
      
      <Spin spinning={loading}>
        <Row gutter={16} style={{ marginBottom: '24px' }}>
          <Col span={6}>
            <Card>
              <Statistic title="今日产量" value={stats.todayOutput} suffix="件" valueStyle={{ color: '#1890ff' }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic title="良品率" value={stats.yieldRate} suffix="%" valueStyle={{ color: '#52c41a' }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic title="在制工单" value={stats.activeOrders} suffix="个" valueStyle={{ color: '#faad14' }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic title="待处理不良" value={stats.pendingDefects} suffix="件" valueStyle={{ color: '#f5222d' }} />
            </Card>
          </Col>
        </Row>

        <Row gutter={16}>
          <Col span={12}>
            <Card title="在制工单">
              <Table 
                columns={columns} 
                dataSource={workOrders.map((wo, i) => ({ ...wo, key: wo.id || i }))} 
                pagination={false} 
                size="small" 
              />
            </Card>
          </Col>
          <Col span={12}>
            <Card title="今日报工趋势">
              <div style={{ height: '200px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
                图表区域
              </div>
            </Card>
          </Col>
        </Row>
      </Spin>
    </div>
  )
}

export default Dashboard
