import React, { useState, useEffect } from 'react';
import { Card, Table, Button, Tag, Space, Input, Select, DatePicker, Modal, Form, message, Typography, Statistic, Row, Col, Descriptions } from 'antd';
import { PlusOutlined, EyeOutlined, ToolOutlined, CalendarOutlined, CheckCircleOutlined, ClockCircleOutlined, PlayCircleOutlined } from '@ant-design/icons';
import api from '../../services/api';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { RangePicker } = DatePicker;

interface MaintenanceTask {
  id: string;
  task_code: string;
  task_type: string;
  priority: string;
  equipment_id: string;
  equipment_name: string;
  planned_date: string;
  status: string;
  assigned_to: string;
  result?: string;
  remark?: string;
  started_at?: string;
  completed_at?: string;
  created_at?: string;
}

const TYPE_MAP: Record<string, { label: string; color: string }> = {
  inspection: { label: '点检', color: 'blue' },
  lubrication: { label: '润滑', color: 'cyan' },
  calibration: { label: '校准', color: 'purple' },
  repair: { label: '维修', color: 'orange' },
  preventive: { label: '预防保养', color: 'geekblue' },
};

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  pending: { label: '待执行', color: 'default' },
  assigned: { label: '已指派', color: 'blue' },
  in_progress: { label: '进行中', color: 'orange' },
  completed: { label: '已完成', color: 'green' },
};

const PRIORITY_MAP: Record<string, { label: string; color: string }> = {
  high: { label: '高', color: 'red' },
  medium: { label: '中', color: 'orange' },
  low: { label: '低', color: 'green' },
};

