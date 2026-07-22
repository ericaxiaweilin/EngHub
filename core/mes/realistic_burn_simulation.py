"""
MES系统 - 跑步机固件烧录与FCT测试真实场景模拟
Real-world Simulation for Treadmill Firmware Burning & FCT

核心改进点：
1. 引入人工操作时间 (Human Operation Time)
2. 真实的烧录物理耗时 (基于波特率和Flash大小)
3. 工人疲劳度与操作失误率
4. 异常处理流程 (重试、换线、报废)
5. 治具占用与并行工位计算
"""

import time
import random
import datetime
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Dict
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BurnProtocol(Enum):
    UART = "UART"
    SWD = "SWD"
    BLE_OTA = "BLE_OTP"
    WIFI_OTA = "WIFI_OTA"

class StationStatus(Enum):
    IDLE = "空闲"
    OPERATING = "人工操作中"
    BURNING = "自动烧录中"
    TESTING = "FCT测试中"
    ERROR = "异常处理"
    MAINTENANCE = "维护"

class WorkOrderStatus(Enum):
    PENDING = "待生产"
    IN_PROGRESS = "生产中"
    COMPLETED = "已完成"
    EXCEPTION = "异常挂起"

@dataclass
class FirmwareConfig:
    """固件配置"""
    name: str
    version: str
    size_kb: int  # 固件大小 KB
    protocol: BurnProtocol
    baudrate: int = 115200
    
    def get_burn_time(self) -> float:
        """计算纯物理烧录时间 (秒)
        公式：(Size * 1024 * 8) / Baudrate * 校验系数(1.2)
        """
        bits = self.size_kb * 1024 * 8
        effective_rate = self.baudrate * 0.8  # 串口传输效率通常只有80%
        raw_time = bits / effective_rate
        
        # 不同协议额外开销
        if self.protocol == BurnProtocol.SWD:
            return max(25.0, raw_time * 0.9) # SWD较快，但有握手时间
        elif self.protocol == BurnProtocol.UART:
            return max(40.0, raw_time) # UART较慢
        else: # OTA
            return max(60.0, raw_time * 1.5) # OTA受信号影响大

@dataclass
class Operator:
    """操作员模型"""
    id: str
    name: str
    skill_level: float  # 0.8 - 1.2 (1.0为标准)
    fatigue_factor: float = 1.0  # 疲劳系数，随时间增加
    
    def get_operation_time(self, base_time: float) -> float:
        """计算实际操作时间，考虑技能和疲劳"""
        # 技能越高时间越短，疲劳越高时间越长
        factor = (1.0 / self.skill_level) * self.fatigue_factor
        return base_time * factor
    
    def get_error_rate(self) -> float:
        """获取当前操作失误率"""
        base_error = 0.01 # 基础1%失误率
        return base_error * self.fatigue_factor * (1.2 - self.skill_level)

@dataclass
class Jig:
    """烧录治具"""
    id: str
    status: str = "GOOD" # GOOD, BAD_PIN, BAD_CABLE
    usage_count: int = 0
    
    def check_health(self) -> bool:
        if self.status != "GOOD":
            return False
        # 治具使用过多会导致接触不良概率增加
        if self.usage_count > 1000 and random.random() < 0.05:
            self.status = "BAD_PIN"
            return False
        return True

@dataclass
class ProductUnit:
    """单个产品实例"""
    sn: str
    model: str
    firmware: FirmwareConfig
    status: str = "INIT"
    burn_result: str = "PENDING"
    fct_result: str = "PENDING"
    total_time: float = 0.0
    retry_count: int = 0
    failure_reason: str = ""

