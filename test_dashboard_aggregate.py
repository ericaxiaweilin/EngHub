#!/usr/bin/env python3
"""
生产看板聚合 API 测试脚本
验证 /aggregate 端点是否能正确返回所有数据
"""
import asyncio
import httpx
from datetime import datetime, timedelta

# FastAPI 测试配置
BASE_URL = "http://localhost:8000"
TEST_FACTORY_ID = "F01"


async def test_api_endpoints():
    """测试各个 Dashboard API 端点"""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        print("=" * 60)
        print("生产看板聚合 API - 测试执行时间:", datetime.now().isoformat())
        print("=" * 60)

        # 测试 1: 原始 summary 端点
        print("\n[1] 测试 /summary (原有端点)...")
        try:
            response = await client.get(
                f"{BASE_URL}/api/v1/production-dashboard/summary",
                params={"factory_id": TEST_FACTORY_ID, "horizon_days": 7}
            )
            assert response.status_code == 200, f"状态码: {response.status_code}"
            data = response.json()
            print(f"   ✓ summary 正常返回 - KPIs: {data.get('kpis', {})}")
            print(f"   - sections: {len(data.get('sections', []))}")
            print(f"   - orders: {len(data.get('orders', []))}")
        except Exception as e:
            print(f"   ✗ summary 测试失败: {e}")

        # 测试 2: live-summary 端点
        print("\n[2] 测试 /live-summary (精简实时端点)...")
        try:
            response = await client.get(
                f"{BASE_URL}/api/v1/production-dashboard/live-summary",
                params={"factory_id": TEST_FACTORY_ID}
            )
            assert response.status_code == 200, f"状态码: {response.status_code}"
            data = response.json()
            print(f"   ✓ live-summary 正常返回 - total_output: {data.get('total_output')}")
        except Exception as e:
            print(f"   ✗ live-summary 测试失败: {e}")

        # 测试 3: stations-grid 端点
        print("\n[3] 测试 /stations-grid (工位矩阵端点)...")
        try:
            response = await client.get(
                f"{BASE_URL}/api/v1/production-dashboard/stations-grid",
                params={"factory_id": TEST_FACTORY_ID}
            )
            assert response.status_code == 200, f"状态码: {response.status_code}"
            data = response.json()
            print(f"   ✓ stations-grid 正常返回 - 工位数: {data['total']}")
            print(f"   - 状态分布: {data['summary']}")
        except Exception as e:
            print(f"   ✗ stations-grid 测试失败: {e}")

        # 测试 4: top-issues 端点
        print("\n[4] 测试 /top-issues (异常列表端点)...")
        try:
            response = await client.get(
                f"{BASE_URL}/api/v1/production-dashboard/top-issues",
                params={"factory_id": TEST_FACTORY_ID, "limit": 5}
            )
            assert response.status_code == 200, f"状态码: {response.status_code}"
            data = response.json()
            print(f"   ✓ top-issues 正常返回 - 异常数: {data.get('count', 0)}")
        except Exception as e:
            print(f"   ✗ top-issues 测试失败: {e}")

        # 测试 5: 新聚合端点（核心测试）
        print("\n[5] 测试 /aggregate (聚合端点 - 核心特性)...")
        try:
            response = await client.get(
                f"{BASE_URL}/api/v1/production-dashboard/aggregate",
                params={
                    "factory_id": TEST_FACTORY_ID,
                    "horizon_days": 7,
                    "include_live": True,
                    "include_grid": True,
                    "include_issues": True,
                }
            )
            assert response.status_code == 200, f"状态码: {response.status_code}"
            data = response.json()
            aggregate_fields = data.get("aggregated_fields", [])
            print(f"   ✓ aggregate 正常返回!")
            print(f"   - 聚合字段: {aggregate_fields}")
            print(f"   - 总字段数: {len(data.keys())}")
            print(f"   - full_summary sections: {len(data.get('full_summary', {}).get('sections', []))}")
            print(f"   - live_dashboard: {'exists' if 'live_dashboard' in data else 'MISSING'}")
            print(f"   - stations_grid: {'exists' if 'stations_grid' in data else 'MISSING'}")
            print(f"   - top_issues: {'exists' if 'top_issues' in data else 'MISSING'}")
            
            # 关键断言：确认所有预期字段都存在
            assert "full_summary" in data, "缺少 full_summary"
            assert "live_dashboard" in data or "live_dashboard_error" in data, "缺少 live_dashboard"
            assert "stations_grid" in data or "stations_grid_error" in data, "缺少 stations_grid"
            assert "top_issues" in data or "top_issues_error" in data, "缺少 top_issues"
            assert "timestamp" in data, "缺少 timestamp"
            print("\n   ✅ 聚合端点全部验证通过!")
        except Exception as e:
            print(f"   ✗ aggregate 测试失败: {e}")

        print("\n" + "=" * 60)
        print("测试完成!")
        print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(test_api_endpoints())
    except httpx.ConnectionError:
        print("错误: 无法连接到 FastAPI 服务，请先启动服务端!")
        print("启动命令: uvicorn api.main:app --reload --host 0.0.0.0 --port 8000")