const MaintenanceCenter: React.FC = () => {
  const [tasks, setTasks] = useState<MaintenanceTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [typeFilter, setTypeFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [stats, setStats] = useState<any>(null);
  const [equipmentOptions, setEquipmentOptions] = useState<{ value: string; label: string }[]>([]);
  const factoryId = (() => {
    const v = localStorage.getItem('active_factory_id');
    return v && v !== 'factory-sh-01' && v !== 'F01' ? v : 'FAC_MECH_001';
  })();

  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedTask, setSelectedTask] = useState<MaintenanceTask | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [createForm] = Form.useForm();

  const fetchTasks = async () => {
    setLoading(true);
    try {
      const params: any = {
        factory_id: factoryId,
        limit: pagination.pageSize,
        offset: (pagination.current - 1) * pagination.pageSize,
      };
      if (typeFilter) params.task_type = typeFilter;
      if (statusFilter) params.status = statusFilter;
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.date_from = dateRange[0].format('YYYY-MM-DD');
        params.date_to = dateRange[1].format('YYYY-MM-DD');
      }
      // api 实例响应拦截器已返回 response.data
      const data: any = await api.get('/api/v1/equipment/maintenance', { params });
      setTasks(data.tasks || []);
      setTotal(data.total || 0);
    } catch (error) {
      console.error('Failed to fetch maintenance tasks:', error);
      message.error('维保任务加载失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchStats = async () => {
    try {
      const data: any = await api.get('/api/v1/equipment/maintenance/stats', { params: { factory_id: factoryId } });
      setStats(data);
    } catch (error) {
      console.error('Failed to fetch stats:', error);
    }
  };

  const fetchEquipment = async () => {
    try {
      // 注意尾部斜杠：无斜杠会被 SPA fallback 吃掉
      const data: any = await api.get('/api/v1/equipment/', { params: { factory_id: factoryId, limit: 200 } });
      const list = data.equipment || [];
      setEquipmentOptions(list.map((e: any) => ({
        value: e.id,
        label: `${e.equipment_name || e.equipment_code}${e.equipment_code ? `（${e.equipment_code}）` : ''}`,
      })));
    } catch (error) {
      console.error('Failed to fetch equipment:', error);
    }
  };

  useEffect(() => {
    fetchTasks();
    fetchStats();
  }, [pagination, typeFilter, statusFilter, dateRange, factoryId]);

  useEffect(() => {
    fetchEquipment();
  }, [factoryId]);

  const handleTableChange = (pg: any) => {
    setPagination({ current: pg.current, pageSize: pg.pageSize });
  };

  const handleCreate = async (values: any) => {
    setSubmitLoading(true);
    try {
      const payload = {
        ...values,
        planned_date: values.planned_date ? values.planned_date.format('YYYY-MM-DD') : undefined,
      };
      await api.post(`/api/v1/equipment/maintenance?factory_id=${factoryId}`, payload);
      message.success('维保任务创建成功');
      setCreateModalVisible(false);
      createForm.resetFields();
      fetchTasks();
      fetchStats();
    } catch (error) {
      console.error('Failed to create task:', error);
      message.error('维保任务创建失败');
    } finally {
      setSubmitLoading(false);
    }
  };

  const handleStart = async (id: string) => {
    try {
      await api.post(`/api/v1/equipment/maintenance/${id}/start`);
      message.success('任务已开始');
      fetchTasks();
      fetchStats();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '开始任务失败');
    }
  };

  const handleComplete = async (id: string) => {
    try {
      await api.post(`/api/v1/equipment/maintenance/${id}/complete`);
      message.success('任务已完成');
      fetchTasks();
      fetchStats();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '完成任务失败');
    }
  };

  const columns = [
    {
      title: '任务编号',
      dataIndex: 'task_code',
      key: 'task_code',
      width: 190,
    },
    {
      title: '设备',
      dataIndex: 'equipment_name',
      key: 'equipment_name',
      width: 150,
    },
    {
      title: '类型',
      dataIndex: 'task_type',
      key: 'task_type',
      width: 110,
      render: (type: string) => {
        const cfg = TYPE_MAP[type?.toLowerCase()] || { label: type, color: 'default' };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 90,
      render: (p: string) => {
        const cfg = PRIORITY_MAP[p?.toLowerCase()] || { label: p, color: 'default' };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '计划日期',
      dataIndex: 'planned_date',
      key: 'planned_date',
      width: 120,
      render: (d: string) => d || '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (status: string) => {
        const cfg = STATUS_MAP[status?.toLowerCase()] || { label: status, color: 'default' };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '执行人',
      dataIndex: 'assigned_to',
      key: 'assigned_to',
      width: 110,
      render: (v: string) => v || '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      render: (_: any, record: MaintenanceTask) => {
        const st = record.status?.toLowerCase();
        return (
          <Space>
            <Button
              type="link"
              icon={<EyeOutlined />}
              onClick={() => { setSelectedTask(record); setDetailModalVisible(true); }}
            >
              查看
            </Button>
            {(st === 'pending' || st === 'assigned') && (
              <Button type="link" icon={<PlayCircleOutlined />} onClick={() => handleStart(record.id)}>
                开始
              </Button>
            )}
            {st === 'in_progress' && (
              <Button type="link" icon={<CheckCircleOutlined />} onClick={() => handleComplete(record.id)}>
                完成
              </Button>
            )}
          </Space>
        );
      },
    },
  ];

  return (
    <div>
      <Title level={3}>维保中心（TPM）</Title>
      <Text type="secondary">设备点检 · 润滑 · 校准 · 维修任务管理</Text>

      {stats && (
        <Row gutter={16} style={{ marginTop: 16, marginBottom: 16 }}>
          <Col span={5}>
            <Card>
              <Statistic title="任务总数" value={stats.total_tasks || 0} prefix={<ToolOutlined />} />
            </Card>
          </Col>
          <Col span={5}>
            <Card>
              <Statistic title="待执行" value={(stats.pending || 0) + (stats.in_progress || 0)} prefix={<ClockCircleOutlined />} valueStyle={{ color: '#faad14' }} />
            </Card>
          </Col>
          <Col span={5}>
            <Card>
              <Statistic title="已完成" value={stats.completed || 0} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} />
            </Card>
          </Col>
          <Col span={5}>
            <Card>
              <Statistic title="逾期" value={stats.overdue || 0} prefix={<CalendarOutlined />} valueStyle={{ color: stats.overdue ? '#f5222d' : undefined }} />
            </Card>
          </Col>
          <Col span={4}>
            <Card>
              <Statistic title="完成率" value={stats.completion_rate || 0} suffix="%" valueStyle={{ color: '#1677ff' }} />
            </Card>
          </Col>
        </Row>
      )}

      <div style={{ marginBottom: 16, display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        <Select
          placeholder="任务类型"
          value={typeFilter}
          onChange={(v) => { setTypeFilter(v); setPagination({ ...pagination, current: 1 }); }}
          style={{ width: 140 }}
          allowClear
        >
          <Select.Option value="inspection">点检</Select.Option>
          <Select.Option value="lubrication">润滑</Select.Option>
          <Select.Option value="calibration">校准</Select.Option>
          <Select.Option value="repair">维修</Select.Option>
          <Select.Option value="preventive">预防保养</Select.Option>
        </Select>
        <Select
          placeholder="状态"
          value={statusFilter}
          onChange={(v) => { setStatusFilter(v); setPagination({ ...pagination, current: 1 }); }}
          style={{ width: 140 }}
          allowClear
        >
          <Select.Option value="pending">待执行</Select.Option>
          <Select.Option value="assigned">已指派</Select.Option>
          <Select.Option value="in_progress">进行中</Select.Option>
          <Select.Option value="completed">已完成</Select.Option>
        </Select>
        <RangePicker
          value={dateRange}
          onChange={(dates) => setDateRange(dates as any)}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalVisible(true)}>
          新建任务
        </Button>
      </div>

      <Table
        columns={columns}
        dataSource={tasks}
        rowKey="id"
        loading={loading}
        pagination={{
          ...pagination,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条任务`,
        }}
        onChange={handleTableChange}
      />

      <Modal
        title="新建维保任务"
        open={createModalVisible}
        onOk={() => createForm.submit()}
        onCancel={() => { setCreateModalVisible(false); createForm.resetFields(); }}
        confirmLoading={submitLoading}
        width={600}
      >
        <Form form={createForm} layout="vertical" onFinish={handleCreate}>
          <Form.Item
            name="equipment_id"
            label="设备"
            rules={[{ required: true, message: '请选择设备' }]}
          >
            <Select placeholder="选择设备" options={equipmentOptions} showSearch optionFilterProp="label" />
          </Form.Item>
          <Form.Item
            name="task_type"
            label="任务类型"
            rules={[{ required: true, message: '请选择类型' }]}
          >
            <Select>
              <Select.Option value="inspection">点检</Select.Option>
              <Select.Option value="lubrication">润滑</Select.Option>
              <Select.Option value="calibration">校准</Select.Option>
              <Select.Option value="repair">维修</Select.Option>
              <Select.Option value="preventive">预防保养</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="priority" label="优先级" initialValue="medium">
            <Select>
              <Select.Option value="high">高</Select.Option>
              <Select.Option value="medium">中</Select.Option>
              <Select.Option value="low">低</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="planned_date" label="计划日期" initialValue={dayjs()}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="planned_duration_minutes" label="预计时长（分钟）" initialValue={60}>
            <Input type="number" />
          </Form.Item>
          <Form.Item name="assigned_to" label="执行人">
            <Input placeholder="可选，默认当前用户" />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <TextArea rows={3} placeholder="补充说明..." />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="维保任务详情"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={[<Button key="close" onClick={() => setDetailModalVisible(false)}>关闭</Button>]}
        width={700}
      >
        {selectedTask && (
          <div>
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="任务编号">{selectedTask.task_code}</Descriptions.Item>
              <Descriptions.Item label="类型">
                <Tag color={TYPE_MAP[selectedTask.task_type?.toLowerCase()]?.color || 'default'}>
                  {TYPE_MAP[selectedTask.task_type?.toLowerCase()]?.label || selectedTask.task_type}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="设备">{selectedTask.equipment_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="优先级">
                <Tag color={PRIORITY_MAP[selectedTask.priority?.toLowerCase()]?.color || 'default'}>
                  {PRIORITY_MAP[selectedTask.priority?.toLowerCase()]?.label || selectedTask.priority}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={STATUS_MAP[selectedTask.status?.toLowerCase()]?.color || 'default'}>
                  {STATUS_MAP[selectedTask.status?.toLowerCase()]?.label || selectedTask.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="执行人">{selectedTask.assigned_to || '-'}</Descriptions.Item>
              <Descriptions.Item label="计划日期">{selectedTask.planned_date || '-'}</Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {selectedTask.created_at ? dayjs(selectedTask.created_at).format('YYYY-MM-DD HH:mm') : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="开始时间">
                {selectedTask.started_at ? dayjs(selectedTask.started_at).format('YYYY-MM-DD HH:mm') : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="完成时间">
                {selectedTask.completed_at ? dayjs(selectedTask.completed_at).format('YYYY-MM-DD HH:mm') : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="备注" span={2}>{selectedTask.remark || '-'}</Descriptions.Item>
            </Descriptions>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default MaintenanceCenter;
