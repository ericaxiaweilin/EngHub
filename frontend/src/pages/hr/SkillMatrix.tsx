import React, { useEffect, useState } from 'react'
import { Card, Table, Tag, Row, Col, Statistic, Empty, Alert } from 'antd'
import { getSkillMatrix, getExpiringCerts, listSkills } from '../../services/modules'

const levelColor: Record<string, string> = {
  '1': 'default', '2': 'blue', '3': 'cyan', '4': 'green', '5': 'gold',
  beginner: 'default', intermediate: 'blue', advanced: 'green', expert: 'gold',
}

const SkillMatrix: React.FC = () => {
  const [matrix, setMatrix] = useState<any[]>([])
  const [skills, setSkills] = useState<any[]>([])
  const [expiring, setExpiring] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
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
  }, [])

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>员工技能矩阵</h2>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}><Card><Statistic title="技能项" value={skills.length} /></Card></Col>
        <Col span={8}><Card><Statistic title="员工记录" value={matrix.length} /></Card></Col>
        <Col span={8}><Card><Statistic title="即将到期认证" value={expiring.length} valueStyle={{ color: expiring.length ? '#faad14' : undefined }} /></Card></Col>
      </Row>

      {expiring.length > 0 && (
        <Alert type="warning" style={{ marginBottom: 16 }}
          message={`有 ${expiring.length} 项认证即将到期，请及时安排复训`} showIcon />
      )}

      <Card title="技能矩阵" style={{ marginBottom: 16 }}>
        <Table
          rowKey={(r) => r.user_id || r.employee_id || JSON.stringify(r)} loading={loading} dataSource={matrix}
          locale={{ emptyText: <Empty description="暂无技能矩阵数据" /> }}
          columns={[
            { title: '员工', dataIndex: 'user_name', render: (v: string, r: any) => v || r.user_id || '-' },
            { title: '技能', dataIndex: 'skill_name', render: (v: string, r: any) => v || r.skill_id || '-' },
            { title: '等级', dataIndex: 'level', render: (v: any) => <Tag color={levelColor[String(v)] || 'default'}>{v ?? '-'}</Tag> },
            { title: '认证', dataIndex: 'certified', render: (v: boolean) => (v ? <Tag color="success">已认证</Tag> : <Tag>未认证</Tag>) },
            { title: '到期日', dataIndex: 'expiry_date', render: (v: string) => v || '-' },
          ]}
        />
      </Card>

      <Card title="即将到期认证">
        <Table
          size="small" rowKey={(r) => JSON.stringify(r)} dataSource={expiring}
          locale={{ emptyText: '无即将到期认证' }}
          columns={[
            { title: '员工', dataIndex: 'user_name', render: (v: string, r: any) => v || r.user_id || '-' },
            { title: '技能/认证', dataIndex: 'skill_name', render: (v: string, r: any) => v || r.certification_name || '-' },
            { title: '到期日', dataIndex: 'expiry_date' },
            { title: '剩余天数', dataIndex: 'days_remaining', render: (v: number) => <Tag color={v < 30 ? 'error' : 'warning'}>{v ?? '-'}</Tag> },
          ]}
        />
      </Card>
    </div>
  )
}

export default SkillMatrix