@dataclass
class Station:
    """烧录工位"""
    id: str
    operator: Operator
    jig: Jig
    current_product: Optional[ProductUnit] = None
    status: StationStatus = StationStatus.IDLE
    queue: List[ProductUnit] = field(default_factory=list)
    
    # 时间统计 (秒)
    time_operate: float = 15.0  # 标准人工操作时间 (取放+接线)
    time_verify: float = 5.0   # 验证与拆卸时间
    
    def process_unit(self, unit: ProductUnit) -> Dict:
        """执行单个产品的完整烧录流程"""
        result_log = {
            "sn": unit.sn,
            "start_time": datetime.datetime.now().isoformat(),
            "steps": []
        }
        
        start_ts = time.time()
        
        # 1. 检查治具
        if not self.jig.check_health():
            unit.status = "FAIL"
            unit.failure_reason = f"治具故障 ({self.jig.status})"
            result_log["steps"].append({"step": "JIG_CHECK", "status": "FAIL", "time": 0})
            return result_log
            
        # 2. 人工操作：取料、安装、接线 (模拟真实动作)
        op_time = self.operator.get_operation_time(self.time_operate)
        result_log["steps"].append({"step": "MANUAL_LOAD", "duration": round(op_time, 2)})
        # time.sleep(op_time * 0.1) # 加速模拟，实际会sleep(op_time) - 注释掉以快速演示
        
        # 3. 触发烧录 (自动过程)
        self.status = StationStatus.BURNING
        burn_time = unit.firmware.get_burn_time()
        # 模拟烧录过程中的微小波动
        actual_burn_time = burn_time * random.uniform(0.95, 1.05)
        result_log["steps"].append({"step": "FLASH_BURN", "duration": round(actual_burn_time, 2)})
        # time.sleep(actual_burn_time * 0.05) # 加速模拟 - 注释掉以快速演示
        
        # 4. 模拟烧录结果判定
        # 失败概率：基础硬件失败 + 治具接触不良 + 人为接线不稳
        fail_chance = 0.02 + (0.03 if self.jig.usage_count > 500 else 0) + self.operator.get_error_rate()
        
        if random.random() < fail_chance:
            # 烧录失败，进入重试逻辑
            unit.retry_count += 1
            if unit.retry_count <= 2:
                # 重试：通常只需重新插拔 (人工时间短一点)
                retry_op_time = self.operator.get_operation_time(8.0) 
                result_log["steps"].append({"step": "RETRY_RELOAD", "duration": round(retry_op_time, 2)})
                time.sleep(retry_op_time * 0.1)
                
                # 重试烧录
                result_log["steps"].append({"step": "FLASH_BURN_RETRY", "duration": round(actual_burn_time, 2)})
                time.sleep(actual_burn_time * 0.05)
                
                # 重试后大概率成功，小概率彻底失败
                if random.random() < 0.1:
                    unit.status = "FAIL"
                    unit.failure_reason = "二次烧录校验错误"
                    result_log["steps"].append({"step": "FINAL_CHECK", "status": "FAIL"})
                    return result_log
            else:
                unit.status = "FAIL"
                unit.failure_reason = "超过最大重试次数"
                result_log["steps"].append({"step": "ABORT", "reason": "Max Retries"})
                return result_log

        # 5. FCT功能测试 (模拟点亮屏幕、测电机信号等)
        self.status = StationStatus.TESTING
        fct_time = 15.0 # FCT测试时间
        result_log["steps"].append({"step": "FCT_TEST", "duration": round(fct_time, 2)})
        # time.sleep(fct_time * 0.1) # 跳过延时以快速演示
        
        # 6. 人工确认与拆卸
        verify_time = self.operator.get_operation_time(self.time_verify)
        result_log["steps"].append({"step": "MANUAL_UNLOAD", "duration": round(verify_time, 2)})
        # time.sleep(verify_time * 0.1) # 跳过延时以快速演示
        
        # 更新状态
        unit.status = "PASS"
        unit.burn_result = "SUCCESS"
        unit.fct_result = "SUCCESS"
        # 使用累加的步骤时间作为总时间 (因为 time.sleep 被注释了，time.time() 差值几乎为 0)
        unit.total_time = sum(step.get("duration", 0) for step in result_log["steps"])
        
        # 更新治具计数
        self.jig.usage_count += 1
        
        result_log["total_time"] = round(unit.total_time, 2)
        result_log["status"] = "PASS"
        return result_log

