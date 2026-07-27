import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Space, Modal, Form, Input, Select, message, DatePicker, Empty, Row, Col,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'

interface TimeStudy {
  id: string
  factory_id: string
  station_id: string
  operation_name: string
  operator_id: string
  average_time: number
  normal_time: number
  allowed_time: number
  status: string
  created_at: string
}

const TimeStudies: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [data, setData] = useState<TimeStudy[]>([])
  const [loading, setLoading] = useState(false)

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await fetch(`http://localhost:8000/api/v1/ie/time-studies?factory_id=${factory}&limit=500`)
      const data = await res.json()
      setData(Array.isArray(data) ? data : [])
    } catch (e) {
      console.error('Error fetching time studies', e)
      setData([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [factory])

  const columns: ColumnsType<TimeStudy> = [
    {
      title: '工厂ID',
      dataIndex: 'factory_id',
      key: 'factory_id',
      width: 100,
    },
    {
      title: '工位',
      dataIndex: 'station_id',
      key: 'station_id',
      width: 120,
    },
    {
      title: '操作名称',
      dataIndex: 'operation_name',
      key: 'operation_name',
      width: 180,
    },
    {
      title: '操作员',
      dataIndex: 'operator_id',
      key: 'operator_id',
      width: 100,
    },
    {
      title: '平均时间(min)',
      dataIndex: 'average_time',
      key: 'average_time',
      width: 100,
      render: (val) => val.toFixed(2),
    },
    {
      title: '正常时间(min)',
      dataIndex: 'normal_time',
      key: 'normal_time',
      width: 100,
      render: (val) => val.toFixed(2),
    },
    {
      title: '允许时间(min)',
      dataIndex: 'allowed_time',
      key: 'allowed_time',
      width: 100,
      render: (val) => val.toFixed(2),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      render: (val) => <Tag color="blue">{val}</Tag>,
    },
    {
      title: '创建日期',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (val) => dayjs(val).format('YYYY-MM-DD HH:mm'),
    },
  ]

  return (
    <Card title="时间研究管理">
      <Row gutter={16} align="middle" style={{ marginBottom: 16 }}>
        <Col span={4}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => message.info('Create button not implemented yet')}>
            新增记录
          </Button>
        </Col>
        <Col span={4}>
          <Select value={factory} onChange={setFactory} style={{ width: 120 }}>
            <Select.Option value="F001">F001 厂区</Select.Option>
          </Select>
        </Col>
      </Row>
      {data.length > 0 ? (
        <Table
          dataSource={data}
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

export default TimeStudies