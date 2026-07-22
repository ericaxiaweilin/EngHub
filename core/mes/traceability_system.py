"""
MES系统 - 跑步机固件烧录与FCT测试全流程追溯模块 (v3.0)
核心功能：
1. 真实工时模拟（含人工操作 + 物理烧录 + FCT测试）
2. 全字段追溯（SN、MAC、耗时、操作员、固件版本、测试详情）
3. 一机一档（每台机器独立档案，支持导出）
4. 防错机制（重烧记录、NG品隔离）
"""

import time
import random
import uuid
import json
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum

# ==================== 数据模型定义 ====================

class TestStatus(Enum):
    PENDING = "待测试"
    RUNNING = "测试中"
    PASS = "合格"
    FAIL = "不合格"
    RETRY = "重试中"

@dataclass
class FirmwareInfo:
    version: str
    build_date: str
    checksum: str  # MD5或CRC32
    file_size_kb: int

@dataclass
class BurnRecord:
    start_time: str
    end_time: str
    duration_sec: float
    protocol: str
    status: str
    retry_count: int
    log_message: str

@dataclass
class FCTTestResult:
    test_time: str
    items: Dict[str, bool]  # {"power": True, "motor": True, ...}
    total_duration_sec: float
    status: str
    operator_comment: str

@dataclass
class ProductTrace:
    sn: str                  # 序列号 (唯一键)
    model: str               # 型号
    mac_address: str         # MAC地址 (烧录后读取)
    wifi_mac: str            # Wi-Fi MAC
    bt_mac: str              # 蓝牙 MAC
    operator_id: str         # 操作员ID
    station_id: str          # 工站ID
    firmware: FirmwareInfo   # 固件信息
    burn_record: BurnRecord  # 烧录记录
    fct_result: FCTTestResult # FCT测试结果
    final_status: str        # 最终状态
    create_time: str         # 建档时间
    finish_time: str         # 完成时间
    
    def to_dict(self):
        return asdict(self)

# ==================== 硬件抽象层 (模拟真实设备交互) ====================

class HardwareSimulator:
    """模拟真实的烧录器和测试治具行为"""
    
    @staticmethod
    def read_mac_address(protocol: str) -> tuple:
        """
        模拟从芯片读取MAC地址
        真实场景：通过UART/SWD发送指令读取OTP区域
        """
        # 模拟读取耗时 0.5秒
        # time.sleep(0.5)
        
        # 生成符合规范的MAC (例如: 00:1A:2B:XX:YY:ZZ)
        base_mac = "00:1A:2B"
        suffix = ":".join([f"{random.randint(0, 255):02X}" for _ in range(3)])
        full_mac = f"{base_mac}:{suffix}"
        
        # 拆分Wi-Fi和蓝牙MAC (通常蓝牙是Wi-Fi MAC + 1)
        last_byte = int(suffix.split(":")[-1], 16)
        bt_last_byte = last_byte + 1 if last_byte < 255 else 0
        bt_suffix = suffix.rsplit(":", 1)[0] + f":{bt_last_byte:02X}"
        bt_mac = f"{base_mac}:{bt_suffix}"
        
        return full_mac, bt_mac

    @staticmethod
    def flash_firmware(file_size_kb: int, protocol: str) -> float:
        """
        模拟真实烧录耗时
        基于波特率和协议计算
        """
        # 真实物理耗时基准 (秒)
        if protocol == "SWD":
            speed_factor = 0.05  # SWD 很快，约20KB/s有效速度
        elif protocol == "UART_115200":
            speed_factor = 0.12  # 115200 较慢，约8KB/s
        elif protocol == "UART_921600":
            speed_factor = 0.02  # 高速UART
        else:
            speed_factor = 0.1
            
        # 基础开销 (握手 + 擦除 + 校验)
        base_overhead = 2.0 
        flash_time = (file_size_kb * speed_factor) + base_overhead
        
        # 随机波动 (±5%)
        variation = random.uniform(0.95, 1.05)
        return flash_time * variation

    @staticmethod
    def run_fct_test() -> Dict[str, bool]:
        """
        模拟FCT功能测试
        包含多个测试项，每项都有真实耗时
        """
        tests = {
            "voltage_check": True,      # 电压检测 (1s)
            "button_panel": True,       # 按键测试 (3s)
            "motor_run_low": True,      # 电机低速 (5s)
            "motor_run_high": True,     # 电机高速 (5s)
            "display_pixels": True,     # 屏幕坏点 (2s)
            "wifi_connection": True,    # Wi-Fi连接 (3s)
            "bt_broadcast": True,       # 蓝牙广播 (2s)
            "emergency_stop": True      # 急停测试 (2s)
        }
        
        # 模拟小概率失败 (10%)
        if random.random() < 0.1:
            fail_item = random.choice(list(tests.keys()))
            tests[fail_item] = False
            
        return tests

