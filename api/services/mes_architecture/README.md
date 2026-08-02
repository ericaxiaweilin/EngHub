# MES Architecture - Orthogonal Design Documentation

## Overview

This directory contains the **orthogonally decomposed** MES (Manufacturing Execution System) architecture, refactored from the monolithic `mes_routes.py` and `mes_service.py`. The goal is to separate concerns using established software design patterns while preserving all existing functionality.

### Architectural Principles Applied

1. **Single Responsibility Principle (SRP)** - Each class/module has exactly one reason to change
2. **Dependency Inversion Principle (DIP)** - High-level modules don't depend on low-level details; both depend on abstractions
3. **Open/Closed Principle (OCP)** - Open for extension, closed for modification - add new strategies without touching core logic
4. **Separation of Concerns** - Routing, business logic, data access, presentation are fully decoupled

---

## Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    MES Adapter (Thin Layer)                 │
│  Routes → Request Parser → Validation → State Machine       │
│           ↓          ↓              ↓                      │
│   Repository     Recovery    Response Formatter             │
│   (Data Access)  Strategies   (DTO/JSON serialization)     │
└─────────────────────────────────────────────────────────────┘
            │                           │
            ▼                           ▼
     Database Models              Frontend Response
```

---

## Directory Structure

```
api/services/mes_architecture/
├── adapters/                  # Thin adapter classes (orchestrators)
│   └── mes_adapter.py         # Main MES entry point
├── repository/                # Data access layer
│   └── mes_repository.py      # All DB operations
├── formatter/                 # Response serialization
│   └── response_formatter.py  # ORM → DTO conversion
├── resolvers/                 # Input parsing & validation
│   └── request_parser.py      # Query param → Criteria objects
├── state_machine/             # State transition logic
│   └── work_order_state_machine.py  # FSM implementation
├── recovery/                  # Exception handling strategies
│   ├── base.py                # Abstract base class
│   ├── production/            # Production-related strategies
│   │   ├── capacity_limit_reject.py
│   │   └── material_shortage_pause.py
│   ├── quality/               # Quality-related strategies
│   │   └── defect_threshold_alert.py
│   └── equipment/             # Equipment-related strategies
│       └── failure_recovery.py
├── __init__.py                # Public API export
└── README.md                  # This file
```

---

## Key Concepts

### 1. Request Parser (`request_parser.py`)

**Responsibility:** Convert raw HTTP query parameters into typed `WorkOrderQueryCriteria` objects.

**Benefits:** Centralized parsing logic, easy testing, type safety.

```python
# Usage in route handler
criteria = MESRequestParser.parse_work_order_query(query_params)
results = await adapter.get_work_orders(criteria)
```

### 2. State Machine (`work_order_state_machine.py`)

**Responsibility:** Encapsulate valid work order state transitions with guard conditions.

**Key Features:**
- Explicit transition rules dictionary
- Guard condition hooks for pre-transition checks
- Terminal state detection (COMPLETED, CANCELLED)
- Pure functions (no side effects during validation)

```python
sm = WorkOrderStateMachine()
if sm.can_transition(from_status, to_status, context):
    # Safe to transition
    new_status = sm.transition(from_status, to_status)
```

### 3. Recovery Strategies (`recovery/`)

**Responsibility:** Handle exceptional conditions through composable strategies.

**Pattern Strategy:** Each strategy implements `MesRecoveryStrategy` interface with `should_apply()` and `execute()` methods. Strategies are applied sequentially in priority order.

**Example - Capacity Limit Reject:**
```python
strategy = CapacityLimitReject(default_capacity=100)
context = {"reported_qty": 150, "station_id": "ST-ASSY-01"}
result = strategy.execute(context)

if result.applied:
    # Handle rejection (return error to client)
else:
    # Continue with normal flow
```

### 4. Repository (`mes_repository.py`)

**Responsibility:** All database operations only. No business logic.

**Methods:**
- CRUD on work orders
- CRUD on production reports
- Count queries for pagination
- UUID generation helper

### 5. Response Formatter (`response_formatter.py`)

**Responsibility:** Convert ORM models to JSON-serializable DTOs.

**Why separate?** Clean separation between domain models and API contracts. Allows evolving the API without changing domain models.

```python
formatter = ResponseFormatter()
dto = formatter.format_work_order(work_order_orm_object)
```

---

## Migration Guide (from monolithic to architectured)

### Before (monolithic `mes_routes.py`)

```python
@router.get("/work-orders")
async def list_work_orders(...):
    # ALL IN ONE FUNCTION:
    # 1. Parse params
    # 2. Check auth/factory access
    # 3. Build SQL query
    # 4. Execute DB query
    # 5. Calculate totals/pagination
    # 6. Loop through results to compute progress
    # 7. Return mixed ORM + calculated data
```

### After (adapter pattern)

```python
@router.get("/work-orders")
async def list_work_orders(adapter: MESAdapter = Depends(get_mes_adapter)):
    # ONLY TWO LINES OF BUSINESS LOGIC:
    criteria = parse_query_params(request.query_params)
    return await adapter.get_work_orders(criteria)
```

The adapter now handles all complexity internally, keeping routes thin and testable.

---

## Running Tests

```bash
# Run all MES architecture tests
pytest tests/mes_architecture/ -v

# Specific test categories
pytest tests/mes_architecture/test_state_machine.py -v
pytest tests/mes_architecture/test_adapter.py -v
pytest tests/mes_architecture/test_integration.py -v
```

These tests serve as **characterization tests** - they capture current behavior before any further changes, ensuring regressions are detected if we modify the architecture later.

---

## Compatibility Note

This new architecture is designed to be **incrementally adoptable**. The existing `mes_routes.py` can remain functional alongside this new architecture, with migration happening over multiple releases. Endpoints have identical request/response shapes, so frontend clients won't notice any difference.