/**
 * v2.6 - 三位一体调度系统前端 UI
 * RCC + 参数化面板 + Chatbot工单 + 资源调度视图（接入真实基线数据）
 */

import { useState, useEffect } from 'react'
import { Card, Tabs, Table, Button, Space, Tag, Descriptions, Modal, Form, Input, Select, message, Tree, Breadcrumb, Alert, Row, Col, Statistic } from 'antd'
import { SettingOutlined, TeamOutlined, CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined, SwapOutlined, SafetyOutlined, ThunderboltOutlined, ToolOutlined, FileTextOutlined, EnvironmentOutlined, ProfileOutlined } from '@ant-design/icons'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1/rcc'

interface RccDataResponse {
  success: boolean
  mode?: string
  factory_id?: string
  generated_at?: string
  params_summary: { total: number; high_sensitive: number; people_params: number; equipment_params: number; wo_params: number; env_params: number; process_params: number }
  chains_summary: { total: number; enabled_count: number; disabled_count: number }
  baseline: Record<string, any>
  decisions: Record<string, any>
}

export default function RCCDashboard() {
  const [selectedOrg, setSelectedOrg] = useState('rcc-root')
  const [orgTree, setOrgTree] = useState<any[]>([])
  const [params, setParams] = useState<any[]>([])
  const [rccTasks, setRccTasks] = useState<any[]>([])
  const [chatbotTickets, setChatbotTickets] = useState<any[]>([])
  const [logicChains, setLogicChains] = useState<any[]>([])
  const [rccData, setRccData] = useState<RccDataResponse | null>(null)
  const [loadingData, setLoadingData] = useState(false)
  const [selectedParam, setSelectedParam] = useState<any>(null)
  const [newTicketVisible, setNewTicketVisible] = useState(false)
  const [newTicketForm] = Form.useForm()

  useEffect(() => {
    fetchOrgTree()
    fetchAll()
  }, [])

  const fetchOrgTree = async () => {
    try {
      // 从 API 动态获取工厂列表
      let factoryList = [
        'FAC_ELEC_DEMO_2026',
        'FAC_MECH_001'
      ]
      
      try {
        const res = await axios.get(`${API_BASE}/data?mode=global`)
        if (res.data?.factories_aggregated) {
          factoryList = res.data.factories_aggregated
        }
      } catch (e) {
        console.warn('获取工厂列表失败，使用默认列表')
      }
      
      setOrgTree([
        {
          title: '🏭 RCC 资源控制中心',
          key: 'rcc-root',
          children: [
            ...factoryList.map((f) => ({
              title: `${f}`,
              key: f,
              onClick: () => { fetchFactoryBaseline(f); setSelectedOrg(f); fetchRccData(); },
            })),
            { title: '📊 全局汇总', key: 'rcc-root' },
          ],
        },
      ])
    } catch (err) {
      console.error('获取组织树失败:', err)
    }
  }

  const fetchAll = async () => {
    await Promise.all([
      fetchParams(),
      fetchTasks(),
      fetchTickets(),
      fetchLogicChains(),
      fetchRccData(),
    ])
  }

  const fetchParams = async () => {
    try {
      const res = await axios.get(`${API_BASE}/params`)
      setParams(res.data.items || [])
    } catch (err) {
      console.error('获取参数失败:', err)
    }
  }

  const fetchTasks = async () => {
    try {
      const res = await axios.get(`${API_BASE}/tasks`)
      setRccTasks(res.data.items || [])
    } catch (err) {
      console.error('获取RCC任务失败:', err)
    }
  }

  const fetchTickets = async () => {
    try {
      const res = await axios.get(`${API_BASE}/chatbot/tickets`)
      setChatbotTickets(res.data.items || [])
    } catch (err) {
      console.error('获取Chatbot工单失败:', err)
    }
  }

  const fetchLogicChains = async () => {
    try {
      const res = await axios.get(`${API_BASE}/logic-chains`)
      setLogicChains(res.data.items || [])
    } catch (err) {
      console.error('获取逻辑链失败:', err)
    }
  }

  const fetchRccData = async () => {
    setLoadingData(true)
    try {
      // RCC 全局视角默认走 mode=global，遍历所有工厂汇总
      const res = await axios.get(`${API_BASE}/data?mode=global`)
      setRccData(res.data)
    } catch (err: any) {
      console.error('获取RCC综合数据失败:', err)
      const detail = err.response?.data?.detail || '获取综合数据失败'
      if (!detail.includes('404')) {
        console.warn(detail)
      }
    } finally {
      setLoadingData(false)
    }
  }

  const fetchFactoryBaseline = async (fid: string) => {
    setLoadingData(true)
    try {
      const res = await axios.get(`${API_BASE}/data?mode=single&factory_id=${fid}`)
      setRccData(res.data)
    } catch (err: any) {
      console.error(`获取工厂 ${fid} 基线失败:`, err)
    } finally {
      setLoadingData(false)
    }
  }

}