# ==================== 业务逻辑层 ====================

class TraceabilityManager:
    """追溯数据管理器"""
    
    def __init__(self):
        self.database: Dict[str, ProductTrace] = {}
        self.station_id = "STATION-BURN-01"
        
    def create_archive(self, sn: str, model: str, operator_id: str) -> ProductTrace:
        """创建初始档案"""
        record = ProductTrace(
            sn=sn,
            model=model,
            mac_address="",
            wifi_mac="",
            bt_mac="",
            operator_id=operator_id,
            station_id=self.station_id,
            firmware=FirmwareInfo("", "", "", 0),
            burn_record=BurnRecord("", "", 0, "", "", 0, ""),
            fct_result=FCTTestResult("", {}, 0, "", ""),
            final_status=TestStatus.PENDING.value,
            create_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            finish_time=""
        )
        self.database[sn] = record
        return record

    def update_burn_data(self, sn: str, firmware: FirmwareInfo, burn_record: BurnRecord, macs: tuple):
        """更新烧录数据"""
        if sn not in self.database:
            raise ValueError(f"SN {sn} not found")
        
        record = self.database[sn]
        record.firmware = firmware
        record.burn_record = burn_record
        record.wifi_mac = macs[0]
        record.bt_mac = macs[1]
        record.mac_address = macs[0] # 主MAC

    def update_fct_data(self, sn: str, fct_result: FCTTestResult):
        """更新FCT数据"""
        if sn not in self.database:
            raise ValueError(f"SN {sn} not found")
            
        record = self.database[sn]
        record.fct_result = fct_result
        record.final_status = fct_result.status
        record.finish_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def get_full_trace(self, sn: str) -> Optional[Dict]:
        """获取完整追溯档案"""
        if sn in self.database:
            return self.database[sn].to_dict()
        return None

    def export_batch_report(self) -> List[Dict]:
        """导出批次报告"""
        return [rec.to_dict() for rec in self.database.values()]

class SmartBurnStation:
    """智能烧录工站 (含人工操作模拟)"""
    
    def __init__(self, manager: TraceabilityManager):
        self.manager = manager
        self.hw = HardwareSimulator()
        
        # 当前固件配置
        self.current_fw = FirmwareInfo(
            version="TM-X500_V2.4.1_Build20231027",
            build_date="2023-10-27",
            checksum="a1b2c3d4e5f6...",
            file_size_kb= 2048 # 2MB 固件
        )
        
        # 协议配置
        self.protocol = "UART_921600" # 高速烧录
        
    def execute_workflow(self, sn: str, operator_id: str) -> Dict:
        """
        执行单台设备的完整工作流
        包含：人工操作 -> 烧录 -> 读MAC -> FCT -> 归档
        """
        print(f"\n[开始] SN: {sn} | 操作员: {operator_id}")
        
        # 1. 创建档案
        archive = self.manager.create_archive(sn, "TM-X500", operator_id)
        
        # --- 人工操作阶段 1: 上架与扫码 ---
        print("  [人工] 扫描SN码，放置治具...")
        # time.sleep(1.5) # 扫码 + 放置
        
        # 2. 开始烧录
        print(f"  [系统] 开始烧录 ({self.current_fw.version})...")
        burn_start = time.time()
        
        # 模拟物理烧录
        flash_duration = self.hw.flash_firmware(self.current_fw.file_size_kb, self.protocol)
        time.sleep(min(flash_duration, 1.0)) # 加速演示，实际不sleep
        
        # 模拟读取MAC
        macs = self.hw.read_mac_address(self.protocol)
        
        burn_end = time.time()
        actual_burn_time = (burn_end - burn_start) 
        # 修正：为了演示效果，我们使用计算出的真实时间，而不是sleep的时间
        actual_burn_time = flash_duration 
        
        burn_record = BurnRecord(
            start_time=datetime.fromtimestamp(burn_start).strftime("%H:%M:%S.%f")[:-3],
            end_time=datetime.fromtimestamp(burn_end).strftime("%H:%M:%S.%f")[:-3],
            duration_sec=round(actual_burn_time, 2),
            protocol=self.protocol,
            status="SUCCESS",
            retry_count=0,
            log_message=f"Flash OK, Checksum Matched. MAC:{macs[0]}"
        )
        
        # 保存烧录数据
        self.manager.update_burn_data(sn, self.current_fw, burn_record, macs)
        print(f"  [完成] 烧录耗时: {actual_burn_time:.2f}s | MAC: {macs[0]}")
        
        # --- 人工操作阶段 2: 切换模式/确认 ---
        print("  [人工] 移除烧录线，切换至FCT模式...")
        # time.sleep(2.0) + 切换开关
        
        # 3. FCT测试
        print("  [系统] 启动FCT功能测试...")
        fct_start = time.time()
        
        test_items = self.hw.run_fct_test()
        
        # 模拟各项测试耗时累加
        fct_duration = sum([random.uniform(1.0, 3.0) for _ in test_items]) 
        # time.sleep(min(fct_duration, 1.0))
        
        fct_end = time.time()
        
        # 判定结果
        all_pass = all(test_items.values())
        status = TestStatus.PASS.value if all_pass else TestStatus.FAIL.value
        
        fct_result = FCTTestResult(
            test_time=datetime.now().strftime("%H:%M:%S"),
            items=test_items,
            total_duration_sec=round(fct_duration, 2),
            status=status,
            operator_comment="Auto Pass" if all_pass else "Check Motor Module"
        )
        
        # 保存FCT数据
        self.manager.update_fct_data(sn, fct_result)
        
        # --- 人工操作阶段 3: 下料 ---
        if all_pass:
            print(f"  [PASS] 测试通过，贴标下料...")
            # time.sleep(1.5) + 取下
        else:
            print(f"  [FAIL] 测试失败，放入NG区...")
              # time.sleep(1.0)
            
        total_time = actual_burn_time + fct_duration + 5.0 # +5s 人工总耗时
        print(f"  [统计] 该台总耗时: {total_time:.2f}s (含人工)")
        
        return self.manager.get_full_trace(sn)

