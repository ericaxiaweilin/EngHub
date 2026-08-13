import React, { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Card, Empty, Form, Input, InputNumber, List, Modal, Select, Space, Spin, Tag, Typography, message } from 'antd'
import { DownloadOutlined, FileExcelOutlined, ImportOutlined, ReloadOutlined, SaveOutlined } from '@ant-design/icons'
import type { SpreadsheetEditorHandle } from '../../components/SpreadsheetEditor'
import { workbooksApi, type WorkbookMeta } from '../../services/workbooks'

const SpreadsheetEditor = lazy(() => import('../../components/SpreadsheetEditor'))
const { Text } = Typography
const ACTIVE_WORKBOOK_KEY = 'enghub-active-workbook-id'

const downloadExport = async (id: string, name: string) => {
  const token = localStorage.getItem('token')
  const response = await fetch(`/api/v1/workbooks/${id}/export`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${name || 'workbook'}.xlsx`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export default function PmcWorkbookPanel() {
  const editorRef = useRef<SpreadsheetEditorHandle>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [workbooks, setWorkbooks] = useState<WorkbookMeta[]>([])
  const [selected, setSelected] = useState<WorkbookMeta | null>(null)
  const [snapshot, setSnapshot] = useState<Record<string, any> | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editorRevision, setEditorRevision] = useState(0)
  const [pivotOpen, setPivotOpen] = useState(false)
  const [pivotLoading, setPivotLoading] = useState(false)
  const [pivotSheetName, setPivotSheetName] = useState('')
  const [flashFillOpen, setFlashFillOpen] = useState(false)
  const [flashFillLoading, setFlashFillLoading] = useState(false)
  const [pivotForm] = Form.useForm()
  const [flashFillForm] = Form.useForm()

  const sheetOptions = useMemo(() => {
    if (!snapshot) return []
    const sheets = snapshot.sheets || {}
    const order = snapshot.sheetOrder || Object.keys(sheets)
    return order.map((id: string) => sheets[id]).filter(Boolean).map((sheet: any) => ({ value: sheet.name, label: sheet.name }))
  }, [snapshot])

  const headersForSheet = (name: string) => {
    if (!snapshot) return []
    const sheets = snapshot.sheets || {}
    const sheet = Object.values(sheets).find((item: any) => item?.name === name) as any
    const headerRow = sheet?.cellData?.['0'] || {}
    return Object.keys(headerRow).sort((a, b) => Number(a) - Number(b)).map((key) => String(headerRow[key]?.v || '')).filter(Boolean)
  }

  const pivotHeaderOptions = useMemo(() => headersForSheet(pivotSheetName).map((value) => ({ value, label: value })), [snapshot, pivotSheetName])

  const adoptSnapshot = (next: Record<string, any>) => {
    setSnapshot(next)
    setEditorRevision((value) => value + 1)
  }

  const loadList = async () => {
    try {
      const result = await workbooksApi.list()
      setWorkbooks(result.workbooks || [])
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '在线工作簿列表加载失败')
    }
  }

  const openWorkbook = async (meta: WorkbookMeta) => {
    setLoading(true)
    try {
      const result = await workbooksApi.get(meta.id)
      setSelected(result)
      adoptSnapshot(result.snapshot)
      localStorage.setItem(ACTIVE_WORKBOOK_KEY, result.id)
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '工作簿打开失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadList() }, [])

  const importWorkbook = async (file?: File) => {
    if (!file) return
    setLoading(true)
    try {
      const result = await workbooksApi.import(file)
      setSelected(result)
      adoptSnapshot(result.snapshot)
      localStorage.setItem(ACTIVE_WORKBOOK_KEY, result.id)
      await loadList()
      message.success(`已导入 ${file.name}，公式和工作表已保留`)
    } catch (error: any) {
      message.error(error?.response?.data?.detail || 'XLSX 导入失败')
    } finally {
      setLoading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const createPmcTemplate = async () => {
    setLoading(true)
    try {
      const result = await workbooksApi.createPmcTemplate()
      setSelected(result)
      adoptSnapshot(result.snapshot)
      localStorage.setItem(ACTIVE_WORKBOOK_KEY, result.id)
      await loadList()
      message.success('PMC 模板已创建：BOM、订单池、库存、MRP、产能负荷及 VLOOKUP/XLOOKUP/SUMIFS 练习已预置')
    } catch (error: any) {
      message.error(error?.response?.data?.detail || 'PMC 模板创建失败')
    } finally {
      setLoading(false)
    }
  }

  const saveCurrentSnapshot = async () => {
    if (!selected || !editorRef.current) throw new Error('无法读取当前工作簿')
    const next = editorRef.current.getWorkbookSnapshot()
    if (!next) throw new Error('无法读取当前工作簿')
    await workbooksApi.update(selected.id, { snapshot: next })
    adoptSnapshot(next)
    return next
  }

  const saveWorkbook = async () => {
    setSaving(true)
    try {
      await saveCurrentSnapshot()
      message.success('工作簿已保存，公式和多 Sheet 快照已写入系统')
      await loadList()
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '工作簿保存失败')
    } finally {
      setSaving(false)
    }
  }

  const openPivot = () => {
    const firstSheet = sheetOptions[0]?.value || ''
    const headers = headersForSheet(firstSheet)
    setPivotSheetName(firstSheet)
    pivotForm.setFieldsValue({ sheet: firstSheet, row_field: headers[0], value_field: headers[1], aggregation: 'sum', output_sheet_name: '透视汇总' })
    setPivotOpen(true)
  }

  const runPivot = async (values: any) => {
    if (!selected) return
    setPivotLoading(true)
    try {
      await saveCurrentSnapshot()
      const result = await workbooksApi.pivot(selected.id, values)
      adoptSnapshot(result.snapshot)
      setPivotOpen(false)
      await loadList()
      message.success(`透视汇总已生成：${result.summary?.groups || 0} 个分组`)
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '透视汇总失败')
    } finally {
      setPivotLoading(false)
    }
  }

  const openFlashFill = () => {
    const firstSheet = sheetOptions[0]?.value || ''
    setPivotSheetName(firstSheet)
    flashFillForm.setFieldsValue({ sheet: firstSheet, source_column: 'A', target_column: 'B', start_row: 2, end_row: 201, overwrite: false })
    setFlashFillOpen(true)
  }

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'e' && selected && snapshot) {
        event.preventDefault()
        openFlashFill()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [selected, snapshot])

  const runFlashFill = async (values: any) => {
    if (!selected) return
    setFlashFillLoading(true)
    try {
      await saveCurrentSnapshot()
      const result = await workbooksApi.operations(selected.id, [{ type: 'flash_fill', ...values }])
      adoptSnapshot(result.snapshot)
      setFlashFillOpen(false)
      message.success(`快速填充完成：${result.changed?.[0]?.filled || 0} 个单元格`)
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '快速填充失败')
    } finally {
      setFlashFillLoading(false)
    }
  }

  const exportWorkbook = async () => {
    if (!selected) return
    try {
      await downloadExport(selected.id, selected.name)
      message.success('XLSX 已导出')
    } catch {
      message.error('XLSX 导出失败')
    }
  }

  return (
    <Card size="small" title={<Space><FileExcelOutlined /> PMC 在线工作簿</Space>}>
      <Alert
        type="info"
        showIcon
        message="XLSX 导入会保留公式、多个 Sheet、基础样式、行列宽和冻结窗格"
        description="保存后可导出为 XLSX；当前工作簿会绑定到 Chatbot，支持 VLOOKUP/XLOOKUP/SUMIFS 公式、透视汇总和 Ctrl+E 快速填充。XLSM 的 VBA/宏不进入在线快照，请保留原始宏文件。"
        style={{ marginBottom: 16 }}
      />
      <Space wrap style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<ImportOutlined />} onClick={() => fileRef.current?.click()} loading={loading}>导入 XLSX / XLSM</Button>
        <Button icon={<FileExcelOutlined />} onClick={createPmcTemplate} loading={loading}>新建 PMC 模板</Button>
        <input ref={fileRef} type="file" accept=".xlsx,.xlsm" hidden onChange={(event) => importWorkbook(event.target.files?.[0])} />
        <Button icon={<ReloadOutlined />} onClick={loadList} loading={loading}>刷新工作簿</Button>
        {selected && <>
          <Button icon={<SaveOutlined />} onClick={saveWorkbook} loading={saving}>保存工作簿</Button>
          <Button onClick={openPivot}>透视汇总</Button>
          <Button onClick={openFlashFill}>Ctrl+E 快速填充</Button>
          <Button icon={<DownloadOutlined />} onClick={exportWorkbook}>导出 XLSX</Button>
          <Tag color="blue">Chatbot 已绑定：{selected.name}</Tag>
        </>}
      </Space>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 280px) 1fr', gap: 16, minHeight: 500 }}>
        <Card size="small" title="工作簿列表" bodyStyle={{ padding: 0 }}>
          <List
            size="small"
            loading={loading && !snapshot}
            dataSource={workbooks}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请导入第一个 XLSX" /> }}
            renderItem={(item) => <List.Item style={{ padding: '10px 12px', cursor: 'pointer', background: selected?.id === item.id ? '#e6f4ff' : undefined }} onClick={() => openWorkbook(item)}>
              <List.Item.Meta title={item.name} description={<Text type="secondary" style={{ fontSize: 11 }}>{item.updated_at?.slice(0, 16) || '-'}</Text>} />
            </List.Item>}
          />
        </Card>
        <Card size="small" title={selected ? `${selected.name} · 在线编辑` : '请选择或导入工作簿'} bodyStyle={{ padding: 8 }}>
          {snapshot ? <Suspense fallback={<div style={{ height: 480, display: 'grid', placeItems: 'center' }}><Spin tip="加载在线工作表..." /></div>}>
            <SpreadsheetEditor key={`${selected?.id}-${editorRevision}`} ref={editorRef} initialWorkbook={snapshot} height={520} sheetName={selected?.name || 'PMC'} />
          </Suspense> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="导入外部 XLSX 后在这里编辑" />}
        </Card>
      </div>
      <Modal title="基础透视汇总" open={pivotOpen} onCancel={() => setPivotOpen(false)} onOk={() => pivotForm.submit()} confirmLoading={pivotLoading} destroyOnClose>
        <Alert type="info" showIcon message="把明细表按行字段分组，生成新的透视汇总 Sheet" style={{ marginBottom: 16 }} />
        <Form form={pivotForm} layout="vertical" onFinish={runPivot}>
          <Form.Item name="sheet" label="明细 Sheet" rules={[{ required: true }]}>
            <Select options={sheetOptions} onChange={(value) => {
              setPivotSheetName(value)
              const headers = headersForSheet(value)
              pivotForm.setFieldsValue({ row_field: headers[0], value_field: headers[1] })
            }} />
          </Form.Item>
          <Form.Item name="row_field" label="分组字段" rules={[{ required: true }]}><Select options={pivotHeaderOptions} /></Form.Item>
          <Form.Item name="value_field" label="汇总字段" rules={[{ required: true }]}><Select options={pivotHeaderOptions} /></Form.Item>
          <Form.Item name="aggregation" label="汇总方式" rules={[{ required: true }]}><Select options={[{ value: 'sum', label: '求和' }, { value: 'count', label: '计数' }, { value: 'avg', label: '平均值' }]} /></Form.Item>
          <Form.Item name="output_sheet_name" label="输出 Sheet 名称" rules={[{ required: true }]}><Input /></Form.Item>
        </Form>
      </Modal>
      <Modal title="Ctrl+E 快速填充" open={flashFillOpen} onCancel={() => setFlashFillOpen(false)} onOk={() => flashFillForm.submit()} confirmLoading={flashFillLoading} destroyOnClose>
        <Alert type="info" showIcon message="先在目标列填写至少两行示例，再执行填充。例如 A1001-2024-01 → 2024。" style={{ marginBottom: 16 }} />
        <Form form={flashFillForm} layout="vertical" onFinish={runFlashFill}>
          <Form.Item name="sheet" label="工作表" rules={[{ required: true }]}><Select options={sheetOptions} /></Form.Item>
          <Space style={{ display: 'flex' }} align="start">
            <Form.Item name="source_column" label="源列" rules={[{ required: true }]}><Input placeholder="A" /></Form.Item>
            <Form.Item name="target_column" label="目标列" rules={[{ required: true }]}><Input placeholder="B" /></Form.Item>
          </Space>
          <Space style={{ display: 'flex' }} align="start">
            <Form.Item name="start_row" label="开始行" rules={[{ required: true }]}><InputNumber min={1} /></Form.Item>
            <Form.Item name="end_row" label="结束行" rules={[{ required: true }]}><InputNumber min={1} /></Form.Item>
          </Space>
        </Form>
      </Modal>
    </Card>
  )
}
