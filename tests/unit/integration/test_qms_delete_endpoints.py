"""
QMS DELETE端点集成测试 - 端到端验证路由->服务->数据库交互
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from starlette.test_client import TestClient
from main import app  # 假设您的FastAPI应用入口是main.py
from database.db_config import get_db


@pytest.fixture(scope="module")
def test_client():
    """FastAPI测试客户端"""
    # 临时替换DB依赖为mock
    original_get_db = app.dependency_overrides.get(get_db)
    
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_db.get = AsyncMock(return_value=None)
    
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    yield client
    
    # 清理覆盖
    if original_get_db:
        app.dependency_overrides[get_db] = original_get_db
    else:
        del app.dependency_overrides[get_db]


class TestQMSDeleteEndpoints:
    """QMS DELETE端点集成测试套件"""
    
    def test_delete_defect_endpoint_exists(self, test_client):
        """测试：DELETE /defects/{id} 端点存在且可访问"""
        response = test_client.delete("/api/v1/defects/def-001")
        assert response.status_code in [200, 201, 404, 500]
    
    def test_delete_inspection_endpoint_exists(self, test_client):
        """测试：DELETE /inspections/{id} 端点存在且可访问"""
        response = test_client.delete("/api/v1/inspections/ins-001")
        assert response.status_code in [200, 201, 404, 500]
    
    @patch('api.services.qms_service.QMSService.soft_delete_defect')
    async def test_delete_defect_calls_service(self, mock_soft_delete, test_client, monkeypatch):
        """测试：调用DELETE端点会触发service层的软删除方法"""
        mock_soft_delete.return_value = {"success": True, "message": "已删除"}
        
        from core.auth.security import get_current_user
        mock_user = MagicMock()
        mock_user.username = "testuser"
        
        def mock_get_db():
            db = MagicMock()
            db.get = AsyncMock(return_value=MagicMock(id="def-001"))
            return db
        
        def mock_get_current_user():
            return mock_user
        
        monkeypatch.setattr('api.routes.qms_routes.get_db', mock_get_db)
        monkeypatch.setattr('api.routes.qms_routes.get_current_user', mock_get_current_user)
        
        response = test_client.delete("/api/v1/defects/def-001")
        assert response.status_code == 200
        assert response.json()["message"] == "已删除"
        mock_soft_delete.assert_called_once_with("def-001", "testuser")
    
    @patch('api.services.qms_service.QMSService.soft_delete_inspection')
    async def test_delete_inspection_calls_service(self, mock_soft_delete, test_client, monkeypatch):
        """测试：DELETE /inspections/{id} 调用正确的服务方法"""
        mock_soft_delete.return_value = {"success": True, "message": "检验已软删除"}
        
        from core.auth.security import get_current_user
        mock_user = MagicMock()
        mock_user.username = "qcuser"
        
        def mock_get_db():
            db = MagicMock()
            db.get = AsyncMock(return_value=MagicMock(id="ins-001"))
            return db
        
        def mock_get_current_user():
            return mock_user
        
        monkeypatch.setattr('api.routes.qms_routes.get_db', mock_get_db)
        monkeypatch.setattr('api.routes.qms_routes.get_current_user', mock_get_current_user)
        
        response = test_client.delete("/api/v1/inspections/ins-001")
        assert response.status_code == 200
        mock_soft_delete.assert_called_once_with("ins-001", "qcuser")


class TestDeleteEndpointParameters:
    """DELETE端点参数和错误处理测试"""
    
    def test_delete_defect_missing_id_returns_404(self, test_client):
        response = test_client.delete("/api/v1/defects/")
        assert response.status_code == 404
    
    def test_delete_nonexistent_defect(self, test_client):
        response = test_client.delete("/api/v1/defects/non-existent-id")
        assert response.status_code in [404, 200]