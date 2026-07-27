import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Space, Modal, Form, Input, Select, message, Empty, Row, Col,
} from 'antd'
import { PlusOutlined, EditOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'
import { API_ENDPOINTS } from '../../config/api'

const { Search } = Input

interface StandardTime {
  id: string
  factory_id: string
  product_id: string
  routing_step: string
  operation_name: string
  station_id?: string
  standard_time_min: number
  effective_standard_time: number
  version: string
  is_active: boolean
  validity_start: string
  created_at: string
}

const StandardTimes: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [data, setData] = useState<StandardTime[]>([])
  const [loading, setLoading] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await api.get(API_ENDPOINTS.IE_STANDARD_TIMES, {
        params: { factory_id: factory, limit: 500 },
      })
      setData(res.items || [])
    } catch (e) {
      console.error('Error fetching standard times', e)
      setData([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [factory])

  const filteredData = data.filter(item =>
    item.operation_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    item.product_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
    item.routing_step.toLowerCase().includes(searchTerm.toLowerCase())
  )

  const columns: ColumnsType<StandardTime> = [
    {
      title: '产品ID',
      dataIndex: 'product_id',
      key: 'product_id',
      width: 120,
    },
    {
      title: '工序步骤',
      dataIndex: 'routing_step',
      key: 'routing_step',
      width: 100,
    },
    {
      title: '作业名称',
      dataIndex: 'operation_name',
      key: 'operation_name',
      width: 180,
    },
    {
      title: '工位ID',
      dataIndex: 'station_id',
      key: 'station_id',
      width: 100,
    },
    {
      title: '标准时间(min)',
      dataIndex: 'standard_time_min',
      key: 'standard_time_min',
      width: 100,
      render: (val) => val.toFixed(2),
    },
    {
      title: '有效工时',
      dataIndex: 'effective_standard_time',
      key: 'effective_standard_time',
      width: 100,
      render: (val) => val.toFixed(2),
    },
    {
      title: '版本',
      dataIndex: 'version',
      key: 'version',
      width: 60,
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 80,
      render: (bool) => <Tag color={bool ? 'green' : 'red'}>{bool ? '有效' : '无效'}</Tag>,
    },
    {
      title: '生效日期',
      dataIndex: 'validity_start',
      key: 'validity_start',
      width: 120,
      render: (val) => dayjs(val).format('YYYY-MM-DD'),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (val) => dayjs(val).format('YYYY-MM-DD HH:mm'),
    },
  ]

  return (
    <Card title="标准工时管理">
      <Row gutter={16} align="middle" style={{ marginBottom: 16 }}>
        <Col span={4}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => message.info('Create button not implemented yet')}>
            新增
          </Button>
        </Col>
        <Col span={4}>
          <Select value={factory} onChange={setFactory} style={{ width: 120 }}>
            <Select.Option value="F001">F001 厂区</Select.Option>
          </Select>
        </Col>
        <Col span={4}>
          <Search
            placeholder="搜索操作名称..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            onSearch={() => {}}
            allowClear
          />
        </Col>
      </Row>
      {filteredData.length > 0 ? (
        <Table
          dataSource={filteredData}
          columns={columns}
          loading={loading}
          pagination={{ pageSize: 10 }}
          rowKey="id"
        />
      ) : (
        <Empty description={loading ? '加载中...' : '暂无数据'} style={{ margin: '40px 0' }} />
      )}
    </Card>
  )
}

export default StandardTimes