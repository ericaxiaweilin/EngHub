# Quality Red Tag (质量红单) Implementation

## Overview
This implementation adds Quality Red Tag (质量红单) functionality to the QMS module for managing non-conforming products.

## Files Created/Modified

### Backend
1. **`database/migrations/063_quality_red_tag.sql`** - Database migration for red tag tables
2. **`core/qms/red_tag_service.py`** - Service layer for red tag operations
3. **`api/routes/qms_red_tag_routes.py`** - API routes for red tag management
4. **`database/models.py`** - Added QualityRedTag and QualityRedTagAttachment models
5. **`api/routes/__init__.py`** - Registered red tag routes
6. **`core/qms/__init__.py`** - Exported RedTagService

### Frontend
1. **`frontend/src/pages/qms/RedTagList.tsx`** - Red tag list page
2. **`frontend/src/pages/qms/RedTagDetail.tsx`** - Red tag detail page
3. **`frontend/src/pages/qms/RedTagCreate.tsx`** - Red tag creation page
4. **`frontend/src/pages/qms/DefectList.tsx`** - Updated to include red tag integration
5. **`frontend/src/pages/qms/index.tsx`** - QMS module entry point
6. **`frontend/src/services/modules/qms.ts`** - Red tag API service

### Scripts
1. **`scripts/apply_migration.py`** - Migration runner script

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/qms/red-tags/` | Create red tag |
| GET | `/api/v1/qms/red-tags/` | List red tags |
| GET | `/api/v1/qms/red-tags/statistics` | Get statistics |
| GET | `/api/v1/qms/red-tags/{id}` | Get red tag by ID |
| PUT | `/api/v1/qms/red-tags/{id}` | Update red tag |
| DELETE | `/api/v1/qms/red-tags/{id}` | Delete red tag |
| POST | `/api/v1/qms/red-tags/{id}/disposition` | Submit disposition |
| GET | `/api/v1/qms/red-tags/defects/{defect_id}/red-tags` | Get red tags by defect |

## Database Tables

### `quality_red_tag`
- `id` - Primary key
- `red_tag_no` - Unique red tag number (RT-YYYYMMDD-NNNN)
- `defect_id` - Foreign key to defect_records
- `red_tag_type` - INCOMING/IN_PROCESS/FINAL/CUSTOMER_RETURN
- `severity` - CRITICAL/MAJOR/MINOR
- `quarantine_status` - SEATED/QUARANTINED/RELEASED
- `disposition` - SCRAP/REWORK/USE_AS_IS/RTV/NO_DEFECT

### `quality_red_tag_attachments`
- `id` - Primary key
- `red_tag_id` - Foreign key to quality_red_tag
- `file_id` - Foreign key to files
- `attachment_type` - PHOTO/DOCUMENT/INSPECTION_REPORT

## Usage

### 1. Apply Migration
```bash
python3 scripts/apply_migration.py
```

### 2. Start Backend
```bash
python3 main.py
```

### 3. Access Frontend
Navigate to QMS module and click on "Red Tags (质量红单)" tab.

## Integration with Defects
- Red tags are linked to defects via `defect_id`
- Defect list includes "Red Tags" button to view associated red tags
- Red tag creation can be triggered from defect detail

## Business Flow
1. **Create** - Create red tag linked to defect
2. **Quarantine** - Move to quarantine status
3. **MRB Review** - Material Review Board evaluation
4. **Disposition** - Select disposition (Scrap/Rework/Use As Is/RTV/No Defect)
5. **Release** - Release from quarantine after disposition