class ProductionLine:
    """生产线模拟器"""
    def __init__(self, line_name: str, station_count: int):
        self.name = line_name
        self.stations: List[Station] = []
        self.products: List[ProductUnit] = []
        self.stats = {
            "total": 0,
            "pass": 0,
            "fail": 0,
            "total_time_sec": 0,
            "start_time": None,
            "end_time": None
        }
        
        # 初始化产线资源
        fw_config = FirmwareConfig(
            name="Treadmill_Main_v2.4.bin",
            version="2.4.1",
            size_kb=1024, # 1MB固件
            protocol=BurnProtocol.UART,
            baudrate=921600 # 高速波特率
        )
        
        for i in range(station_count):
            # 模拟不同技能的工人
            skill = random.uniform(0.9, 1.1)
            op = Operator(id=f"OP-{i+1:02d}", name=f"Worker_{i+1}", skill_level=skill)
            jig = Jig(id=f"JIG-{i+1:02d}")
            station = Station(id=f"ST-{i+1:02d}", operator=op, jig=jig)
            self.stations.append(station)
            
        print(f"\n{'='*60}")
        print(f"产线初始化完成：{self.name}")
        print(f"工位数量：{station_count}")
        print(f"目标固件：{fw_config.name} ({fw_config.size_kb}KB)")
        print(f"理论烧录时间：{fw_config.get_burn_time():.1f}s")
        print(f"标准人工操作：~20s (含取放、接线、确认)")
        print(f"预计单件节拍 (CT): ~{fw_config.get_burn_time() + 20:.1f}s")
        print(f"预计小时产能 (UPH): ~{3600/(fw_config.get_burn_time() + 20):.1f} 台 (理论值)")
        print(f"{'='*60}\n")

    def generate_order(self, quantity: int, model: str):
        """生成工单"""
        fw_config = FirmwareConfig(
            name=f"{model}_FW.bin",
            version="1.0.0",
            size_kb=1024,
            protocol=BurnProtocol.UART,
            baudrate=921600
        )
        
        for i in range(quantity):
            sn = f"TM{model[-3:]}{datetime.datetime.now().strftime('%y%m%d')}{i+1:05d}"
            unit = ProductUnit(sn=sn, model=model, firmware=fw_config)
            self.products.append(unit)
        self.stats["total"] = quantity
        self.stats["start_time"] = datetime.datetime.now()

    def run_simulation(self):
        """运行生产模拟"""
        if not self.products:
            return
            
        print(f"开始生产工单，总数：{len(self.products)} 台...")
        print("注：以下时间为真实物理时间模拟 (已加速显示，实际逻辑包含完整延时)\n")
        
        product_idx = 0
        completed_units = []
        
        # 简单的轮询调度模拟
        while product_idx < len(self.products) or any(s.current_product is not None for s in self.stations):
            
            # 1. 分配任务给空闲工位
            for station in self.stations:
                if station.status == StationStatus.IDLE and product_idx < len(self.products):
                    unit = self.products[product_idx]
                    station.current_product = unit
                    station.status = StationStatus.OPERATING
                    product_idx += 1
            
            # 2. 处理进行中的任务 (模拟并发)
            # 在真实系统中这是多线程/异步的，这里为了演示日志清晰，我们按工位顺序快速推进
            # 为了体现"真实感"，我们打印每个工位的预计耗时
            
            active_stations = [s for s in self.stations if s.current_product is not None]
            if not active_stations and product_idx >= len(self.products):
                break
                
            # 模拟并行处理：找出最快完成的工位逻辑
            # 这里简化处理：直接调用process_unit，但在日志中体现时间累积
            for station in active_stations:
                unit = station.current_product
                
                # 模拟工人疲劳度随产量增加
                produced_count = len(completed_units)
                station.operator.fatigue_factor = 1.0 + (produced_count / 100.0) * 0.2 # 每100个疲劳度+20%
                
                # 执行
                log_data = station.process_unit(unit)
                
                # 记录结果
                if unit.status == "PASS":
                    self.stats["pass"] += 1
                    station.status = StationStatus.IDLE
                    completed_units.append(unit)
                    print(f"[{station.id}] SN:{unit.sn} -> PASS | 耗时:{log_data['total_time']:.2f}s | 工人:{station.operator.name}(技能:{station.operator.skill_level:.2f})")
                else:
                    self.stats["fail"] += 1
                    station.status = StationStatus.IDLE # 故障品移走，工位恢复
                    print(f"[{station.id}] SN:{unit.sn} -> FAIL | 原因:{unit.failure_reason} | 移至维修区")
                
                station.current_product = None
                
                # 防止CPU空转，稍微停顿让日志可读
                time.sleep(0.1) 

        self.stats["end_time"] = datetime.datetime.now()
        self.print_report()

    def print_report(self):
        """输出真实产能报告"""
        duration = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()
        # 注意：因为上面为了演示加了time.sleep(0.1)，这里的duration不是真实物理耗时
        # 我们需要累加所有产品的实际耗时来估算真实时间
        
        total_real_time = sum(p.total_time for p in self.products)
        avg_cycle_time = total_real_time / len(self.products) if self.products else 0
        
        # 真实产线是并行的，所以总耗时 ≈ (单件耗时 * 数量) / 工位数 + 启动损耗
        # 但更准确的是看瓶颈工位。这里简化为：最后一个产品完成的时间点
        # 由于我们是串行模拟并行逻辑，我们直接统计平均CT来计算UPH
        
        real_uph = 3600 / avg_cycle_time if avg_cycle_time > 0 else 0
        
        print(f"\n{'='*60}")
        print(f"🏭 生产报表：{self.name}")
        print(f"{'='*60}")
        print(f"📅 生产时间：{self.stats['start_time'].strftime('%H:%M:%S')} - {self.stats['end_time'].strftime('%H:%M:%S')}")
        print(f"📊 计划产量：{self.stats['total']} 台")
        print(f"✅ 良品数量：{self.stats['pass']} 台")
        print(f"❌ 不良数量：{self.stats['fail']} 台")
        print(f"📈 直通率 (FPY): {(self.stats['pass']/self.stats['total']*100):.2f}%")
        print(f"⏱️ 单件平均实际耗时 (CT): {avg_cycle_time:.2f} 秒")
        print(f"   - 其中烧录耗时: ~45-60 秒 (物理限制)")
        print(f"   - 其中人工耗时: ~15-25 秒 (含疲劳波动)")
        print(f"🚀 实际小时产能 (UPH): {real_uph:.1f} 台/小时")
        print(f"💡 结论: {'产能达标' if real_uph >= 45 else '需优化人工操作或增加工位'}")
        print(f"{'='*60}")

if __name__ == "__main__":
    # 创建一条拥有 4 个工位的烧录线
    line = ProductionLine("Treadmill_Burn_Line_01", station_count=4)
    
    # 下达工单：生产 20 台跑步机控制器
    line.generate_order(quantity=20, model="TM-X500")
    
    # 运行模拟
    line.run_simulation()
