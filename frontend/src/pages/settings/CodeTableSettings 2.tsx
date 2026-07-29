/**
 * 系统设置 - 码表管理（基础数据管理）
 * 统一维护工单类型、工序代码、优先级、工单状态等枚举字典
 * 支持自定义扩展，告别硬编码散落
 */
import React, { useState, useEffect, useCallback } from 'react'
import {
  Card, Tabs, Table, Button, Modal, Form, Input, InputNumber, Switch,
  Tag, Space, Popconfirm, message, Tooltip, Badge,
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined, SettingOutlined,
  LockOutlined,
} from '@ant-design/icons'
import {
  getCategories, getCodeTableItems, createCodeTableItem, updateCodeTableItem,
  deleteCodeTableItem, CodeTableItem, CategoryInfo, CATEGORY_LABELS,
} from '../../services/codeTable'
import { getStoredUser } from '../../services/auth'

const CodeTableSettings: React.FC = () => {
  const [categories, setCategories] = useState<CategoryInfo[]>([])
  const [activeTab, setActiveTab] = useState('wo_type')
  const [items, setItems] = useState<CodeTableItem[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingItem, setEditingItem] = useState<CodeTableItem | null>(null)
  const [showInactive, setShowInactive] = useState(false)
  const [form] = Form.useForm()

  const user = getStoredUser()
  const isAdmin = user?.role === 'admin' || user?.role === 'super_admin'

  // 加载分类列表
  const loadCategories = useCallback(async () => {
    try {
      const res = await getCategories()
      setCategories(res || [])
    } catch { /* ignore */ }
  }, [])

  // 加载当前分类条目
  const loadItems = useCallback(async (category: string, includeInactive = false) => {
    setLoading(true)
    try {
      const res = await getCodeTableItems(category, includeInactive)
      setItems(res.items || [])
    } catch {
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadCategories() }, [loadCategories])
  useEffect(() => { loadItems(activeTab, showInactive) }, [activeTab, showInactive, loadItems])

  // 新增/编辑弹窗
  const openModal = (item?: CodeTableItem) => {
    setEditingItem(item || null)
    if (item) {
      form.setFieldsValue({
        code: item.code,
        name: item.name,
        name_en: item.name_en,
        description: item.description,
        keywords: item.keywords?.join(', ') || '',
        sort_order: item.sort_order,
        is_active: item.is_active,
      })
    } else {
      form.resetFields()
      form.setFieldsValue({ sort_order: 0, is_active: true })
    }
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      const payload = {
        code: values.code,
        name: values.name,
        name_en: values.name_en || undefined,
        description: values.description || undefined,
        keywords: values.keywords ? values.keywords.split(',').map((s: string) => s.trim()).filter(Boolean) : undefined,
        sort_order: values.sort_order ?? 0,
        is_active: values.is_active ?? true,
      }

      if (editingItem) {
        await updateCodeTableItem(activeTab, editingItem.id, payload)
        message.success('更新成功')
      } else {
        await createCodeTableItem(activeTab, payload)
        message.success('新增成功')
      }
      setModalOpen(false)
      loadItems(activeTab, showInactive)
      loadCategories()
    } catch (err: any) {
      if (err?.response?.data?.detail) message.error(err.response.data.detail)
    }
  }

  const handleDelete = async (item: CodeTableItem) => {
    try {
      await deleteCodeTableItem(activeTab, item.id)
      message.success('已删除')
      loadItems(activeTab, showInactive)
      loadCategories()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '删除失败')
    }
  }

  const handleToggleActive = async (item: CodeTableItem, checked: boolean) => {
    try {
      await updateCodeTableItem(activeTab, item.id, { is_active: checked })
      message.success(checked ? '已启用' : '已停用')
      loadItems(activeTab, showInactive)
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '操作失败')
    }
  }

  // 列定义
  const columns = [
    {
      title: '编码', dataIndex: 'code', key: 'code', width: 100,
      render: (t: string, r: CodeTableItem) => (
        <Space>
          <Tag color="blue" style={{ fontFamily: 'monospace', fontWeight: 600 }}>{t}</Tag>
          {r.is_system && <Tooltip title="系统内置"><LockOutlined style={{ color: '#999', fontSize: 12 }} /></Tooltip>}
        </Space>
      ),
    },
    { title: '中文名称', dataIndex: 'name', key: 'name', width: 120 },
    { title: '英文名称', dataIndex: 'name_en', key: 'name_en', width: 180, render: (t: string) => t || '-' },
    {
      title: '关键词', dataIndex: 'keywords', key: 'keywords', width: 200,
      render: (kws: string[]) => kws?.length
        ? kws.slice(0, 4).map(k => <Tag key={k} style={{ fontSize: 11 }}>{k}</Tag>)
        : '-',
    },
    { title: '排序', dataIndex: 'sort_order', key: 'sort', width: 60 },
    {
      title: '状态', key: 'active', width: 80,
      render: (_: any, r: CodeTableItem) => (
        <Switch
          size="small"
          checked={r.is_active}
          disabled={!isAdmin}
          onChange={(v) => handleToggleActive(r, v)}
        />
      ),
    },
    {
      title: '操作', key: 'action', width: 100,
      render: (_: any, r: CodeTableItem) => (
        <Space size={4}>
          {isAdmin && (
            <Tooltip title="编辑">
              <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openModal(r)} />
            </Tooltip>
          )}
          {isAdmin && !r.is_system && (
            <Popconfirm title="确认删除？" onConfirm={() => handleDelete(r)} okText="删除" cancelText="取消">
              <Button type="link" size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  // Tab 项
  const tabItems = categories.map(c => ({
    key: c.category,
    label: (
      <span>
        {CATEGORY_LABELS[c.category] || c.category}
        <Badge count={c.count} size="small" style={{ marginLeft: 6, backgroundColor: '#e6f7ff', color: '#1890ff' }} />
      </span>
    ),
  }))

  return (
    <div style={{ padding: '0' }}>
      <Card
        title={<><SettingOutlined /> 码表管理（基础数据）</>}
        extra={
          <Space>
            <span style={{ fontSize: 12, color: '#999' }}>显示已停用</span>
            <Switch size="small" checked={showInactive} onChange={setShowInactive} />
            {isAdmin && (
              <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => openModal()}>
                新增
              </Button>
            )}
          </Space>
        }
      >
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={tabItems}
          size="small"
          style={{ marginBottom: 8 }}
        />
        <Table
          dataSource={items}
          columns={columns}
          rowKey="id"
          size="small"
          loading={loading}
          pagination={false}
          scroll={{ y: 480 }}
        />
      </Card>

      {/* 新增/编辑弹窗 */}
      <Modal
        title={editingItem ? `编辑 - ${CATEGORY_LABELS[activeTab] || activeTab}` : `新增 - ${CATEGORY_LABELS[activeTab] || activeTab}`}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
        width={520}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="code" label="编码"
            rules={[{ required: true, message: '请输入编码' }]}
            extra={editingItem?.is_system ? '系统内置编码不可修改' : '英文大写，如 INJ、SMT'}
          >
            <Input
              placeholder="如 INJ"
              disabled={editingItem?.is_system}
              style={{ fontFamily: 'monospace' }}
            />
          </Form.Item>
          <Form.Item name="name" label="中文名称" rules={[{ required: true, message: '请输入中文名称' }]}>
            <Input placeholder="如 注塑" />
          </Form.Item>
          <Form.Item name="name_en" label="英文名称">
            <Input placeholder="如 Injection Molding" />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} placeholder="补充描述（可选）" />
          </Form.Item>
          {activeTab === 'process_code' && (
            <Form.Item name="keywords" label="匹配关键词" extra="逗号分隔，用于工艺路线工序名自动解析匹配">
              <Input placeholder="如 注塑,注射,inj,mold" />
            </Form.Item>
          )}
          <Form.Item name="sort_order" label="排序号">
            <InputNumber min={0} max={999} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default CodeTableSettings
