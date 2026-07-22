import React, { useEffect, useState, useMemo } from 'react'
import {
  Card, Table, Tag, Row, Col, Statistic, Empty, Alert, Progress,
  Space, Tooltip, Badge, Typography, Segmented, Button,
} from 'antd'
import {
  TeamOutlined, SafetyCertificateOutlined, WarningOutlined,
  TrophyOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { getSkillMatrix, getExpiringCerts, listSkills } from '../../services/modules'

const { Text } = Typography

const levelColor: Record<string, string> = {
  '1': 'default', '2': 'blue', '3': 'cyan', '4': 'green', '5': 'gold',
  beginner: 'default', intermediate: 'blue', advanced: 'green', expert: 'gold',
}

const levelText: Record<string, string> = {
  '1': 'L1 入门', '2': 'L2 熟练', '3': 'L3 精通', '4': 'L4 专家', '5': 'L5 大师',
  beginner: '入门', intermediate: '熟练', advanced: '精通', expert: '专家',
}

const SkillMatrix: React.FC = () => {
  const [matrix, setMatrix] = useState<any[]>([])
  const [skills, setSkills] = useState<any[]>([])
  const [expiring, setExpiring] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [view, setView] = useState<string>('matrix')

  const fetchData = () => {
    setLoading(true)
    Promise.allSettled([getSkillMatrix(), listSkills(), getExpiringCerts()]).then((res) => {
      if (res[0].status === 'fulfilled') setMatrix((res[0].value as any[]) || [])
      if (res[1].status === 'fulfilled') setSkills((res[1].value as any[]) || [])
      if (res[2].status === 'fulfilled') {
        const v: any = res[2].value
        setExpiring(Array.isArray(v) ? v : v?.items || [])
      }
      setLoading(false)
    })
  }

  useEffect(() => { fetchData() }, [])

  /* ── 等级分布统计 ── */
  const levelDist = useMemo(() => {
    const dist: Record<string, number> = {}
    matrix.forEach(m => {
      const lv = String(m.level ?? 'unknown')
      dist[lv] = (dist[lv] || 0) + 1
    })
    return dist
  }, [matrix])

  const certifiedCount = matrix.filter(m => m.certified).length
  const certRate = matrix.length ? Math.round((certifiedCount / matrix.length) * 100) : 0

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>员工技能矩阵</h2>
        <Button icon={<ReloadOutlined />} onClick={fetchData}>刷新</Button>
      </div>

      {/* 统计卡 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="技能项" value={skills.length} prefix={<TrophyOutlined style={{ color: '#faad14' }} />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="员工记录" value={matrix.length} prefix={<TeamOutlined style={{ color: '#1890ff' }} />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="认证率" value={certRate} suffix="%"
              valueStyle={{ color: certRate >= 80 ? '#52c41a' : certRate >= 50 ? '#faad14' : '#f5222d' }}
              prefix={<SafetyCertificateOutlined />} />
            <Progress percent={certRate} size="small" showInfo={false}
              strokeColor={certRate >= 80 ? '#52c41a' : certRate >= 50 ? '#faad14' : '#f5222d'} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="即将到期认证" value={expiring.length}
              valueStyle={{ color: expiring.length ? '#faad14' : undefined }}
              prefix={<WarningOutlined style={{ color: expiring.length ? '#faad14' : '#d9d9d9' }} />} />
          </Card>
        </Col>
      </Row>

      {/* 到期预警 */}
      {expiring.length > 0 && (
        <Alert type="warning" style={{ marginBottom: 16 }} showIcon
          message={`有 ${expiring.length} 项认证即将到期，请及时安排复训`}
          description={
            <Space wrap size={4}>
              {expiring.slice(0, 5).map((e, i) => (
                <Tag key={i} color={e.days_remaining < 30 ? 'error' : 'warning'}>
                  {e.user_name || e.user_id} · {e.skill_name || e.certification_name} · 剩 {e.days_remaining} 天
                </Tag>
              ))}
              {expiring.length > 5 && <Tag>+{expiring.length - 5} 更多</Tag>}
            </Space>
          }
        />
      )}

      {/* 视图切换 */}
      <div style={{ marginBottom: 16 }}>
        <Segmented
          value={view}
          onChange={(v) => setView(v as string)}
          options={[
            { label: '技能矩阵', value: 'matrix' },
            { label: '等级分布', value: 'distribution' },
            { label: '到期认证', value: 'expiring' },
          ]}
        />
      </div>

      {/* 技能矩阵表 */}
      {view === 'matrix' && (
        <Card title="技能矩阵" size="small">
          <Table
            rowKey={(r) => r.user_id || r.employee_id || JSON.stringify(r)}
            loading={loading}
            dataSource={matrix}
            locale={{ emptyText: <Empty description="暂无技能矩阵数据" /> }}
            pagination={{ pageSize: 10, showTotal: t => `共 ${t} 条` }}
            columns={[
              {
                title: '员工', dataIndex: 'user_name', width: 120,
                render: (v: string, r: any) => (
                  <Space>
                    <TeamOutlined style={{ color: '#1890ff' }} />
                    <Text strong>{v || r.user_id || '-'}</Text>
                  </Space>
                ),
              },
              {
                title: '技能', dataIndex: 'skill_name', width: 150,
                render: (v: string, r: any) => <Tag>{v || r.skill_id || '-'}</Tag>,
              },
              {
                title: '等级', dataIndex: 'level', width: 120,
                render: (v: any) => {
                  const key = String(v)
                  return (
                    <Tooltip title={`等级 ${v}`}>
                      <Tag color={levelColor[key] || 'default'}>
                        {levelText[key] || `L${v}`}
                      </Tag>
                    </Tooltip>
                  )
                },
              },
              {
                title: '认证状态', dataIndex: 'certified', width: 100, align: 'center',
                render: (v: boolean) => v
                  ? <Tag color="success" icon={<SafetyCertificateOutlined />}>已认证</Tag>
                  : <Tag>未认证</Tag>,
              },
              {
                title: '到期日', dataIndex: 'expiry_date', width: 120,
                render: (v: string) => {
                  if (!v) return '-'
                  const days = Math.ceil((new Date(v).getTime() - Date.now()) / 86400000)
                  return (
                    <Space size={4}>
                      <span>{v}</span>
                      {days < 30 && <Badge count={`${days}天`} color={days < 7 ? '#f5222d' : '#faad14'} />}
                    </Space>
                  )
                },
              },
            ]}
          />
        </Card>
      )}

      {/* 等级分布 */}
      {view === 'distribution' && (
        <Card title="技能等级分布" size="small">
          {Object.keys(levelDist).length === 0 ? (
            <Empty description="暂无数据" />
          ) : (
            <Row gutter={16}>
              {Object.entries(levelDist)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([level, count]) => {
                  const pct = matrix.length ? Math.round((count / matrix.length) * 100) : 0
                  return (
                    <Col span={4} key={level}>
                      <Card size="small" style={{ textAlign: 'center' }}>
                        <Progress
                          type="circle"
                          percent={pct}
                          size={80}
                          strokeColor={
                            level === '5' || level === 'expert' ? '#faad14'
                            : level === '4' || level === 'advanced' ? '#52c41a'
                            : level === '3' || level === 'intermediate' ? '#13c2c2'
                            : '#1890ff'
                          }
                          format={() => String(count)}
                        />
                        <div style={{ marginTop: 8 }}>
                          <Tag color={levelColor[level] || 'default'}>
                            {levelText[level] || `L${level}`}
                          </Tag>
                        </div>
                      </Card>
                    </Col>
                  )
                })}
            </Row>
          )}
        </Card>
      )}

      {/* 到期认证 */}
      {view === 'expiring' && (
        <Card title="即将到期认证" size="small">
          <Table
            size="small"
            rowKey={(r) => JSON.stringify(r)}
            dataSource={expiring}
            loading={loading}
            locale={{ emptyText: <Empty description="无即将到期认证" /> }}
            pagination={{ pageSize: 10 }}
            columns={[
              {
                title: '员工', dataIndex: 'user_name', width: 120,
                render: (v: string, r: any) => <Text strong>{v || r.user_id || '-'}</Text>,
              },
              {
                title: '技能/认证', dataIndex: 'skill_name', width: 150,
                render: (v: string, r: any) => <Tag color="blue">{v || r.certification_name || '-'}</Tag>,
              },
              { title: '到期日', dataIndex: 'expiry_date', width: 120 },
              {
                title: '剩余天数', dataIndex: 'days_remaining', width: 100, align: 'center',
                render: (v: number) => (
                  <Tag color={v < 7 ? 'error' : v < 30 ? 'warning' : 'success'}>
                    {v ?? '-'} 天
                  </Tag>
                ),
              },
              {
                title: '紧急度', key: 'urgency', width: 100,
                render: (_: any, r: any) => {
                  const d = r.days_remaining
                  if (d < 7) return <Tag color="error">紧急</Tag>
                  if (d < 30) return <Tag color="warning">关注</Tag>
                  return <Tag color="success">正常</Tag>
                },
              },
            ]}
          />
        </Card>
      )}
    </div>
  )
}

export default SkillMatrix
