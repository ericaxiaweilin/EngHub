"""Tests for WMS Architecture - RecoveryExecutor."""

import pytest
from api.services.wms_architecture.recovery.executor import (
    RecoveryExecutor,
    InsufficientStockRecovery,
    BatchConflictRecovery,
    SystemErrorRecovery,
    GenericFallbackRecovery,
)


class TestRecoveryExecutor:
    """Test RecoveryExecutor."""
    
    def test_register_and_execute(self):
        """Test registering and executing recovery strategies."""
        # Reset registry
        RecoveryExecutor.reset()
        
        # Register strategies
        RecoveryExecutor.register(InsufficientStockRecovery())
        RecoveryExecutor.register(BatchConflictRecovery())
        
        # Test insufficient stock recovery
        context = {"error": "库存不足"}
        result = RecoveryExecutor.execute_all(context)
        assert result is not None
        assert result.strategy_name == "insufficient_stock"
        assert result.applied is True
    
    def test_no_recovery_applies(self):
        """Test when no recovery strategy applies."""
        RecoveryExecutor.reset()
        RecoveryExecutor.register(InsufficientStockRecovery())
        
        # No matching error
        context = {"error": "Unknown error"}
        result = RecoveryExecutor.execute_all(context)
        assert result is None
    
    def test_generic_fallback(self):
        """Test generic fallback recovery."""
        RecoveryExecutor.reset()
        RecoveryExecutor.register(GenericFallbackRecovery())
        
        context = {"error": "Some error"}
        result = RecoveryExecutor.execute_all(context)
        assert result is not None
        assert result.strategy_name == "generic_fallback"
        assert result.context.get("degraded") is True
    
    def test_reset(self):
        """Test resetting the registry."""
        RecoveryExecutor.register(InsufficientStockRecovery())
        RecoveryExecutor.reset()
        
        context = {"error": "库存不足"}
        result = RecoveryExecutor.execute_all(context)
        assert result is None
    
    def test_initialize_default_strategies(self):
        """Test initializing default strategies."""
        RecoveryExecutor.reset()
        RecoveryExecutor.initialize_default_strategies()
        
        # Test all default strategies
        context1 = {"error": "库存不足"}
        result1 = RecoveryExecutor.execute_all(context1)
        assert result1 is not None
        assert result1.strategy_name == "insufficient_stock"
        
        context2 = {"error": "批次冲突"}
        result2 = RecoveryExecutor.execute_all(context2)
        assert result2 is not None
        assert result2.strategy_name == "batch_conflict"
        
        context3 = {"error": "system error"}
        result3 = RecoveryExecutor.execute_all(context3)
        assert result3 is not None
        assert result3.strategy_name == "system_error"
        
        context4 = {"error": "未知错误"}
        result4 = RecoveryExecutor.execute_all(context4)
        assert result4 is not None
        assert result4.strategy_name == "generic_fallback"