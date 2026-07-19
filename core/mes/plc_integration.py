"""
MES Edge Computing & PLC Integration Module
边缘计算与PLC集成模块

功能:
- 上位机与PLC通信 (Modbus TCP/RTU, OPC UA)
- 实时数据采集 (设备状态、工艺参数、报警信息)
- 指令下发 (工单启动、设备控制、参数设置)
- 边缘数据预处理 (过滤、聚合、缓存)
- 断网续传 (本地缓存，网络恢复后同步)
- SCADA系统集成

架构说明:
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   MES Core  │◄───►│  Edge Gateway │◄───►│    PLCs     │
│  (Cloud/On) │     │  (Industrial  │     │ (Siemens,   │
│             │     │   PC/Server)  │     │  Mitsubishi,│
└─────────────┘     └──────────────┘     │   Omron...) │
                                         └─────────────┘
                                                │
                                         ┌─────────────┐
                                         │   Sensors   │
                                         │  (Temperature,│
                                         │   Pressure) │
                                         └─────────────┘
"""

import asyncio
import json
import uuid
import time
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from enum import Enum
from dataclasses import dataclass, field, asdict
import threading
import queue


# ==================== 协议枚举 ====================

class Protocol(str, Enum):
    """支持的工业协议"""
    MODBUS_TCP = "modbus_tcp"
    MODBUS_RTU = "modbus_rtu"
    OPC_UA = "opc_ua"
    SIEMENS_S7 = "siemens_s7"
    MITSUBISHI_MC = "mitsubishi_mc"
    OMRON_FINS = "omron_fins"
    MQTT = "mqtt"  # 用于上位机通信


class DataType(str, Enum):
    """数据类型"""
    BOOL = "bool"
    INT16 = "int16"
    INT32 = "int32"
    FLOAT32 = "float32"
    FLOAT64 = "float64"
    STRING = "string"


