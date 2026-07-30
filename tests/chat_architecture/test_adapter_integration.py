"""Integration test for ChatAdapter with real DB session."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
from api.services.chat_service import ChatService
from api.services.chat_architecture.adapters.chat_adapter import ChatAdapter
from database.db_config import db_config


class TestChatAdapterIntegration:
    """Test that ChatAdapter components assemble correctly with real DB."""
    
    @pytest.mark.asyncio
    async def test_chat_service_creation(self):
        """Verify ChatService can be instantiated with real DB session."""
        async with db_config.session_factory() as db:
            # Create service - this should not raise any import errors
            service = ChatService(db=db, current_user=None)
            
            assert service is not None
            assert hasattr(service, 'adapter')
            assert isinstance(service.adapter, ChatAdapter)
            print("✅ ChatService created successfully")
    
    @pytest.mark.asyncio
    async def test_adapter_components_initialized(self):
        """Verify all components are properly initialized in ChatAdapter."""
        async with db_config.session_factory() as db:
            adapter = ChatAdapter(db=db)
            
            # Check all expected attributes exist
            assert hasattr(adapter, 'factory_resolver')
            assert hasattr(adapter, 'intent_resolver')
            assert hasattr(adapter, 'state_engine')
            assert hasattr(adapter, 'response_formatter')
            assert hasattr(adapter, 'recovery_executors')
            assert len(adapter.recovery_executors) == 3
            
            print(f"✅ Adapter initialized with {len(adapter.recovery_executors)} recovery strategies")
    
    @pytest.mark.asyncio
    async def test_factory_resolver_resolution(self):
        """Test factory resolution works correctly."""
        async with db_config.session_factory() as db:
            adapter = ChatAdapter(db=db)
            
            # Test with no http_request and no user -> returns default
            result = adapter.factory_resolver.resolve(None, None)
            assert result == "F01"
            
            print(f"✅ FactoryResolver returns: {result}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])