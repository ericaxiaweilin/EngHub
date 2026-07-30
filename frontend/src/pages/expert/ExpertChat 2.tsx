


import { useState } from 'react'
import { Card, Input, Select, Button, Space, Tag, Alert, Spin, Tabs } from 'antd'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1/expert-system'

export default function ExpertSystemChat() {
  const [query, setQuery] = useState('')
  const [industry, setIndustry] = useState('mold')
  const [expertMode, setExpertMode] = useState('hybrid')
  const [params, setParams] = useState('{\n  "spindle_rpm": 16000,\n  "edm_gap_voltage": 130\n}')
  const [result, setResult] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleAnswer = async () => {
    try {
      setLoading(true)
      setError(null)
      let parsedParams: Record<string, any> = {}
      if (params.trim()) {
        try {
          parsedParams = JSON.parse(params)
        } catch {
          setError('工艺参数 JSON 格式错误，请检查')
          return
        }
      }

      const res = await axios.post(`${API_BASE}/answer`, {
        query,
        industry,
        params: parsedParams,
        expert_mode: expertMode,
      })
      setResult(res.data.data)
    } catch (err: any) {
      setError(err.response?.data?.detail || '请求失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card title="🔬 专家系统 — 混合推理" style={{ minHeight: 500 }}>
      {/* 模式选择 */}
      <Space style={{ marginBottom: 16 }}>
        <Select
          value={industry}
          onChange={setIndustry}
          options={[
            { label: '🏭 模具厂', value: 'mold' },
            { label: '📱 电子厂', value: 'electronics' },
            { label: '⚽ 运动器材厂', value: 'sporting_goods' },
          ]}
        />
        <Select
          value={expertMode}
          onChange={setExpertMode}
          options={[
            { label: '混合推理 (规则+AI)', value: 'hybrid' },
            { label: '纯规则模式', value: 'rules_only' },
            { label: 'AI优先模式', value: 'ai_first' },
          ]}
        />
      </Space>

      {/* 输入区 */}
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Input.TextArea
          rows={3}
          placeholder="请输入生产相关问题，如：回流焊峰值温度设置多少？SMT贴片后AOI灵敏度应该调多少？"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        <Input.TextArea
          rows={4}
          placeholder="工艺参数（JSON格式，可选）"
          value={params}
          onChange={e => setParams(e.target.value)}
          style={{ fontFamily: 'monospace', fontSize: 12 }}
        />
        <Button type="primary" icon={<span>🤖</span>} onClick={handleAnswer} loading={loading} disabled={!query.trim()}>
          开始推理
        </Button>
      </Space>

      {/* 结果区 */}
      {error && <Alert message={error} type="error" showIcon style={{ marginTop: 16 }} />}
      {result && (
        <Card size="small" title="推理结果" style={{ marginTop: 16 }} bodyStyle={{ maxHeight: 400, overflow: 'auto' }}>
          <Tabs defaultActiveKey="summary">
            <Tabs.TabPane tab="总览" key="summary">
              <p><b>策略:</b> <Tag color={result.strategy === 'hybrid' ? 'blue' : result.strategy === 'rules_only' ? 'green' : 'purple'}>{result.strategy}</Tag></p>
              <p><b>阶段:</b> <Tag color="cyan">{result.phase}</Tag></p>
              {result.result?.overall_status && (
                <p><b>状态:</b> <Tag color={result.result.overall_status === 'failed' ? 'red' : 'green'}>{result.result.overall_status}</Tag></p>
              )}
              {result.result?.response && (
                <pre style={{ whiteSpace: 'pre-wrap' }}>{result.result.response}</pre>
              )}
            </Tabs.TabPane>

            <Tabs.TabPane tab="规则检查" key="rules">
              {result.result?.findings && result.result.findings.length > 0 ? (
                result.result.findings.map((f: any, i: number) => (
                  <div key={i} style={{ padding: 8, borderBottom: '1px solid #f0f0f0' }}>
                    <Tag color={f.severity === 'critical' ? 'red' : f.severity === 'warning' ? 'orange' : 'green'}>{f.rule_id}</Tag>
                    <div>{f.message}</div>
                    {f.suggestion && <div style={{ color: '#1890ff' }}>💡 {f.suggestion}</div>}
                  </div>
                ))
              ) : (
                <p>所有参数均符合行业标准。</p>
              )}
            </Tabs.TabPane>
          </Tabs>
        </Card>
      )}

      {!result && !error && !loading && (
        <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
          <p>输入问题，选择行业和推理模式，点击「开始推理」</p>
        </div>
      )}

      {loading && <Spin tip="正在推理..." />}
    </Card>
  )
}