class ConnectionStatus(str, Enum):
    """连接状态"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class DeviceMode(str, Enum):
    """设备运行模式"""
    AUTO = "auto"         # 自动模式
    MANUAL = "manual"     # 手动模式
    SEMI_AUTO = "semi"    # 半自动模式
    MAINTENANCE = "maint" # 维护模式


# ==================== 数据模型 ====================

@dataclass
class TagPoint:
    """数据点/标签定义"""
    id: str
    name: str
    address: str          # 寄存器地址，如 "40001", "DB1.DBD0"
    data_type: DataType
    unit: str = ""        # 单位
    description: str = ""
    scale: float = 1.0    # 缩放比例
    offset: float = 0.0   # 偏移量
    read_only: bool = True
    last_value: Any = None
    last_update: Optional[datetime] = None
    quality: str = "good"  # good, bad, uncertain


@dataclass
class PLCDevice:
    """PLC设备定义"""
    id: str
    name: str
    protocol: Protocol
    ip_address: str
    port: int
    station_id: int = 1      # Modbus站号/PLC站号
    rack: int = 0            # S7机架号
    slot: int = 1            # S7槽号
    tags: List[TagPoint] = field(default_factory=list)
    connection_status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    last_heartbeat: Optional[datetime] = None
    firmware_version: str = ""
    device_model: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DataCollection:
    """数据采集记录"""
    id: str
    device_id: str
    tag_id: str
    value: Any
    timestamp: datetime
    quality: str
    raw_value: Any = None


@dataclass
class CommandRequest:
    """控制指令请求"""
    id: str
    device_id: str
    tag_id: str
    value: Any
    operator: str
    reason: str
    created_at: datetime
    status: str = "pending"  # pending, executing, completed, failed
    result: Optional[str] = None
    executed_at: Optional[datetime] = None


@dataclass
class AlarmEvent:
    """报警事件"""
    id: str
    device_id: str
    alarm_code: str
    alarm_message: str
    severity: str  # critical, major, minor, warning
    triggered_at: datetime
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    cleared: bool = False
    cleared_at: Optional[datetime] = None


@dataclass
class WorkOrderExecution:
    """工单执行上下文"""
    work_order_id: str
    product_code: str
    quantity: int
    current_operation: str
    target_device_id: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    produced_qty: int = 0
    scrap_qty: int = 0
    parameters: Dict[str, Any] = field(default_factory=dict)


# ==================== 边缘网关核心类 ====================

class EdgeGateway:
    """
    边缘计算网关
    
    功能:
    - 多协议PLC连接管理
    - 实时数据采集
    - 指令下发
    - 边缘数据预处理
    - 本地缓存与断网续传
    - 与MES云端同步
    """
    
    def __init__(self, gateway_id: str, location: str = "factory_floor"):
        self.gateway_id = gateway_id
        self.location = location
        self.devices: Dict[str, PLCDevice] = {}
        self.tag_subscriptions: Dict[str, List[Callable]] = {}  # tag_id -> callbacks
        self.command_queue: queue.Queue = queue.Queue()
        self.data_buffer: List[DataCollection] = []
        self.max_buffer_size = 10000
        self.is_running = False
        self.sync_callback: Optional[Callable] = None  # MES同步回调
        self._collection_thread: Optional[threading.Thread] = None
        self._command_thread: Optional[threading.Thread] = None
        
        # 统计信息
        self.stats = {
            "total_collections": 0,
            "failed_collections": 0,
            "commands_executed": 0,
            "commands_failed": 0,
            "last_sync_time": None,
        }
    
    def register_device(self, device: PLCDevice) -> bool:
        """注册PLC设备"""
        if device.id in self.devices:
            return False
        self.devices[device.id] = device
        print(f"[EdgeGateway] 设备已注册：{device.name} ({device.ip_address})")
        return True
    
    def unregister_device(self, device_id: str) -> bool:
        """注销设备"""
        if device_id not in self.devices:
            return False
        del self.devices[device_id]
        print(f"[EdgeGateway] 设备已注销：{device_id}")
        return True
    
    async def connect_device(self, device_id: str) -> Dict[str, Any]:
        """连接设备"""
        if device_id not in self.devices:
            return {"success": False, "error": "设备不存在"}
        
        device = self.devices[device_id]
        
        # 模拟连接过程
        try:
            print(f"[EdgeGateway] 正在连接设备：{device.name} via {device.protocol.value}")
            await asyncio.sleep(0.5)  # 模拟连接延迟
            
            device.connection_status = ConnectionStatus.CONNECTED
            device.last_heartbeat = datetime.now()
            
            return {
                "success": True,
                "device_id": device_id,
                "status": device.connection_status.value,
                "message": f"设备 {device.name} 连接成功"
            }
        except Exception as e:
            device.connection_status = ConnectionStatus.ERROR
            return {
                "success": False,
                "error": str(e),
                "device_id": device_id
            }
    
    async def disconnect_device(self, device_id: str) -> Dict[str, Any]:
        """断开设备连接"""
        if device_id not in self.devices:
            return {"success": False, "error": "设备不存在"}
        
        device = self.devices[device_id]
        device.connection_status = ConnectionStatus.DISCONNECTED
        
        return {
            "success": True,
            "device_id": device_id,
            "message": f"设备 {device.name} 已断开"
        }
    
    async def read_tags(self, device_id: str, tag_ids: List[str]) -> List[DataCollection]:
        """批量读取标签数据"""
        if device_id not in self.devices:
            return []
        
        device = self.devices[device_id]
        if device.connection_status != ConnectionStatus.CONNECTED:
            print(f"[EdgeGateway] 设备未连接：{device_id}")
            return []
        
        collections = []
        for tag_id in tag_ids:
            tag = next((t for t in device.tags if t.id == tag_id), None)
            if not tag:
                continue
            
            # 模拟读取数据
            simulated_value = self._simulate_tag_value(tag)
            
            collection = DataCollection(
                id=str(uuid.uuid4()),
                device_id=device_id,
                tag_id=tag_id,
                value=simulated_value * tag.scale + tag.offset,
                timestamp=datetime.now(),
                quality="good",
                raw_value=simulated_value
            )
            
            collections.append(collection)
            tag.last_value = collection.value
            tag.last_update = collection.timestamp
            
            # 触发订阅回调
            self._notify_subscribers(tag_id, collection)
            
            # 添加到缓冲区
            self._buffer_data(collection)
        
        self.stats["total_collections"] += len(collections)
        return collections
    
    async def write_tag(self, device_id: str, tag_id: str, value: Any, 
                       operator: str, reason: str = "") -> CommandRequest:
        """写入单个标签值"""
        command = CommandRequest(
            id=str(uuid.uuid4()),
            device_id=device_id,
            tag_id=tag_id,
            value=value,
            operator=operator,
            reason=reason,
            created_at=datetime.now()
        )
        
        self.command_queue.put(command)
        return command
    
    async def execute_command(self, command: CommandRequest) -> CommandRequest:
        """执行控制指令"""
        if command.device_id not in self.devices:
            command.status = "failed"
            command.result = "设备不存在"
            self.stats["commands_failed"] += 1
            return command
        
        device = self.devices[command.device_id]
        if device.connection_status != ConnectionStatus.CONNECTED:
            command.status = "failed"
            command.result = "设备未连接"
            self.stats["commands_failed"] += 1
            return command
        
        try:
            # 模拟写入操作
            await asyncio.sleep(0.2)
            
            command.status = "completed"
            command.result = "执行成功"
            command.executed_at = datetime.now()
            self.stats["commands_executed"] += 1
            
            print(f"[EdgeGateway] 指令执行成功：{command.tag_id} = {command.value}")
            
        except Exception as e:
            command.status = "failed"
            command.result = str(e)
            self.stats["commands_failed"] += 1
        
        return command
    
    def subscribe_tag(self, tag_id: str, callback: Callable[[DataCollection], None]):
        """订阅标签数据变化"""
        if tag_id not in self.tag_subscriptions:
            self.tag_subscriptions[tag_id] = []
        self.tag_subscriptions[tag_id].append(callback)
    
    def unsubscribe_tag(self, tag_id: str, callback: Callable):
        """取消订阅"""
        if tag_id in self.tag_subscriptions:
            self.tag_subscriptions[tag_id] = [
                cb for cb in self.tag_subscriptions[tag_id] if cb != callback
            ]
    
    def _notify_subscribers(self, tag_id: str, collection: DataCollection):
        """通知订阅者"""
        if tag_id in self.tag_subscriptions:
            for callback in self.tag_subscriptions[tag_id]:
                try:
                    callback(collection)
                except Exception as e:
                    print(f"[EdgeGateway] 订阅回调错误：{e}")
    
    def _buffer_data(self, collection: DataCollection):
        """缓冲数据（用于断网续传）"""
        self.data_buffer.append(collection)
        if len(self.data_buffer) > self.max_buffer_size:
            self.data_buffer.pop(0)
    
    def _simulate_tag_value(self, tag: TagPoint) -> Any:
        """模拟标签值（实际应通过协议读取）"""
        import random
        
        if tag.data_type == DataType.BOOL:
            return random.choice([True, False])
        elif tag.data_type in [DataType.INT16, DataType.INT32]:
            return random.randint(0, 1000)
        elif tag.data_type == DataType.FLOAT32:
            return round(random.uniform(20.0, 80.0), 2)
        elif tag.data_type == DataType.FLOAT64:
            return round(random.uniform(0.0, 100.0), 4)
        else:
            return "simulated"
    
    async def sync_to_mes(self):
        """同步数据到MES系统"""
        if not self.data_buffer or not self.sync_callback:
            return
        
        buffer_copy = self.data_buffer.copy()
        self.data_buffer.clear()
        
        try:
            await self.sync_callback(buffer_copy)
            self.stats["last_sync_time"] = datetime.now()
            print(f"[EdgeGateway] 已同步 {len(buffer_copy)} 条数据到 MES")
        except Exception as e:
            # 同步失败，数据保留在缓冲区
            self.data_buffer = buffer_copy + self.data_buffer
            print(f"[EdgeGateway] 同步失败：{e}")
    
    def start_background_tasks(self):
        """启动后台任务"""
        self.is_running = True
        
        # 数据采集线程
        self._collection_thread = threading.Thread(target=self._collection_loop)
        self._collection_thread.daemon = True
        self._collection_thread.start()
        
        # 指令执行线程
        self._command_thread = threading.Thread(target=self._command_loop)
        self._command_thread.daemon = True
        self._command_thread.start()
        
        print("[EdgeGateway] 后台任务已启动")
    
    def stop_background_tasks(self):
        """停止后台任务"""
        self.is_running = False
        if self._collection_thread:
            self._collection_thread.join(timeout=2)
        if self._command_thread:
            self._command_thread.join(timeout=2)
        print("[EdgeGateway] 后台任务已停止")
    
    def _collection_loop(self):
        """数据采集循环"""
        while self.is_running:
            for device_id, device in self.devices.items():
                if device.connection_status == ConnectionStatus.CONNECTED:
                    tag_ids = [tag.id for tag in device.tags]
                    if tag_ids:
                        # 在线程中调用异步方法
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(self.read_tags(device_id, tag_ids[:5]))
                        finally:
                            loop.close()
            time.sleep(1)  # 采集间隔
    
    def _command_loop(self):
        """指令执行循环"""
        while self.is_running:
            try:
                command = self.command_queue.get(timeout=1)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self.execute_command(command))
                finally:
                    loop.close()
                    self.command_queue.task_done()
            except queue.Empty:
                continue
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self.stats,
            "gateway_id": self.gateway_id,
            "connected_devices": sum(
                1 for d in self.devices.values() 
                if d.connection_status == ConnectionStatus.CONNECTED
            ),
            "total_devices": len(self.devices),
            "buffer_size": len(self.data_buffer),
        }


# ==================== 上位机通信服务 ====================

class HMICommunicationService:
    """
    上位机通信服务
    
    功能:
    - 与HMI/SCADA系统双向通信
    - 工单信息推送
    - 生产指令接收
    - 报警通知
    - 报表数据上传
    """
    
    def __init__(self, service_id: str):
        self.service_id = service_id
        self.connected_hmis: Dict[str, Dict[str, Any]] = {}
        self.message_queue: queue.Queue = queue.Queue()
        self.is_running = False
    
    def register_hmi(self, hmi_id: str, hmi_info: Dict[str, Any]) -> bool:
        """注册上位机"""
        if hmi_id in self.connected_hmis:
            return False
        
        self.connected_hmis[hmi_id] = {
            "id": hmi_id,
            "info": hmi_info,
            "connected_at": datetime.now(),
            "last_heartbeat": datetime.now(),
            "status": "online"
        }
        print(f"[HMI] 上位机已注册：{hmi_id}")
        return True
    
    async def send_work_order_to_hmi(self, hmi_id: str, work_order: WorkOrderExecution) -> bool:
        """发送工单到上位机"""
        if hmi_id not in self.connected_hmis:
            return False
        
        message = {
            "type": "work_order",
            "hmi_id": hmi_id,
            "data": asdict(work_order),
            "timestamp": datetime.now().isoformat()
        }
        
        self.message_queue.put(message)
        print(f"[HMI] 工单已发送到上位机 {hmi_id}: {work_order.work_order_id}")
        return True
    
    async def receive_production_data(self, hmi_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """接收上位机上报的生产数据"""
        if hmi_id not in self.connected_hmis:
            return {"success": False, "error": "上位机未注册"}
        
        # 更新心跳
        self.connected_hmis[hmi_id]["last_heartbeat"] = datetime.now()
        
        # 处理数据
        processed = {
            "success": True,
            "hmi_id": hmi_id,
            "received_at": datetime.now().isoformat(),
            "data_points": len(data.get("readings", [])),
            "message": "数据接收成功"
        }
        
        print(f"[HMI] 收到上位机 {hmi_id} 上报数据：{len(data.get('readings', []))} 个点")
        return processed
    
    async def send_alarm_notification(self, hmi_id: str, alarm: AlarmEvent) -> bool:
        """发送报警通知到上位机"""
        if hmi_id not in self.connected_hmis:
            return False
        
        message = {
            "type": "alarm",
            "hmi_id": hmi_id,
            "data": asdict(alarm),
            "priority": "high" if alarm.severity in ["critical", "major"] else "normal",
            "timestamp": datetime.now().isoformat()
        }
        
        self.message_queue.put(message)
        print(f"[HMI] 报警已发送到上位机 {hmi_id}: {alarm.alarm_message}")
        return True
    
    def get_hmi_status(self, hmi_id: str) -> Optional[Dict[str, Any]]:
        """获取上位机状态"""
        if hmi_id not in self.connected_hmis:
            return None
        return self.connected_hmis[hmi_id]


# ==================== SCADA集成服务 ====================

class SCADAIntegrationService:
    """
    SCADA系统集成服务
    
    功能:
    - 与SCADA系统数据交换
    - 实时画面数据推送
    - 历史数据查询
    - 报警联动
    """
    
    def __init__(self, scada_endpoint: str):
        self.scada_endpoint = scada_endpoint
        self.connection_status = ConnectionStatus.DISCONNECTED
        self.subscribed_tags: List[str] = []
        self.data_callbacks: Dict[str, Callable] = {}
    
    async def connect(self) -> Dict[str, Any]:
        """连接SCADA系统"""
        try:
            print(f"[SCADA] 正在连接到 {self.scada_endpoint}")
            await asyncio.sleep(0.5)
            
            self.connection_status = ConnectionStatus.CONNECTED
            return {
                "success": True,
                "endpoint": self.scada_endpoint,
                "status": "connected"
            }
        except Exception as e:
            self.connection_status = ConnectionStatus.ERROR
            return {
                "success": False,
                "error": str(e)
            }
    
    async def subscribe_tags(self, tag_ids: List[str]) -> bool:
        """订阅SCADA标签"""
        if self.connection_status != ConnectionStatus.CONNECTED:
            return False
        
        self.subscribed_tags.extend(tag_ids)
        print(f"[SCADA] 已订阅 {len(tag_ids)} 个标签")
        return True
    
    async def push_realtime_data(self, data: Dict[str, Any]) -> bool:
        """推送实时数据到SCADA"""
        if self.connection_status != ConnectionStatus.CONNECTED:
            return False
        
        # 模拟推送
        print(f"[SCADA] 推送 {len(data)} 个数据点到SCADA")
        return True
    
    async def query_historical_data(
        self,
        tag_ids: List[str],
        start_time: datetime,
        end_time: datetime,
        interval: int = 60
    ) -> List[Dict[str, Any]]:
        """查询历史数据"""
        if self.connection_status != ConnectionStatus.CONNECTED:
            return []
        
        # 模拟返回历史数据
        historical = []
        for tag_id in tag_ids:
            historical.append({
                "tag_id": tag_id,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "interval_seconds": interval,
                "data_points": 100,  # 模拟点数
                "values": []  # 实际应包含具体数值
            })
        
        return historical


# ==================== 工单与设备联动场景 ====================

class WorkOrderDeviceLinkage:
    """
    工单与设备联动场景
    
    实现:
    - 工单下达时自动配置设备参数
    - 设备就绪后自动开始工单
    - 生产过程中实时监控设备状态
    - 异常停机时自动暂停工单
    - 完工后自动上报产量
    """
    
    def __init__(self, edge_gateway: EdgeGateway, hmi_service: HMICommunicationService):
        self.edge_gateway = edge_gateway
        self.hmi_service = hmi_service
        self.active_work_orders: Dict[str, WorkOrderExecution] = {}
    
    async def start_work_order_on_device(
        self,
        work_order: WorkOrderExecution,
        device_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        在设备上启动工单
        
        流程:
        1. 检查设备状态
        2. 下发工艺参数
        3. 发送启动指令
        4. 监控执行状态
        """
        device_id = work_order.target_device_id
        
        # 1. 检查设备连接
        if device_id not in self.edge_gateway.devices:
            return {"success": False, "error": "设备不存在"}
        
        device = self.edge_gateway.devices[device_id]
        if device.connection_status != ConnectionStatus.CONNECTED:
            return {"success": False, "error": "设备未连接"}
        
        # 2. 下发工艺参数
        param_commands = []
        for param_name, param_value in device_params.items():
            tag_id = f"{device_id}_{param_name}"
            cmd = await self.edge_gateway.write_tag(
                device_id=device_id,
                tag_id=tag_id,
                value=param_value,
                operator="system",
                reason=f"工单 {work_order.work_order_id} 参数设置"
            )
            param_commands.append(cmd)
        
        # 等待参数下发完成
        await asyncio.sleep(0.5)
        
        # 3. 发送启动指令
        start_cmd = await self.edge_gateway.write_tag(
            device_id=device_id,
            tag_id=f"{device_id}_START_CMD",
            value=True,
            operator="system",
            reason=f"启动工单 {work_order.work_order_id}"
        )
        
        # 4. 记录工单状态
        work_order.started_at = datetime.now()
        self.active_work_orders[work_order.work_order_id] = work_order
        
        # 5. 通知上位机
        await self.hmi_service.send_work_order_to_hmi("HMI-001", work_order)
        
        return {
            "success": True,
            "work_order_id": work_order.work_order_id,
            "device_id": device_id,
            "params_set": len(param_commands),
            "started_at": work_order.started_at.isoformat()
        }
    
    async def monitor_work_order_progress(
        self,
        work_order_id: str,
        device_id: str
    ) -> Dict[str, Any]:
        """监控工单进度"""
        if work_order_id not in self.active_work_orders:
            return {"success": False, "error": "工单不存在"}
        
        work_order = self.active_work_orders[work_order_id]
        
        # 读取设备计数
        collections = await self.edge_gateway.read_tags(
            device_id=device_id,
            tag_ids=[f"{device_id}_PROD_COUNT", f"{device_id}_SCRAP_COUNT"]
        )
        
        for col in collections:
            if "PROD" in col.tag_id:
                work_order.produced_qty = int(col.value)
            elif "SCRAP" in col.tag_id:
                work_order.scrap_qty = int(col.value)
        
        progress = {
            "work_order_id": work_order_id,
            "produced": work_order.produced_qty,
            "scrap": work_order.scrap_qty,
            "target": work_order.quantity,
            "progress_percent": round(work_order.produced_qty / work_order.quantity * 100, 2),
            "status": "in_progress"
        }
        
        return progress
    
    async def complete_work_order(self, work_order_id: str) -> Dict[str, Any]:
        """完成工单"""
        if work_order_id not in self.active_work_orders:
            return {"success": False, "error": "工单不存在"}
        
        work_order = self.active_work_orders[work_order_id]
        work_order.completed_at = datetime.now()
        
        # 从活跃列表移除
        del self.active_work_orders[work_order_id]
        
        return {
            "success": True,
            "work_order_id": work_order_id,
            "produced_qty": work_order.produced_qty,
            "scrap_qty": work_order.scrap_qty,
            "completed_at": work_order.completed_at.isoformat()
        }