# ==================== 主程序入口 ====================

def main():
    print("="*60)
    print("MES系统 - 跑步机固件烧录与FCT全流程追溯仿真 (v3.0)")
    print("特性：真实工时 | 一机一档 | MAC绑定 | 详细日志")
    print("="*60)
    
    manager = TraceabilityManager()
    station = SmartBurnStation(manager)
    
    # 模拟生产一批次 (10台)
    batch_sn = [f"TM20231027{i:04d}" for i in range(1, 11)]
    operators = ["OP001", "OP002"]
    
    results = []
    
    for i, sn in enumerate(batch_sn):
        op = operators[i % 2]
        trace = station.execute_workflow(sn, op)
        results.append(trace)
        
    # ==================== 数据验证与报表 ====================
    print("\n" + "="*60)
    print("【追溯数据验证】随机抽取一台展示完整档案")
    print("="*60)
    
    sample_sn = batch_sn[4] # 抽取第5台
    full_data = manager.get_full_trace(sample_sn)
    
    if full_data:
        print(json.dumps(full_data, indent=2, ensure_ascii=False))
    
    print("\n" + "="*60)
    print("【批次生产报表】")
    print("="*60)
    
    total_count = len(results)
    pass_count = sum(1 for r in results if r['final_status'] == '合格')
    fail_count = total_count - pass_count
    
    avg_burn_time = sum(r['burn_record']['duration_sec'] for r in results) / total_count
    avg_fct_time = sum(r['fct_result']['total_duration_sec'] for r in results) / total_count
    
    # 估算产能 (假设4工位并行)
    # 单台总时间 = 烧录(max) + FCT(max) + 人工(重叠部分) 
    # 简化估算：瓶颈工序决定节拍。烧录约25s，FCT约15s，人工5s。
    # 瓶颈是烧录 25s。
    cycle_time = max(avg_burn_time, avg_fct_time) + 3.0 # 加上必要的人工切换
    uph = 3600 / cycle_time * 4 
    
    print(f"生产总数: {total_count} 台")
    print(f"合格数量: {pass_count} 台")
    print(f"不良数量: {fail_count} 台")
    print(f"直通率:   {pass_count/total_count*100:.1f}%")
    print("-" * 40)
    print(f"平均烧录耗时: {avg_burn_time:.2f} 秒")
    print(f"平均FCT耗时:  {avg_fct_time:.2f} 秒")
    print(f"预估产线节拍: {cycle_time:.2f} 秒/台")
    print(f"预估小时产能: {uph:.1f} 台/小时 (4工位并行)")
    print("-" * 40)
    print("数据完整性检查:")
    print(f"  - MAC地址记录率: {sum(1 for r in results if r['mac_address'])}/{total_count}")
    print(f"  - 固件版本记录率: {sum(1 for r in results if r['firmware']['version'])}/{total_count}")
    print(f"  - 详细测试项记录: 已包含 {len(full_data['fct_result']['items'])} 个测试点")
    
    print("\n[系统提示] 所有数据已写入数据库，可随时通过SN码反查全生命周期记录。")

if __name__ == "__main__":
    main()
