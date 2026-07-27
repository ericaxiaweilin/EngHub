import React, { useEffect, useState } from 'react'
import { 
  Card, Table, Tag, Space, Button, Modal, Form, Input, InputNumber, Select,
  message, Typography, Row, Col, Tree, Spin, Tabs, Tooltip, InputTextArea
} from 'antd'
import { 
  PlusOutlined, MinusOutlined, SplitCellsOutlined, UndoOutlined, ReloadOutlined, 
  RightCircleOutlined, TreeOutlined, HistoryOutlined
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { TreeDataNode } from 'antd/lib/tree/interface'
import dayjs from 'dayjs'
import api from '../../services/api'
import { getStoredUser, hasPermission } from '../../services/auth'

const { Title, Text } = Typography
const { TabPane } = Tabs

const FACTORY = 'F001' // 从上下文获取

interface WorkOrder {
  id: string
  work_order_code: string
  factory_id: string
  product_id: string
  product_name: string
  sales_order_id: string | null
  planned_qty: number
  unit: string
  completed_qty: number
  good_qty: number
  defect_qty: number
  scrap_qty: number
  status: string
  priority: string
  planned_due: string | null
  created_by: string
  routing_id: string | null
  assigned_station_id: string | null
  wo_type: string
  process_code: string | null
  operation_seq: number | null
  parent_work_order_id: string | null
}

interface SplitPreview {
  method: string
  master_wo: { code: string; new_planned_qty: number }
  children: Array<{
    code: string
    planned_qty: number
    status: string
    [key: string]: any
  }>
  total_children: number
}

interface SplitHistoryItem {
  id: string
  action: string
  result: string
  work_orders_created: number
  operator: string
  created_at: string
}

const WorkOrderSplitPage: React.FC = () => {
  const [workOrderId] = useState<string>()
  const [workOrder, setWorkOrder] = useState<WorkOrder | null>(null)
  const [loading, setLoading] = useState(true)
  const [splitMethod, setSplitMethod] = useState<'simple'|'by_routing'|'by_batch'|'by_ratio'>('simple')
  const [parameters, setParameters] = useState<any>({})
  const [preview, setPreview] = useState<SplitPreview | null>(null)
  const [treeView, setTreeView] = useState(false)
  const [historyView, setHistoryView] = useState(false)
  const [historyList, setHistoryList] = useState<SplitHistoryItem[]>([])

  // 加载工单信息
  useEffect(() => {
    if (!workOrderId) return
    
    setLoading(true)
    api.get(`/api/v1/work-orders/${workOrderId}`)
      .then(res => {
        setWorkOrder(res as WorkOrder)
        loadTree()
        loadHistory()
      })
      .catch(err => {
        message.error('工单不存在或无法访问')
      })
      .finally(() => setLoading(false))
  }, [workOrderId])

  // 加载树形结构
  const loadTree = async () => {
    if (!workOrderId) return
    try {
      const res = await api.get(`/api/v1/work-orders/${workOrderId}/tree`)
      window.currentWoTree = res.data.tree
    } catch (err) {
      console.error('Failed to load tree', err)
    }
  }

  // 加载历史
  const loadHistory = async () => {
    if (!workOrderId) return
    try {
      const res = await api.get(`/api/v1/work-orders/${workOrderId}/split-history`)
      setHistoryList(res.data.history || [])
    } catch (err) {
      console.error('Failed to load history', err)
    }
  }

  // 预览拆分
  const previewSplit = async () => {
    if (!workOrderId || !workOrder) return
    
    try {
      const res = await api.get(`/api/v1/work-orders/${workOrderId}/split-preview`, {
        params: {
          method: splitMethod,
          parameters: JSON.stringify(parameters),
        }
      })
      setPreview(res.data.result)
    } catch (err) {
      message.error('预览失败：' + (err.response?.data?.detail || err.message))
    }
  }

  // 执行高级拆分
  const executeSplit = async () => {
    if (!workOrderId || !workOrder || !preview) return
    
    const confirmResult = await new Promise<void>((resolve) => {
      Modal.confirm({
        title: `确认拆分操作`,
        content: <p>即将执行 <strong>{splitMethod}</strong> 拆分，生成 <strong>{preview.total_children}</strong> 个子工单。</p>,
        onOk: () => resolve(),
        onCancel: () => resolve(),
      })
    })
    
    try {
      const res = await api.post(`/api/v1/work-orders/${workOrderId}/split-advanced`, {
        method: splitMethod,
        parameters,
        remark: '通过独立拆单页面执行'
      })
      
      message.success('拆分成功！')
      setPreview(null)
      setSplitMethod('simple')
      setParameters({})
      loadTree()
      loadHistory()
    } catch (err) {
      message.error('拆分失败：' + (err.response?.data?.detail || err.message))
    }
  }

  // 反拆分
  const reverseSplit = async () => {
    if (!workOrderId) return
    
    const confirmResult = await new Promise<void>((resolve) => {
      Modal.confirm({
        title: '反拆分警告',
        content: '将把子工单合并回主工单，此操作不可逆。确定继续？',
        onOk: () => resolve(),
        onCancel: () => resolve(),
      })
    })
    
    try {
      const res = await api.delete(`/api/v1/work-orders/${workOrderId}/reverse-split`)
      message.success('反拆分成功！')
      setPreview(null)
      loadTree()
      loadHistory()
    } catch (err) {
      message.error('反拆分失败：' + (err.response?.data?.detail || err.message))
    }
  }

  // 动态参数表单
  const renderParamsForm = () => {
    switch (splitMethod) {
      case 'simple':
        return (
          <Form.Item label="拆分数量" name="split_qty">
            <InputNumber 
              min={1} 
              max={(workOrder?.planned_qty || 1) - 1} 
              style={{ width: '100%' }}
              onChange={(v) => setParameters({ split_qty: v || 0 })}
            />
          </Form.Item>
        )
      
      case 'by_routing':
        return <Text type="secondary">按工艺路线拆分：将为每个工序步骤生成一个子工单</Text>
      
      case 'by_batch':
        return (
          <Form.Item label="批次大小" name="batch_size">
            <InputNumber 
              min={1} 
              max={workOrder?.planned_qty || 0} 
              style={{ width: '100%' }}
              placeholder="每批数量"
              onChange={(v) => setParameters({ batch_size: v || 0 })}
            />
          </Form.Item>
        )
      
      case 'by_ratio':
        return (
          <Form.Item label="比例数组（逗号分隔）" name="ratios">
            <Input 
              placeholder="例如：50,30,20（总和为100）"
              onChange={(e) => setParameters({ ratios: e.target.value.split(',').map(Number).filter(n => n > 0) })}
            />
          </Form.Item>
        )
      
      default:
        return null
    }
  }

  // 构建树形数据
  const buildTreeData = (data?: any): TreeDataNode[] => {
    if (!data) return []
    
    const node: TreeDataNode = {
      key: data.master_wo.code,
      title: `${data.master_wo.code} (${data.master_wo.new_planned_qty} ${workOrder?.unit || 'pcs'})`,
      children: data.children ? buildTreeFromChildren(data.children) : undefined,
    }
    
    return [node]
  }

  const buildTreeFromChildren = (children: any[]): TreeDataNode[] => {
    return children.map(child => ({
      key: child.code,
      title: `${child.code} (${child.planned_qty} ${workOrder?.unit || 'pcs'})`,
      children: child.subtree ? buildTreeFromChildren(child.subtree) : undefined,
    }))
  }

  if (loading) {
    return <div style={{ padding: 24 }}><Spin message="加载中工单信息..." /></div>
  }

  if (!workOrder) {
    return <div>未找到指定工单</div>
  }

  const canSplit = hasPermission('work_order', 'edit')

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <SplitCellsOutlined style={{ fontSize: 22, color: '#1890ff' }} />
            <Title level={4} style={{ margin: 0 }}>工单拆分</Title>
            <Tag>{workOrder.work_order_code}</Tag>
          </Space>
        </Col>
        <Col>
          <Space>
            {canSplit && (
              <Button type="primary" icon={<PlusOutlined />} onClick={executeSplit}>
                执行拆分
              </Button>
            )}
            <Button icon={<UndoOutlined />} onClick={reverseSplit} disabled={!treeView}>
              反拆分
            </Button>
          </Space>
        </Col>
      </Row>

      {/* 基本信息卡片 */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={6}>
            <div><Text strong>产品：</Text>{workOrder.product_id}</div>
            <div><Text strong>名称：</Text>{workOrder.product_name || '-'}</div>
            <div><Text strong>订单号：</Text>{workOrder.sales_order_id || '无关联销售订单'}</div>
          </Col>
          <Col span={6}>
            <div><Text strong>计划量：</Text>{workOrder.planned_qty} {workOrder.unit || 'pcs'}</div>
            <div><Text strong>已完成：</Text>{workOrder.completed_qty}</div>
            <div><Text strong>良率：</Text>{((workOrder.good_qty / Math.max(workOrder.completed_qty, 1)) * 100).toFixed(1)}%</div>
          </Col>
          <Col span={6}>
            <div><Text strong>状态：</Text><Tag color={workOrder.status}>{workOrder.status_text || workOrder.status}</Tag></div>
            <div><Text strong>优先级：</Text><Tag color={{ urgent: 'red', high: 'orange', medium: 'blue', low: 'default' }[workOrder.priority]}>{workOrder.priority_text || workOrder.priority}</Tag></div>
            <div><Text strong>交期：</Text>{workOrder.planned_due ? dayjs(workOrder.planned_due).format('YYYY-MM-DD') : '无'}</div>
          </Col>
          <Col span={6}>
            <div><Text strong>工单类型：</Text>{workOrder.wo_type === 'master' ? '主工单' : '工序工单'}</div>
            <div><Text strong>父工单：</Text>{workOrder.parent_work_order_id ? '有' : '无'}</div>
            {workOrder.routing_id && <div><Text strong>工艺路线：</Text>已绑定</div>}
          </Col>
        </Row>
      </Card>

      {/* 拆分模式选择 */}
      <Card style={{ marginBottom: 16}} title="拆分模式配置">
        <Row gutter={16} align="middle">
          <Col span={4}>
            <Select 
              value={splitMethod} 
              onChange={(v) => { setSplitMethod(v as any); setPreview(null); }}
              style={{ width: 120 }}
            >
              <Select.Option value="simple">数量拆分</Select.Option>
              <Select.Option value="by_routing">工序拆分</Select.Option>
              <Select.Option value="by_batch">批次拆分</Select.Option>
              <Select.Option value="by_ratio">比例拆分</Select.Option>
            </Select>
          </Col>
          <Col span={20}>
            {renderParamsForm()}
          </Col>
        </Row>
        <Row style={{ marginTop: 16 }}>
          <Button type="primary" icon={ReloadOutlined} onClick={previewSplit}>
            预览拆分结果
          </Button>
        </Row>
      </Card>

      {/* 预览区域 */}
      {preview && (
        <Card title="拆分预览" style={{ marginBottom: 16 }}>
          <Table
            dataSource={[...[preview.master_wo], ...preview.children.map(c => ({...c, isMaster: false}))]}
            columns={[
              { title: '工单号', dataIndex: 'code', key: 'code', width: 200 },
              { title: '计划量', dataIndex: 'planned_qty', key: 'qty', width: 120, align: 'right' },
              { title: '状态', dataIndex: 'status', key: 'status', width: 100 },
            ]}
            row={(record) => record.isMaster ? { background: '#f0f8ff' } : {}}
          />
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={12}>
              <div><Text>主工单剩余：</Text>{preview.master_wo.new_planned_qty} {workOrder.unit || 'pcs'}</div>
              <div><Text>预计生成子工单：</Text>{preview.total_children} 个</div>
            </Col>
            <Col span={12} style={{ textAlign: 'right' }}>
              <Button type="primary" onClick={executeSplit}>
                确认执行拆分
              </Button>
            </Col>
          </Row>
        </Card>
      )}

      {/* 树形视图切换 */}
      <Card title="父子关系树形图">
        <Row gutter={8} style={{ marginBottom: 16 }}>
          <Col>
            <Button type={treeView ? 'primary' : 'dashed'} icon={<TreeOutlined />} onClick={() => setTreeView(!treeView)}>
              {treeView ? '收起树形' : '展开树形'}
            </Button>
            <Button type={historyView ? 'primary' : 'dashed'} icon={<HistoryOutlined />} style={{ marginLeft: 8 }} onClick={() => setHistoryView(!historyView)}>
              {historyView ? '收起历史' : '查看历史'}
            </Button>
          </Col>
        </Row>
        
        {treeView && (
          <div style={{ padding: 16, border: '1px solid #f0f0f0', borderRadius: 4, maxHeight: 400, overflow: 'auto' }}>
            {window.currentWoTree ? (
              <Tree 
                treeData={buildTreeData(window.currentWoTree)} 
                expandedKeys={window.currentWoTree.master_wo.code ? [window.currentWoTree.master_wo.code] : []}
                onExpand={(expandedKeys) => console.log('Expanded:', expandedKeys)}
              />
            ) : (
              <Text type="secondary">暂无子工单</Text>
            )}
          </div>
        )}

        {historyView && (
          <div style={{ marginTop: 16 }}>
            <Table
              dataSource={historyList}
              columns={[
                { title: '时间', dataIndex: 'created_at', key: 'created_time', render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm') },
                { title: '动作', dataIndex: 'action', key: 'action', width: 100 },
                { title: '结果', dataIndex: 'result', key: 'result', width: 200 },
                { title: '操作人', dataIndex: 'operator', key: 'operator', width: 120 },
              ]}
            />
          </div>
        )}
      </Card>
    </div>
  )
}

export default WorkOrderSplitPage
