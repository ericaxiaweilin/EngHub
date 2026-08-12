"""
Unit tests for Quality Red Tag service
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from core.qms.red_tag_service import RedTagService
from database.models import QualityRedTag


@pytest.fixture
def mock_db():
    """Mock database session"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def red_tag_service(mock_db):
    """Create RedTagService with mock DB"""
    return RedTagService(mock_db)


class TestRedTagService:
    """Tests for RedTagService"""
    
    @pytest.mark.asyncio
    async def test_create_red_tag(self, red_tag_service, mock_db):
        """Test creating a red tag"""
        # Mock the sequence query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_db.execute.return_value = mock_count_result
        
        # Mock the insert
        mock_red_tag = MagicMock(spec=QualityRedTag)
        mock_red_tag.id = "test-id-123"
        mock_red_tag.red_tag_no = "RT-20260802-0001"
        mock_db.refresh = AsyncMock()
        
        # Call create
        result = await red_tag_service.create_red_tag(
            factory_id="factory-1",
            defect_id="defect-1",
            red_tag_type="INCOMING",
            defect_description="Test defect",
            nonconforming_qty=10.0,
            severity="MAJOR"
        )
        
        # Verify
        assert result is not None
        assert result.red_tag_no.startswith("RT-")
        mock_db.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_red_tag(self, red_tag_service, mock_db):
        """Test getting a red tag by ID"""
        # Mock the query result
        mock_red_tag = MagicMock(spec=QualityRedTag)
        mock_red_tag.id = "test-id-123"
        mock_red_tag.red_tag_no = "RT-20260802-0001"
        mock_red_tag.defect_id = "defect-1"
        mock_red_tag.factory_id = "factory-1"
        mock_red_tag.red_tag_type = "INCOMING"
        mock_red_tag.defect_description = "Test defect"
        mock_red_tag.nonconforming_qty = 10.0
        mock_red_tag.severity = "MAJOR"
        mock_red_tag.quarantine_status = "SEATED"
        mock_red_tag.created_at = datetime.now()
        mock_red_tag.updated_at = datetime.now()
        mock_red_tag.attachments = []
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_red_tag
        mock_db.execute.return_value = mock_result
        
        # Call get
        result = await red_tag_service.get_red_tag("test-id-123")
        
        # Verify
        assert result is not None
        assert result["id"] == "test-id-123"
        assert result["red_tag_no"] == "RT-20260802-0001"
    
    @pytest.mark.asyncio
    async def test_list_red_tags(self, red_tag_service, mock_db):
        """Test listing red tags"""
        # Mock count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 5
        mock_db.execute.side_effect = [mock_count_result]
        
        # Mock list query
        mock_red_tag = MagicMock(spec=QualityRedTag)
        mock_red_tag.id = "test-id-123"
        mock_red_tag.red_tag_no = "RT-20260802-0001"
        mock_red_tag.defect_id = "defect-1"
        mock_red_tag.red_tag_type = "INCOMING"
        mock_red_tag.defect_description = "Test defect"
        mock_red_tag.nonconforming_qty = 10.0
        mock_red_tag.severity = "MAJOR"
        mock_red_tag.quarantine_status = "SEATED"
        mock_red_tag.created_at = datetime.now()
        
        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = [mock_red_tag]
        mock_db.execute.side_effect = [mock_count_result, mock_list_result]
        
        # Call list
        result = await red_tag_service.list_red_tags(factory_id="factory-1")
        
        # Verify
        assert result["total"] == 5
        assert len(result["red_tags"]) == 1
        assert result["red_tags"][0]["red_tag_no"] == "RT-20260802-0001"
    
    @pytest.mark.asyncio
    async def test_submit_disposition(self, red_tag_service, mock_db):
        """Test submitting disposition"""
        # Mock the query result
        mock_red_tag = MagicMock(spec=QualityRedTag)
        mock_red_tag.id = "test-id-123"
        mock_red_tag.red_tag_no = "RT-20260802-0001"
        mock_red_tag.defect_id = "defect-1"
        mock_red_tag.quarantine_status = "SEATED"
        mock_red_tag.created_at = datetime.now()
        mock_red_tag.updated_at = datetime.now()
        mock_red_tag.attachments = []
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_red_tag
        mock_db.execute.return_value = mock_result
        mock_db.refresh = AsyncMock()
        
        # Call submit disposition
        result = await red_tag_service.submit_disposition(
            red_tag_id="test-id-123",
            disposition="SCRAP",
            disposition_by="user-1"
        )
        
        # Verify
        assert result is not None
        assert result["disposition"] == "SCRAP"
        assert result["quarantine_status"] == "RELEASED"
        mock_db.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_statistics(self, red_tag_service, mock_db):
        """Test getting statistics"""
        # Mock status query
        mock_status_result = MagicMock()
        mock_status_result.all.return_value = [
            ("SEATED", 5),
            ("QUARANTINED", 3),
            ("RELEASED", 2)
        ]
        
        # Mock disposition query
        mock_disposition_result = MagicMock()
        mock_disposition_result.all.return_value = [
            ("SCRAP", 3),
            ("REWORK", 2)
        ]
        
        # Mock type query
        mock_type_result = MagicMock()
        mock_type_result.all.return_value = [
            ("INCOMING", 4),
            ("IN_PROCESS", 4),
            ("FINAL", 2)
        ]
        
        # Mock severity query
        mock_severity_result = MagicMock()
        mock_severity_result.all.return_value = [
            ("CRITICAL", 2),
            ("MAJOR", 5),
            ("MINOR", 3)
        ]
        
        mock_db.execute.side_effect = [
            mock_status_result,
            mock_disposition_result,
            mock_type_result,
            mock_severity_result
        ]
        
        # Call get statistics
        result = await red_tag_service.get_statistics("factory-1")
        
        # Verify
        assert result["total"] == 10
        assert result["by_status"]["SEATED"] == 5
        assert result["by_disposition"]["SCRAP"] == 3
        assert result["by_type"]["INCOMING"] == 4
        assert result["by_severity"]["CRITICAL"] == 2
    
    @pytest.mark.asyncio
    async def test_delete_red_tag(self, red_tag_service, mock_db):
        """Test soft deleting a red tag"""
        # Mock the query result
        mock_red_tag = MagicMock(spec=QualityRedTag)
        mock_red_tag.is_deleted = False
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_red_tag
        mock_db.execute.return_value = mock_result
        
        # Call delete
        result = await red_tag_service.delete_red_tag("test-id-123")
        
        # Verify
        assert result is True
        assert mock_red_tag.is_deleted is True
        mock_db.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_red_tags_by_defect(self, red_tag_service, mock_db):
        """Test getting red tags by defect ID"""
        # Mock the query result
        mock_red_tag = MagicMock(spec=QualityRedTag)
        mock_red_tag.id = "test-id-123"
        mock_red_tag.red_tag_no = "RT-20260802-0001"
        mock_red_tag.defect_id = "defect-1"
        mock_red_tag.red_tag_type = "INCOMING"
        mock_red_tag.defect_description = "Test defect"
        mock_red_tag.nonconforming_qty = 10.0
        mock_red_tag.severity = "MAJOR"
        mock_red_tag.quarantine_status = "SEATED"
        mock_red_tag.disposition = None
        mock_red_tag.created_at = datetime.now()
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_red_tag]
        mock_db.execute.return_value = mock_result
        
        # Call get red tags by defect
        result = await red_tag_service.get_red_tags_by_defect("defect-1")
        
        # Verify
        assert len(result) == 1
        assert result[0]["red_tag_no"] == "RT-20260802-0001"
        assert result[0]["defect_id"] == "defect-1"