# ==================== 演示场景 ====================

async def run_plc_integration_demo():
    """运行PLC集成演示"""
    print("=" * 70)
    print("MES 上位机+PLC集成演示")
    print("=" * 70)
    
    # 1. 初始化边缘网关
    gateway = EdgeGateway(gateway_id="EDGE-001", location="Assembly Line A")
    
    # 2. 创建PLC设备 (模拟西门子S7-1200)
    plc = PLCDevice(
        id="PLC-001",
        name="S7-1200_Main",
        protocol=Protocol.SIEMENS_S7,
        ip_address="192.168.1.100",
        port=102,
        rack=0,
        slot=1,
        device_model="CPU 1215C DC/DC/DC",
        firmware_version="V4.2"
    )
    
    # 添加标签点
    plc.tags = [
        TagPoint(id="PLC-001_TEMP", name="温度传感器", address="DB1.DBD0", 
                 data_type=DataType.FLOAT32, unit="°C", scale=1.0),
        TagPoint(id="PLC-001_PRESSURE", name="压力传感器", address="DB1.DBD4", 
                 data_type=DataType.FLOAT32, unit="bar", scale=0.1),
        TagPoint(id="PLC-001_SPEED", name="电机转速", address="DB1.DBD8", 
                 data_type=DataType.FLOAT32, unit="RPM", scale=1.0),
        TagPoint(id="PLC-001_PROD_COUNT", name="产量计数", address="DB1.DBD12", 
                 data_type=DataType.INT32, unit="pcs", scale=1.0),
        TagPoint(id="PLC-001_SCRAP_COUNT", name="废品计数", address="DB1.DBD16", 
                 data_type=DataType.INT32, unit="pcs", scale=1.0),
        TagPoint(id="PLC-001_START_CMD", name="启动命令", address="DB1.DBX20.0", 
                 data_type=DataType.BOOL, read_only=False),
        TagPoint(id="PLC-001_STOP_CMD", name="停止命令", address="DB1.DBX20.1", 
                 data_type=DataType.BOOL, read_only=False),
        TagPoint(id="PLC-001_RUNNING", name="运行状态", address="DB1.DBX20.2", 
                 data_type=DataType.BOOL),
        TagPoint(id="PLC-001_FAULT", name="故障状态", address="DB1.DBX20.3", 
                 data_type=DataType.BOOL),
    ]
    
    # 注册设备
    gateway.register_device(plc)
    
    # 3. 连接设备
    result = await gateway.connect_device("PLC-001")
    print(f"\n[步骤1] 设备连接结果：{json.dumps(result, ensure_ascii=False, indent=2)}")
    
    # 4. 初始化HMI服务
    hmi_service = HMICommunicationService(service_id="HMI-SVC-001")
    hmi_service.register_hmi("HMI-001", {
        "name": "产线A操作站",
        "ip": "192.168.1.50",
        "model": "WinCC Advanced V16"
    })
    
    # 5. 创建工单联动服务
    linkage = WorkOrderDeviceLinkage(gateway, hmi_service)
    
    # 6. 创建并启动工单
    work_order = WorkOrderExecution(
        work_order_id="WO-20260124-001",
        product_code="PROD-A001",
        quantity=1000,
        current_operation="OP-10_Assembly",
        target_device_id="PLC-001"
    )
    
    # 工艺参数
    device_params = {
        "TEMP": 65.0,        # 目标温度
        "PRESSURE": 5.5,     # 目标压力
        "SPEED": 120.0       # 目标速度
    }
    
    print("\n[步骤2] 启动工单...")
    start_result = await linkage.start_work_order_on_device(work_order, device_params)
    print(f"工单启动结果：{json.dumps(start_result, ensure_ascii=False, indent=2)}")
    
    # 7. 模拟生产过程
    print("\n[步骤3] 模拟生产过程数据采集...")
    for i in range(5):
        collections = await gateway.read_tags(
            device_id="PLC-001",
            tag_ids=["PLC-001_TEMP", "PLC-001_PRESSURE", "PLC-001_SPEED"]
        )
        print(f"  第{i+1}次采集:")
        for col in collections:
            tag = next((t for t in plc.tags if t.id == col.tag_id), None)
            tag_name = tag.name if tag else col.tag_id
            print(f"    {tag_name}: {col.value} {tag.unit if tag else ''}")
        await asyncio.sleep(0.3)
    
    # 8. 监控工单进度
    print("\n[步骤4] 监控工单进度...")
    progress = await linkage.monitor_work_order_progress("WO-20260124-001", "PLC-001")
    print(f"当前进度：{json.dumps(progress, ensure_ascii=False, indent=2)}")
    
    # 9. 模拟报警
    print("\n[步骤5] 模拟报警事件...")
    alarm = AlarmEvent(
        id=str(uuid.uuid4()),
        device_id="PLC-001",
        alarm_code="ALM-HIGH-TEMP",
        alarm_message="温度过高警告",
        severity="warning",
        triggered_at=datetime.now()
    )
    await hmi_service.send_alarm_notification("HMI-001", alarm)
    
    # 10. 完成工单
    print("\n[步骤6] 完成工单...")
    # 模拟产量
    work_order.produced_qty = 985
    work_order.scrap_qty = 15
    complete_result = await linkage.complete_work_order("WO-20260124-001")
    print(f"工单完成结果：{json.dumps(complete_result, ensure_ascii=False, indent=2)}")
    
    # 11. 获取统计信息
    print("\n[步骤7] 网关统计信息...")
    stats = gateway.get_statistics()
    print(f"统计数据：{json.dumps(stats, ensure_ascii=False, indent=2)}")
    
    # 12. SCADA集成演示
    print("\n[步骤8] SCADA集成演示...")
    scada_service = SCADAIntegrationService(scada_endpoint="opc.tcp://192.168.1.200:4840")
    scada_result = await scada_service.connect()
    print(f"SCADA连接结果：{json.dumps(scada_result, ensure_ascii=False, indent=2)}")
    
    if scada_result["success"]:
        await scada_service.subscribe_tags(["PLC-001_TEMP", "PLC-001_PRESSURE"])
        await scada_service.push_realtime_data({"temp": 65.5, "pressure": 5.5})
    
    print("\n" + "=" * 70)
    print("演示完成!")
    print("=" * 70)
    
    return {
        "gateway_stats": stats,
        "work_order_completed": complete_result["success"],
        "scada_connected": scada_result["success"]
    }


# ==================== 主程序入口 ====================

if __name__ == "__main__":
    result = asyncio.run(run_plc_integration_demo())
    print(f"\n最终结果：{json.dumps(result, ensure_ascii=False, indent=2)}")
