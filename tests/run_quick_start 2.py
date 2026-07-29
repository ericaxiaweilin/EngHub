#!/usr/bin/env python3
"""
单元测试快速启动脚本
执行核心模块的单元测试并生成覆盖率报告
"""

import subprocess
import sys
import os

def run_tests():
    """运行pytest测试"""
    project_root = os.path.dirname(os.path.abspath(__file__))
    cmd = [
        "pytest",
        "tests/unit",
        "-v",
        "--cov=api",
        "--cov-report=html",
        "-x"  # 第一个失败就停止
    ]
    
    print("=" * 60)
    print("🚀 开始执行单元测试...")
    print(f"项目根目录: {project_root}")
    print("=" * 60)
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        print("\n" + "=" * 60)
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        print("=" * 60)
        
        if result.returncode != 0:
            print("\n❌ 测试失败！请查看上面的错误信息。")
            return False
        
        print("\n✅ 所有测试通过！")
        print("📊 覆盖率报告生成在: htmlcov/index.html")
        return True
        
    except subprocess.TimeoutExpired:
        print("\n⏱️ 测试超时！")
        return False
    except Exception as e:
        print(f"\n❌ 测试执行出错: {e}")
        return False

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)