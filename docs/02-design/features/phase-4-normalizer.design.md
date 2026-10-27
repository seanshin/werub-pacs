# Design: Phase 4 — DICOM Normalizer Enhancements

**Date**: 2026-05-14  
**Phase**: Design (Phase 4)  
**Status**: READY FOR IMPLEMENTATION  
**Author**: AI Assistant (PDCA)

---

## 1. Executive Summary

This design document provides detailed technical specifications for Phase 4 (DICOM Normalizer Enhancements), building on Phase 3's single-instance normalization to introduce **scalable batch processing, supplier-specific rules, and administrative visibility**. The system enables bulk retrospective normalization of legacy archives, detects and applies vendor-specific corrections, and provides real-time monitoring through a comprehensive admin dashboard.

**Key Design Decisions**:
- **Async Celery Processing**: Handle 1,000+ file batches without API timeout
- **Plugin Architecture**: Extensible supplier-specific normalizers (Siemens, GE, Philips)
- **Manual Review Workflow**: Medium-risk changes (PhotometricInterpretation) require approval
- **Configuration System**: Per-modality algorithm toggles, safety limits in database
- **Backward Compatible**: All Phase 3 APIs unchanged; new features additive only

**Implementation Scope**: ~2,500-3,500 lines of code across backend services, API endpoints, database schema, and admin dashboard.

---

## 2. Architecture Overview

### 2.1 System Component Diagram

```
┌───────────────────────────────────────────────────────────────────┐
│                          CLIENT LAYER                             │
├────────────────────────┬────────────────────┬────────────────────┤
│   Web Dashboard        │   Admin UI         │   CLI / Postman    │
│  (React/Next.js)       │  (batch mgmt)      │  (testing)         │
└────────────┬───────────┴────────┬───────────┴────────────┬────────┘
             │                    │                        │
┌────────────▼────────────────────▼────────────┬──────────▼────────┐
│              FASTAPI API LAYER                │                   │
├──────────────────────────────────────────────┤                   │
│ POST /dicomweb/batch-normalize               │ (STOW-RS          │
│ GET  /normalization/batch/{batch_id}         │  single-file      │
│ GET  /normalization/batch/{batch_id}/stream  │  endpoints        │
│ GET  /admin/normalization/config             │  unchanged)       │
│ PUT  /admin/normalization/config             │                   │
│ GET  /admin/normalization/audit              │                   │
└────────────┬──────────────────────────────────┴───────────────────┘
             │
             ├─────────────────────────────────────────────────┐
             │                                                 │
   ┌─────────▼──────────────┐                   ┌─────────────▼─────────┐
   │ BATCH OPERATIONS       │                   │ CONFIG MANAGEMENT     │
   │ (batch_operations.py)  │                   │ (config_service.py)   │
   │                        │                   │                       │
   │ • Parse zip/multipart  │                   │ • Load config         │
   │ • Validate file count  │                   │ • Cache (Redis TTL)   │
   │ • Enqueue to Celery    │                   │ • Per-modality rules  │
   │ • Track batch status   │                   │ • Risk tier mapping   │
   └─────────┬──────────────┘                   └───────────────────────┘
             │
   ┌─────────▼─────────────────────────────────────────────────────────┐
   │                   CELERY TASK CHAIN                               │
   │  (batch_normalizer.py with @shared_task decorators)              │
   │                                                                    │
   │  batch_upload_task                                                │
   │    ├─ Extract files from zip                                     │
   │    ├─ Validate DICOM magic bytes                                 │
   │    └─ Create batch_job_files records                             │
   │        ↓                                                          │
   │  [chord] Parallel worker tasks                                    │
   │    ├─ validate_file_task (per file)                              │
   │    ├─ normalize_file_task (per file)                             │
   │    │   ├─ Detect manufacturer (SupplierRegistry)                │
   │    │   ├─ Apply supplier rules (if enabled)                      │
   │    │   ├─ Re-validate post-normalization                         │
   │    │   └─ Check medium-risk items                                │
   │    ├─ store_file_task (per file, if valid)                      │
   │    └─ audit_file_task (per file)                                 │
   │        ↓                                                          │
   │  finalize_batch_task                                              │
   │    ├─ Update batch_jobs status                                   │
   │    ├─ Generate final report                                      │
   │    └─ Cleanup temp files                                         │
   └─────────┬──────────────────────────────────────────────────────┘
             │
   ┌─────────▼──────────────────────┐    ┌─────────────────────┐
   │  SUPPLIER REGISTRY             │    │ SERVICE LAYER       │
   │  (supplier_registry.py)        │    │                     │
   │                                │    │ • DicomValidator    │
   │  ├─ Manufacturer detection     │    │ • DicomNormalizer   │
   │  ├─ Plugin registry            │    │ • Orthanc Client    │
   │  ├─ SiemensNormalizer          │    │ • AuditLogger       │
   │  ├─ GENormalizer               │    │                     │
   │  └─ PhilipsNormalizer          │    └─────────────────────┘
   └────────────────────────────────┘
             │
   ┌─────────▼──────────────────────────────────────────────────────────┐
   │                    DATA PERSISTENCE LAYER                          │
   │                                                                     │
   │  PostgreSQL                                   Redis Queue          │
   │  ├─ batch_jobs                                ├─ Celery tasks     │
   │  ├─ batch_job_files                           ├─ Progress tracking│
   │  ├─ normalization_config                      └─ Config cache     │
   │  ├─ normalization_reviews (medium-risk)                           │
   │  ├─ audit_logs (extended)                                         │
   │  └─ supplier_rules (versioned)                                    │
   │                                                                     │
   │  Temporary Storage                            Orthanc             │
   │  ├─ /tmp/batch-{batch_id}/  (cleanup after)  ├─ Store normalized │
   │  └─ [Alternative: Redis if < 500MB]          └─ Query instances  │
   └─────────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow: Upload → Process → Store

```
User Upload (ZIP or Multipart)
    │
    ▼
FastAPI: POST /dicomweb/batch-normalize
    │
    ├─ [Validation] File size, format, DICOM magic bytes
    │
    ├─ [Create Batch Job] Insert batch_jobs row, status='queued'
    │                    Return batch_id + status immediately (<2s)
    │
    └─ [Enqueue Celery] batch_upload_task(batch_id)
        │
        ├─ Extract ZIP → temp storage (/tmp/batch-{batch_id}/)
        ├─ Validate file count < MAX_FILES
        └─ Create batch_job_files records (one per DICOM)
            │
            └─ Update batch_jobs: status='processing', total_files=N
                │
                └─ [CHORD] Parallel validation/normalization
                    │
                    ├──────────────────────────────────────┐
                    │                                       │
                    ▼                                       ▼
                [File 1]                                 [File 2...]
                    │
                    ├─ validate_file_task()
                    │   └─ DicomValidator.validate()
                    │       └─ Update batch_job_files: status='validated'
                    │
                    ├─ normalize_file_task()
                    │   ├─ Load normalized dataset
                    │   ├─ SupplierRegistry.auto_detect(ds)
                    │   ├─ Apply supplier rules (if enabled)
                    │   ├─ Apply phase-3 normalizer
                    │   ├─ Check medium-risk items
                    │   │   └─ If yes: Insert normalization_reviews row (paused)
                    │   └─ Update batch_job_files: status='normalized'
                    │
                    ├─ store_file_task()
                    │   ├─ Orthanc.post(/dicomweb/studies, normalized_ds)
                    │   └─ Update batch_job_files: status='stored'
                    │
                    └─ audit_file_task()
                        └─ Insert audit_logs (supplier, changes, user_id)
                    │
                    └─ (All complete) finalize_batch_task()
                        │
                        ├─ Count succeeded/failed
                        ├─ Generate report JSON
                        ├─ Cleanup temp files
                        ├─ Update batch_jobs: status='completed'
                        └─ Notify user (optional)
```

### 2.3 Async Pattern with WebSocket/Polling

```
Client                          Server
  │                              │
  ├─ POST /batch-normalize ────> │
  │                              │ [Enqueue Celery]
  │ <──── batch_id response ────┤
  │                              │
  ├─ WebSocket /batch/{id}/stream
  │        (optional)     ────> │ [Subscribe to progress]
  │ <── progress updates ──────┤
  │     every N seconds         │
  │                              │
  │  OR  (polling alternative)   │
  │                              │
  ├─ GET /batch/{id} status ──> │
  │ <──── status response ──────┤ (file-level status)
  │                              │
  │  (repeat poll every 2-5s)    │
  │                              │
  └─ GET /batch/{id}/report ──> │ [once complete]
      <──── JSON report ────────┤
```

---

## 3. API Specifications

### 3.1 Endpoint 1: Batch Upload & Normalize

**POST /api/v1/dicomweb/batch-normalize**

**Purpose**: Upload and asynchronously normalize a batch of DICOM files.

**Request**:
```
Content-Type: multipart/form-data

Parameters:
  files*           [File[]]  Multiple DICOM files or single ZIP
  supplier         [string]  Optional: "siemens", "ge", "philips", "auto"
                             Default: "auto" (auto-detect per file)
  auto_normalize   [bool]    Apply normalization rules
                             Default: true
  max_changes      [int]     Safety limit: max corrections per file
                             Default: 10 (from config)
  modality         [string]  Optional filter: "CT", "MR", "US", etc.
                             Used for config-driven algorithm selection
```

**Request Example (cURL)**:
```bash
curl -X POST http://localhost:8000/api/v1/dicomweb/batch-normalize \
  -F "files=@batch.zip" \
  -F "supplier=auto" \
  -F "auto_normalize=true" \
  -F "max_changes=10" \
  -H "Authorization: Bearer {token}"
```

**Response (201 Created)**:
```json
{
  "batch_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "total_files": 150,
  "processed": 0,
  "succeeded": 0,
  "failed": 0,
  "pending_review": 0,
  "progress_percent": 0,
  "progress_url": "/api/v1/normalization/batch/550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2026-05-14T10:30:45Z",
  "estimated_completion_sec": 210,
  "supplier_distribution": {
    "siemens": 50,
    "ge": 45,
    "philips": 30,
    "unknown": 25
  }
}
```

**Error Responses**:
- `400 Bad Request`: File count exceeds MAX_FILES (1000), invalid zip
- `413 Payload Too Large`: Total size exceeds max (100MB)
- `401 Unauthorized`: Invalid token
- `500 Internal Server Error`: Celery queue unavailable

---

### 3.2 Endpoint 2: Batch Progress & Results

**GET /api/v1/normalization/batch/{batch_id}**

**Purpose**: Get current status and per-file details for a batch.

**Query Parameters**:
```
include_files  [bool]  Include file-level status (large response)
               Default: false
skip           [int]   Pagination offset for files
               Default: 0
limit          [int]   Max files to return (50-500)
               Default: 100
```

**Response (200 OK)**:
```json
{
  "batch_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user123",
  "status": "processing",
  "status_description": "Normalizing files...",
  "total_files": 150,
  "processed": 87,
  "succeeded": 85,
  "failed": 2,
  "pending_review": 12,
  "progress_percent": 58,
  "supplier": "auto",
  "created_at": "2026-05-14T10:30:45Z",
  "started_at": "2026-05-14T10:31:00Z",
  "estimated_completion_sec": 85,
  
  "summary": {
    "algorithms": {
      "pixel_spacing": 34,
      "missing_tags": 18,
      "photometric": 12,
      "charset": 5
    },
    "suppliers": {
      "siemens": 45,
      "ge": 30,
      "philips": 12
    },
    "risk_distribution": {
      "safe": 64,
      "medium": 12,
      "risky": 0
    }
  },

  "files": [
    {
      "sequence": 1,
      "filename": "CT_001.dcm",
      "status": "stored",
      "sop_instance_uid": "1.2.3.4.5",
      "study_instance_uid": "1.2.3",
      "modality": "CT",
      "supplier": "siemens",
      "changes_count": 2,
      "changes": [
        {
          "tag_keyword": "PixelSpacing",
          "original_value": null,
          "corrected_value": "0.5\\0.5",
          "rationale": "Extracted from Siemens private tag (0019,1008)",
          "risk_level": "safe",
          "category": "pixel_spacing"
        }
      ],
      "error": null,
      "processing_ms": 45,
      "created_at": "2026-05-14T10:31:05Z"
    },
    {
      "sequence": 2,
      "filename": "CT_002.dcm",
      "status": "pending_review",
      "error": null,
      "changes": [
        {
          "tag_keyword": "PhotometricInterpretation",
          "corrected_value": "MONOCHROME2",
          "risk_level": "medium",
          "category": "photometric"
        }
      ]
    },
    {
      "sequence": 3,
      "filename": "CT_003.dcm",
      "status": "failed",
      "error": "PhotometricInterpretation inference confidence < 50%"
    }
  ],

  "error_summary": {
    "total_errors": 2,
    "by_type": {
      "photometric_inference_failed": 1,
      "validation_failed": 1
    }
  }
}
```

**GET /api/v1/normalization/batch/{batch_id}/stream (WebSocket)**

**Purpose**: Real-time progress updates (optional, polling fallback recommended for MVP).

**WebSocket Message Format**:
```json
{
  "event": "progress_update|file_completed|file_failed|batch_complete",
  "timestamp": "2026-05-14T10:31:30Z",
  "payload": {
    "processed": 88,
    "succeeded": 85,
    "failed": 2,
    "pending_review": 12,
    "progress_percent": 59
  }
}
```

**GET /api/v1/normalization/batch/{batch_id}/report**

**Purpose**: Download final report in JSON or CSV format.

**Query Parameters**:
```
format  [string]  "json" (default) or "csv"
```

**Response (JSON)**:
```json
{
  "batch_id": "550e8400-e29b-41d4-a716-446655440000",
  "summary": { /* ... */ },
  "files": [ /* ... */ ],
  "exported_at": "2026-05-14T10:35:00Z"
}
```

**Response (CSV)**:
```csv
sequence,filename,status,sop_instance_uid,modality,supplier,changes_count,error,processing_ms
1,CT_001.dcm,stored,1.2.3.4.5,CT,siemens,2,,45
2,CT_002.dcm,pending_review,1.2.3.4.6,CT,siemens,1,,52
3,CT_003.dcm,failed,1.2.3.4.7,CT,ge,,PhotometricInterpretation inference failed,1000
```

---

### 3.3 Endpoint 3: Configuration Management

**GET /api/v1/admin/normalization/config**

**Purpose**: Retrieve current normalization configuration.

**Response (200 OK)**:
```json
{
  "safety_limits": {
    "max_changes_per_file": 10,
    "max_files_per_batch": 1000,
    "batch_timeout_ms": 5000,
    "deviation_tolerance_pct": 20.0,
    "charset_confidence_threshold": 0.85
  },

  "algorithms_by_modality": {
    "CT": {
      "enabled": ["pixel_spacing", "missing_tags", "photometric", "charset"],
      "disabled": []
    },
    "MR": {
      "enabled": ["pixel_spacing", "missing_tags", "charset"],
      "disabled": ["photometric"]
    },
    "US": {
      "enabled": ["pixel_spacing", "missing_tags"],
      "disabled": ["photometric", "charset"]
    },
    "_default": {
      "enabled": ["pixel_spacing", "missing_tags"],
      "disabled": ["photometric", "charset"]
    }
  },

  "supplier_rules": {
    "siemens": {
      "enabled": true,
      "version": "1.0",
      "description": "Siemens-specific: PixelSpacing from 0019,1008; Photometric from 0019,1010",
      "risk_level": "medium",
      "last_modified": "2026-05-13T15:00:00Z",
      "rules": [
        {
          "name": "extract_pixel_spacing_from_private_tag",
          "enabled": true,
          "risk": "safe"
        },
        {
          "name": "infer_photometric_from_vendor_tag",
          "enabled": true,
          "risk": "medium"
        }
      ]
    },
    "ge": {
      "enabled": true,
      "version": "1.0",
      "description": "GE-specific: PhotometricInterpretation inference, SamplesPerPixel correction",
      "risk_level": "medium",
      "rules": [
        {
          "name": "infer_photometric_from_jpeg_markers",
          "enabled": true,
          "risk": "medium"
        },
        {
          "name": "correct_samples_per_pixel_grayscale_jpeg",
          "enabled": true,
          "risk": "safe"
        }
      ]
    },
    "philips": {
      "enabled": false,
      "version": "1.0",
      "description": "Philips-specific: JPEG artifact detection, vendor encoding",
      "risk_level": "medium_high",
      "rules": []
    }
  },

  "risk_handling": {
    "safe": "auto_apply",
    "medium": "manual_review",
    "risky": "reject"
  },

  "medium_risk_handling": {
    "require_approval": true,
    "auto_approve_after_days": null,
    "alert_threshold_pending": 100,
    "batch_pause_on_medium_risk": false
  },

  "cache": {
    "ttl_seconds": 300,
    "last_refresh": "2026-05-14T10:30:00Z"
  }
}
```

**PUT /api/v1/admin/normalization/config**

**Purpose**: Update normalization configuration.

**Request Body** (partial update):
```json
{
  "safety_limits": {
    "max_changes_per_file": 15
  },
  "algorithms_by_modality": {
    "CT": {
      "enabled": ["pixel_spacing", "missing_tags", "photometric", "charset"],
      "disabled": []
    }
  },
  "supplier_rules": {
    "philips": {
      "enabled": true
    }
  }
}
```

**Response (200 OK)**:
```json
{
  "message": "Configuration updated successfully",
  "updated_fields": [
    "safety_limits.max_changes_per_file",
    "algorithms_by_modality.CT",
    "supplier_rules.philips.enabled"
  ],
  "cache_invalidation_ms": 50,
  "effective_immediately": true
}
```

**Error Response** (400 Bad Request):
```json
{
  "error": "Invalid configuration",
  "details": [
    "safety_limits.max_changes_per_file: must be >= 1 and <= 100",
    "supplier_rules.unknown_supplier: siemens_typo is not a registered supplier"
  ]
}
```

---

## 4. Database Schema Extensions

### 4.1 New Table: batch_jobs

```sql
CREATE TABLE batch_jobs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  
  -- User tracking
  user_id VARCHAR(128) NOT NULL,
  username VARCHAR(128),
  ip_address VARCHAR(45),
  
  -- Status tracking
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
    -- queued, processing, completed, paused (for manual review), failed, cancelled
  status_reason TEXT,  -- e.g., "Awaiting medium-risk approval"
  
  -- File counts
  total_files INTEGER NOT NULL,
  processed_files INTEGER DEFAULT 0,
  succeeded_files INTEGER DEFAULT 0,
  failed_files INTEGER DEFAULT 0,
  pending_review_files INTEGER DEFAULT 0,
  
  -- Configuration snapshot
  supplier VARCHAR(64),  -- 'auto', 'siemens', 'ge', 'philips'
  max_changes_per_file INTEGER DEFAULT 10,
  auto_normalize BOOLEAN DEFAULT true,
  
  -- Storage
  temp_file_path VARCHAR(512),  -- /tmp/batch-{batch_id}/
  temp_storage_bytes BIGINT,
  
  -- Timing
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at TIMESTAMP WITH TIME ZONE,
  completed_at TIMESTAMP WITH TIME ZONE,
  processing_duration_ms BIGINT,
  
  -- Summary
  error_summary JSONB,  -- {"total_errors": 2, "by_type": {"...": 1}}
  success_rate_percent NUMERIC(5,2),
  
  -- Indexes
  CONSTRAINT batch_jobs_pkey PRIMARY KEY (id),
  INDEX idx_batch_jobs_user_id (user_id),
  INDEX idx_batch_jobs_status (status),
  INDEX idx_batch_jobs_created_at (created_at DESC),
  INDEX idx_batch_jobs_supplier (supplier)
);
```

### 4.2 New Table: batch_job_files

```sql
CREATE TABLE batch_job_files (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  batch_id UUID NOT NULL REFERENCES batch_jobs(id) ON DELETE CASCADE,
  
  -- File identification
  filename VARCHAR(255) NOT NULL,
  sequence_number INTEGER NOT NULL,  -- Position in batch (for ordering)
  
  -- DICOM UIDs
  sop_instance_uid VARCHAR(128),
  study_instance_uid VARCHAR(128),
  series_instance_uid VARCHAR(128),
  
  -- Metadata
  modality VARCHAR(16),
  manufacturer VARCHAR(128),  -- Detected from (0008,0070)
  file_size_bytes BIGINT,
  
  -- Processing status
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
    -- pending, validated, normalized, stored, failed, pending_review
  status_description TEXT,
  
  -- Normalization details
  normalization_changes JSONB,  -- [{"tag_keyword": "...", "original": "...", "corrected": "...", ...}]
  normalization_summary JSONB,  -- {"safe": 2, "medium": 1, "risky": 0}
  supplier_applied VARCHAR(64),  -- Which supplier normalizer was used
  
  -- Error handling
  error_message TEXT,
  error_details JSONB,
  
  -- Manual review
  requires_review BOOLEAN DEFAULT false,
  review_status VARCHAR(32),  -- pending, approved, rejected
  review_note TEXT,
  
  -- Timing
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  processing_start_ms BIGINT,  -- Relative timestamp
  processing_duration_ms BIGINT,
  
  -- Indexes
  CONSTRAINT batch_job_files_pkey PRIMARY KEY (id),
  CONSTRAINT batch_job_files_batch_fkey FOREIGN KEY (batch_id) REFERENCES batch_jobs(id),
  INDEX idx_batch_job_files_batch_id (batch_id),
  INDEX idx_batch_job_files_status (status),
  INDEX idx_batch_job_files_sop_instance_uid (sop_instance_uid),
  INDEX idx_batch_job_files_sequence (batch_id, sequence_number)
);
```

### 4.3 New Table: normalization_config

```sql
CREATE TABLE normalization_config (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  
  -- Scope
  modality VARCHAR(32) UNIQUE,  -- NULL for default/global config
  
  -- Algorithm toggles
  algorithms_enabled JSONB,  -- {"pixel_spacing": true, "missing_tags": true, ...}
  algorithms_disabled JSONB,  -- {"photometric": false, ...}
  
  -- Safety parameters
  max_changes_per_file INTEGER DEFAULT 10,
  deviation_tolerance_pct NUMERIC(5,2) DEFAULT 20.0,
  charset_confidence_threshold NUMERIC(3,2) DEFAULT 0.85,
  
  -- Performance
  timeout_ms_per_file INTEGER DEFAULT 5000,
  batch_concurrent_workers INTEGER DEFAULT 4,
  batch_max_size INTEGER DEFAULT 1000,
  
  -- Risk tiers
  risk_tiers JSONB,  -- {"safe": "auto", "medium": "manual", "risky": "reject"}
  
  -- Audit
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_by VARCHAR(128),
  change_reason TEXT,
  
  -- Indexes
  CONSTRAINT normalization_config_pkey PRIMARY KEY (id),
  INDEX idx_normalization_config_modality (modality)
);

-- Insert default global config if not exists
INSERT INTO normalization_config (modality, algorithms_enabled, algorithms_disabled)
VALUES (NULL, 
  '{"pixel_spacing": true, "missing_tags": true, "photometric": false, "charset": false}'::jsonb,
  '{"photometric": true, "charset": true}'::jsonb)
ON CONFLICT DO NOTHING;
```

### 4.4 New Table: supplier_rules

```sql
CREATE TABLE supplier_rules (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  
  -- Identification
  supplier_name VARCHAR(64) NOT NULL UNIQUE,  -- siemens, ge, philips
  version VARCHAR(16) NOT NULL,  -- 1.0, 1.1, etc.
  
  -- Metadata
  description TEXT,
  risk_level VARCHAR(32),  -- medium, medium_high, high
  
  -- Rules definition (JSON for extensibility)
  rules JSONB NOT NULL,  -- [{"name": "...", "enabled": true, "risk": "safe", "description": "..."}]
  
  -- Configuration
  enabled BOOLEAN DEFAULT true,
  implementation_class VARCHAR(255),  -- e.g., "app.services.suppliers.siemens.SiemensNormalizer"
  
  -- Audit
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_by VARCHAR(128),
  change_notes TEXT,
  
  -- Indexes
  CONSTRAINT supplier_rules_pkey PRIMARY KEY (id),
  INDEX idx_supplier_rules_name (supplier_name),
  INDEX idx_supplier_rules_enabled (enabled)
);

-- Insert default supplier rules
INSERT INTO supplier_rules (supplier_name, version, description, risk_level, rules, enabled, implementation_class)
VALUES 
  ('siemens', '1.0', 'Siemens DICOM normalization rules', 'medium',
    '[{"name": "extract_pixel_spacing_from_private_tag", "enabled": true, "risk": "safe"}, {"name": "infer_photometric_from_vendor_tag", "enabled": true, "risk": "medium"}]'::jsonb,
    true, 'app.services.suppliers.siemens.SiemensNormalizer'),
  ('ge', '1.0', 'GE DICOM normalization rules', 'medium',
    '[{"name": "infer_photometric_from_jpeg_markers", "enabled": true, "risk": "medium"}]'::jsonb,
    true, 'app.services.suppliers.ge.GENormalizer'),
  ('philips', '1.0', 'Philips DICOM normalization rules', 'medium_high',
    '[{"name": "detect_jpeg_artifacts", "enabled": true, "risk": "medium"}]'::jsonb,
    false, 'app.services.suppliers.philips.PhilipsNormalizer');
```

### 4.5 New Table: normalization_reviews

```sql
CREATE TABLE normalization_reviews (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  
  -- Reference
  batch_job_file_id UUID NOT NULL REFERENCES batch_job_files(id) ON DELETE CASCADE,
  batch_id UUID NOT NULL REFERENCES batch_jobs(id) ON DELETE CASCADE,
  
  -- Change details
  tag_keyword VARCHAR(64),
  original_value TEXT,
  corrected_value TEXT,
  rationale TEXT,
  risk_level VARCHAR(32),  -- medium, risky
  
  -- Review decision
  reviewer_id VARCHAR(128),
  reviewer_username VARCHAR(128),
  decision VARCHAR(32) NOT NULL,  -- pending, approved, rejected
  decision_timestamp TIMESTAMP WITH TIME ZONE,
  review_comment TEXT,
  
  -- Audit
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  
  -- Indexes
  CONSTRAINT normalization_reviews_pkey PRIMARY KEY (id),
  INDEX idx_normalization_reviews_batch_file (batch_job_file_id),
  INDEX idx_normalization_reviews_decision (decision),
  INDEX idx_normalization_reviews_reviewer (reviewer_id)
);
```

### 4.6 Extensions to Existing Tables

**audit_logs** (extend with new columns):
```sql
ALTER TABLE audit_logs ADD COLUMN batch_id UUID REFERENCES batch_jobs(id);
ALTER TABLE audit_logs ADD COLUMN supplier VARCHAR(64);
ALTER TABLE audit_logs ADD COLUMN batch_sequence_number INTEGER;

-- Add indexes for batch queries
CREATE INDEX idx_audit_logs_batch_id ON audit_logs(batch_id);
CREATE INDEX idx_audit_logs_supplier ON audit_logs(supplier);
```

**dicom_instances** (extend with normalization tracking):
```sql
ALTER TABLE dicom_instances ADD COLUMN normalized_version INTEGER DEFAULT 0;
ALTER TABLE dicom_instances ADD COLUMN batch_id UUID REFERENCES batch_jobs(id);
ALTER TABLE dicom_instances ADD COLUMN normalization_changes_summary JSONB;

CREATE INDEX idx_dicom_instances_batch_id ON dicom_instances(batch_id);
```

---

## 5. Supplier Rules Architecture

### 5.1 Base Plugin Interface

**File**: `backend/app/services/suppliers/base.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
import pydicom
from pydicom.dataset import Dataset

@dataclass
class SupplierChangeRecord:
    """Record of a single change applied by supplier rule."""
    tag_keyword: str
    original_value: str | None
    corrected_value: str
    rationale: str
    risk_level: str  # "safe", "medium", "risky"
    rule_name: str  # e.g., "extract_pixel_spacing_from_private_tag"

class SupplierNormalizer(ABC):
    """Base class for supplier-specific DICOM normalizers."""
    
    @property
    @abstractmethod
    def supplier_name(self) -> str:
        """Return supplier name (e.g., 'siemens')."""
        pass
    
    @property
    @abstractmethod
    def version(self) -> str:
        """Return rule version (e.g., '1.0')."""
        pass
    
    @abstractmethod
    def detect(self, ds: Dataset) -> bool:
        """Detect if DICOM is from this supplier.
        
        Args:
            ds: pydicom Dataset
            
        Returns:
            True if this normalizer should be applied
        """
        pass
    
    @abstractmethod
    async def normalize(
        self,
        ds: Dataset,
        config: dict | None = None
    ) -> list[SupplierChangeRecord]:
        """Apply supplier-specific normalization rules.
        
        Args:
            ds: pydicom Dataset to normalize (will be modified in-place)
            config: Configuration dict (e.g., {"enabled_rules": ["rule1", "rule2"]})
            
        Returns:
            List of SupplierChangeRecord objects for audit trail
            
        Raises:
            Exception: If normalization fails (should log and continue)
        """
        pass
```

### 5.2 Supplier Registry

**File**: `backend/app/services/supplier_registry.py`

```python
class SupplierRegistry:
    """Registry for supplier-specific normalizers.
    
    Pattern: Plugin architecture with auto-detection.
    """
    
    _registry: dict[str, SupplierNormalizer] = {}
    _enabled_suppliers: set[str] = {"siemens", "ge"}  # From config
    
    @classmethod
    def register(cls, supplier_name: str, normalizer: SupplierNormalizer):
        """Register a supplier normalizer.
        
        Args:
            supplier_name: e.g., 'siemens'
            normalizer: Instance of SupplierNormalizer subclass
        """
        cls._registry[supplier_name.lower()] = normalizer
    
    @classmethod
    def auto_detect(cls, ds: Dataset) -> SupplierNormalizer | None:
        """Auto-detect supplier from DICOM header.
        
        Strategy:
        1. Check Manufacturer tag (0008,0070)
        2. Iterate enabled suppliers in order, call detect()
        3. Return first match or None
        
        Args:
            ds: pydicom Dataset
            
        Returns:
            SupplierNormalizer instance if detected, None otherwise
        """
        manufacturer = getattr(ds, "Manufacturer", "").strip().lower()
        
        # Quick check by manufacturer name
        for supplier_name, normalizer in cls._registry.items():
            if supplier_name in cls._enabled_suppliers:
                if normalizer.detect(ds):
                    return normalizer
        
        return None
    
    @classmethod
    def get(cls, supplier_name: str) -> SupplierNormalizer | None:
        """Get registered normalizer by name.
        
        Args:
            supplier_name: e.g., 'siemens'
            
        Returns:
            SupplierNormalizer instance or None if not registered
        """
        return cls._registry.get(supplier_name.lower())
    
    @classmethod
    def list_available(cls) -> dict[str, SupplierNormalizer]:
        """List all registered normalizers."""
        return dict(cls._registry)
    
    @classmethod
    def enable_supplier(cls, supplier_name: str):
        """Enable supplier rules."""
        cls._enabled_suppliers.add(supplier_name.lower())
    
    @classmethod
    def disable_supplier(cls, supplier_name: str):
        """Disable supplier rules."""
        cls._enabled_suppliers.discard(supplier_name.lower())
```

### 5.3 Siemens Normalizer Implementation

**File**: `backend/app/services/suppliers/siemens.py`

```python
import pydicom
from pydicom.dataset import Dataset
from app.services.suppliers.base import SupplierNormalizer, SupplierChangeRecord

class SiemensNormalizer(SupplierNormalizer):
    """Siemens DICOM normalization rules.
    
    Rules:
    1. Extract PixelSpacing from Siemens private tag (0019,1008)
       - Risk: SAFE
    2. Infer PhotometricInterpretation from vendor tag (0019,1010)
       - Risk: MEDIUM
    """
    
    @property
    def supplier_name(self) -> str:
        return "siemens"
    
    @property
    def version(self) -> str:
        return "1.0"
    
    def detect(self, ds: Dataset) -> bool:
        """Detect Siemens DICOM.
        
        Check:
        - Manufacturer contains 'SIEMENS'
        - Private tags in (0019, xxxx) range exist
        """
        manufacturer = getattr(ds, "Manufacturer", "").upper()
        if "SIEMENS" in manufacturer:
            return True
        
        # Fallback: check for Siemens-specific private tags
        try:
            return (0x0019, 0x1008) in ds or (0x0019, 0x1010) in ds
        except:
            return False
    
    async def normalize(
        self,
        ds: Dataset,
        config: dict | None = None
    ) -> list[SupplierChangeRecord]:
        """Apply Siemens-specific normalization."""
        changes = []
        config = config or {}
        
        # Rule 1: Extract PixelSpacing from (0019,1008)
        if not hasattr(ds, "PixelSpacing") and (0x0019, 0x1008) in ds:
            try:
                spacing_bytes = ds[0x0019, 0x1008].value
                spacing = self._parse_pixel_spacing_from_bytes(spacing_bytes)
                if spacing:
                    ds.PixelSpacing = spacing
                    changes.append(SupplierChangeRecord(
                        tag_keyword="PixelSpacing",
                        original_value=None,
                        corrected_value=str(spacing),
                        rationale="Extracted from Siemens private tag (0019,1008)",
                        risk_level="safe",
                        rule_name="extract_pixel_spacing_from_private_tag"
                    ))
            except Exception as e:
                # Log but don't fail
                pass
        
        # Rule 2: Infer PhotometricInterpretation from (0019,1010)
        if not hasattr(ds, "PhotometricInterpretation") and (0x0019, 0x1010) in ds:
            try:
                vendor_value = ds[0x0019, 0x1010].value
                photometric = self._infer_photometric_from_vendor_tag(vendor_value)
                if photometric:
                    ds.PhotometricInterpretation = photometric
                    changes.append(SupplierChangeRecord(
                        tag_keyword="PhotometricInterpretation",
                        original_value=None,
                        corrected_value=photometric,
                        rationale="Inferred from Siemens vendor tag (0019,1010)",
                        risk_level="medium",
                        rule_name="infer_photometric_from_vendor_tag"
                    ))
            except Exception as e:
                pass
        
        return changes
    
    def _parse_pixel_spacing_from_bytes(self, data: bytes) -> list[float] | None:
        """Parse pixel spacing from Siemens proprietary format."""
        # Simplified: Siemens private tags may contain raw float values
        try:
            if len(data) >= 16:  # Two 8-byte doubles
                import struct
                x, y = struct.unpack('<dd', data[:16])
                return [x, y]
        except:
            pass
        return None
    
    def _infer_photometric_from_vendor_tag(self, value: str) -> str | None:
        """Infer PhotometricInterpretation from vendor tag value."""
        if "MONOCHROME" in str(value).upper():
            return "MONOCHROME2"
        if "RGB" in str(value).upper():
            return "RGB"
        return None
```

### 5.4 GE Normalizer Implementation

**File**: `backend/app/services/suppliers/ge.py`

```python
class GENormalizer(SupplierNormalizer):
    """GE DICOM normalization rules.
    
    Rules:
    1. Infer PhotometricInterpretation from JPEG markers
       - Risk: MEDIUM
    2. Correct SamplesPerPixel for grayscale JPEG
       - Risk: SAFE
    """
    
    @property
    def supplier_name(self) -> str:
        return "ge"
    
    @property
    def version(self) -> str:
        return "1.0"
    
    def detect(self, ds: Dataset) -> bool:
        """Detect GE DICOM."""
        manufacturer = getattr(ds, "Manufacturer", "").upper()
        return "GE" in manufacturer or "GENERAL ELECTRIC" in manufacturer
    
    async def normalize(
        self,
        ds: Dataset,
        config: dict | None = None
    ) -> list[SupplierChangeRecord]:
        """Apply GE-specific normalization."""
        changes = []
        
        # Rule 1: Infer PhotometricInterpretation
        if not hasattr(ds, "PhotometricInterpretation"):
            photometric = self._infer_photometric_from_ge_pattern(ds)
            if photometric:
                ds.PhotometricInterpretation = photometric
                changes.append(SupplierChangeRecord(
                    tag_keyword="PhotometricInterpretation",
                    original_value=None,
                    corrected_value=photometric,
                    rationale="Inferred from GE JPEG encoding pattern",
                    risk_level="medium",
                    rule_name="infer_photometric_from_jpeg_markers"
                ))
        
        # Rule 2: Correct SamplesPerPixel
        if hasattr(ds, "TransferSyntaxUID") and "JPEG" in str(ds.TransferSyntaxUID):
            if getattr(ds, "SamplesPerPixel", 1) == 3 and getattr(ds, "PhotometricInterpretation", "") == "MONOCHROME2":
                ds.SamplesPerPixel = 1
                changes.append(SupplierChangeRecord(
                    tag_keyword="SamplesPerPixel",
                    original_value="3",
                    corrected_value="1",
                    rationale="Grayscale JPEG should have SamplesPerPixel=1",
                    risk_level="safe",
                    rule_name="correct_samples_per_pixel_grayscale_jpeg"
                ))
        
        return changes
    
    def _infer_photometric_from_ge_pattern(self, ds: Dataset) -> str | None:
        """Infer photometric interpretation from GE-specific patterns."""
        # Simplified: check transfer syntax and pixel attributes
        try:
            if hasattr(ds, "BitsAllocated") and ds.BitsAllocated == 8:
                return "MONOCHROME2"
            if hasattr(ds, "BitsAllocated") and ds.BitsAllocated == 16:
                return "MONOCHROME2"
        except:
            pass
        return None
```

### 5.5 Philips Normalizer Implementation

**File**: `backend/app/services/suppliers/philips.py`

```python
class PhilipsNormalizer(SupplierNormalizer):
    """Philips DICOM normalization rules.
    
    Rules:
    1. Detect and normalize JPEG encoding artifacts
       - Risk: MEDIUM_HIGH
    
    Note: Disabled by default in Phase 4 (requires validation with real Philips samples).
    """
    
    @property
    def supplier_name(self) -> str:
        return "philips"
    
    @property
    def version(self) -> str:
        return "1.0"
    
    def detect(self, ds: Dataset) -> bool:
        """Detect Philips DICOM."""
        manufacturer = getattr(ds, "Manufacturer", "").upper()
        return "PHILIPS" in manufacturer
    
    async def normalize(
        self,
        ds: Dataset,
        config: dict | None = None
    ) -> list[SupplierChangeRecord]:
        """Apply Philips-specific normalization."""
        changes = []
        
        # Placeholder: Philips rules require real-world validation
        # Rule: Detect JPEG compression artifacts and log for manual review
        
        return changes
```

---

## 6. Batch Processing Workflow (Celery Tasks)

### 6.1 Task Chain Architecture

**File**: `backend/app/services/batch_normalizer.py`

```python
from celery import Celery, chord, group
from app.services.ai_worker import celery_app

# Task sequence:
# 1. batch_upload_task (single) → Enqueue parallel tasks → 
# 2. [chord] validate + normalize (parallel per file) → 
# 3. finalize_batch_task (single)

@celery_app.task(bind=True, max_retries=3, task_acks_late=True)
def batch_upload_task(self, batch_id: str):
    """
    Phase 1: Extract ZIP, validate DICOM magic bytes, create file records.
    """
    # 1. Load batch_jobs record
    # 2. Extract ZIP to /tmp/batch-{batch_id}/
    # 3. Validate file count < MAX_FILES
    # 4. Validate DICOM magic bytes (first 4 bytes or offset 128)
    # 5. Create batch_job_files records
    # 6. Update batch_jobs: status='processing', total_files=N
    # 7. Enqueue parallel tasks via chord()

@celery_app.task(bind=True, max_retries=1)
def validate_file_task(self, batch_id: str, file_sequence: int, file_path: str):
    """
    Phase 2 (per-file, parallel): Validate DICOM structure.
    """
    # 1. Load DICOM from file_path
    # 2. DicomValidator.validate()
    # 3. Update batch_job_files: status='validated'
    # 4. Return file_sequence for chord callback

@celery_app.task(bind=True, max_retries=1)
def normalize_file_task(self, batch_id: str, file_sequence: int, file_path: str, config: dict):
    """
    Phase 3 (per-file, parallel): Apply normalization (supplier + Phase 3 core).
    """
    # 1. Load DICOM
    # 2. SupplierRegistry.auto_detect() → Apply supplier normalizer
    # 3. DicomNormalizer.normalize() → Phase 3 core rules
    # 4. Check medium-risk items:
    #    ├─ If yes & auto_approve_medium=false:
    #    │  └─ Create normalization_reviews row (decision='pending')
    #    │  └─ Update batch_job_files: status='pending_review'
    #    │  └─ Return SKIP_STORE signal
    #    └─ If no:
    #       └─ Update batch_job_files: status='normalized'
    # 5. Return file_sequence + changes summary

@celery_app.task(bind=True, max_retries=2)
def store_file_task(self, batch_id: str, file_sequence: int, file_path: str):
    """
    Phase 4 (per-file, parallel): Upload to Orthanc.
    """
    # 1. Load normalized DICOM
    # 2. POST to Orthanc /dicomweb/studies
    # 3. Update batch_job_files: status='stored', sop_instance_uid=...
    # 4. Update dicom_instances: batch_id=..., normalized_version=1
    # 5. Return file_sequence

@celery_app.task(bind=True)
def audit_file_task(self, batch_id: str, file_sequence: int, changes_summary: dict):
    """
    Phase 5 (per-file, parallel): Log normalization changes.
    """
    # 1. For each change in changes_summary:
    #    └─ Insert audit_logs row (action='DICOM_NORMALIZED_*', batch_id=..., supplier=...)
    # 2. Update batch_job_files: audit logged
    # 3. Return file_sequence

@celery_app.task(bind=True)
def finalize_batch_task(self, results: list, batch_id: str):
    """
    Phase 6 (final): Update batch status, cleanup temp files.
    """
    # 1. Count succeeded/failed/pending from results
    # 2. Calculate success_rate_percent
    # 3. Generate final report JSON
    # 4. Cleanup /tmp/batch-{batch_id}/
    # 5. Update batch_jobs: status='completed', completed_at=now()
    # 6. Notify user (optional email/webhook)
```

### 6.2 Task Execution Flow

```python
def enqueue_batch_normalization(batch_id: str):
    """Enqueue batch using chord pattern (fan-out + join)."""
    
    # Chord: Parallel processing with final callback
    callback = finalize_batch_task.s(batch_id)
    
    parallel_tasks = chord([
        validate_file_task.s(batch_id, seq, path) 
        for seq, path in enumerate(files)
    ], callback)
    
    # Execution:
    # 1. All validate_file_task run in parallel
    # 2. Once all complete, finalize_batch_task runs
    # 3. No re-queuing if one file fails (skipped in callback)
```

### 6.3 Error Handling & Retry Strategy

```python
# Per-task retry policy:

validate_file_task:
  max_retries = 1  # Validation errors are deterministic
  retry_on = [DicomValidationError]  # Not transient, so no retry
  
normalize_file_task:
  max_retries = 1  # Normalization errors are deterministic
  time_limit = 5000  # 5 seconds per file (from config)
  
store_file_task:
  max_retries = 2  # Orthanc failures may be transient
  retry_on = [ConnectionError, TimeoutError]
  
# Batch-level error handling:
# - Failed files skipped (status='failed', error_message set)
# - Partial batch success OK (e.g., 95/100 succeeded)
# - No rollback (immutable audit trail)
```

---

## 7. Admin Dashboard Layout

### 7.1 Page 1: Normalization Overview (Main Dashboard)

**Route**: `/admin/normalization`

**Layout**:
```
┌────────────────────────────────────────────────────────────┐
│ DICOM Normalization Status (Last 24 Hours)                │
├────────────────────────────────────────────────────────────┤
│                                                             │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│ │ Total Files  │ │  Normalized  │ │ Success Rate │        │
│ │   1,247      │ │   1,189      │ │    95.3%     │        │
│ │              │ │  (95.3%)     │ │              │        │
│ └──────────────┘ └──────────────┘ └──────────────┘        │
│                                                             │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│ │ Avg Time     │ │ Errors       │ │ Pending      │        │
│ │  42ms/file   │ │  25 (2%)     │ │  Review: 12  │        │
│ │ P95: 150ms   │ │              │ │              │        │
│ └──────────────┘ └──────────────┘ └──────────────┘        │
│                                                             │
├────────────────────────────────────────────────────────────┤
│ Algorithm Effectiveness (Last 24h)                         │
│                                                             │
│ Pixel Spacing:    [████████░░] 487 files (39%)            │
│ Missing Tags:     [██████░░░░] 203 files (16%)            │
│ Photometric:      [███░░░░░░░] 89 files (7%)              │
│ Charset:          [██░░░░░░░░] 34 files (3%)              │
│                                                             │
├────────────────────────────────────────────────────────────┤
│ Supplier Distribution                                       │
│                                                             │
│ Siemens:   ████████░░ 450 files                            │
│ GE:        ██████░░░░ 300 files                            │
│ Philips:   ████░░░░░░ 180 files                            │
│ Unknown:   ██░░░░░░░░ 120 files                            │
│                                                             │
├────────────────────────────────────────────────────────────┤
│ Pending Medium-Risk Items: 156                             │
│ • PhotometricInterpretation: 98                            │
│ • Charset Conversion: 58                                   │
│ [Review Items] [Bulk Approve]                              │
│                                                             │
├────────────────────────────────────────────────────────────┤
│ Active Batch Jobs: 2                                        │
│ • Batch #abc123: 3,500/5,000 files (70%) - Started 10m ago│
│ • Batch #def456: 127/150 files (85%) - Started 2m ago     │
│ [Manage Batches]                                            │
│                                                             │
├────────────────────────────────────────────────────────────┤
│ Performance Trend (Last 7 days)                            │
│ [Line chart showing normalization throughput over time]    │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

**Component Data Sources**:
```sql
-- Total files & success rate (last 24h)
SELECT COUNT(*) as total, 
       SUM(CASE WHEN status='stored' THEN 1 ELSE 0 END) as succeeded
FROM batch_job_files
WHERE created_at > NOW() - INTERVAL '24 hours';

-- Algorithm effectiveness
SELECT category, COUNT(*) as count
FROM audit_logs
WHERE action LIKE 'DICOM_NORMALIZED_%' AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY category;

-- Supplier distribution
SELECT supplier, COUNT(*) as count
FROM batch_job_files
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY supplier;

-- Pending medium-risk
SELECT tag_keyword, COUNT(*) as count
FROM normalization_reviews
WHERE decision='pending'
GROUP BY tag_keyword;
```

### 7.2 Page 2: Batch Management

**Route**: `/admin/normalization/batch`

**List View**:
```
┌────────────────────────────────────────────────────────────┐
│ Batch Processing Queue                 [Upload New Batch]  │
├────────────────────────────────────────────────────────────┤
│ Batch ID     Status     Progress    Files    Supplier Est.  │
├────────────────────────────────────────────────────────────┤
│ abc12345     processing 70%         3.5K/5K  siemens 4m    │
│ def67890     completed  100%        150/150  auto    -     │
│ ghi11111     processing 45%         225/500  mixed   8m    │
│ jkl22222     failed     30%         150/500  ge      -     │
│ [Show details] [Retry] [Cancel]                            │
│                                                             │
│ Filters: [Status ▼] [Supplier ▼] [Date Range ▼]           │
│ Sort: [Newest ▼]    Page 1 of 5                            │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

**Detail View** (Drill-down):
```
┌────────────────────────────────────────────────────────────┐
│ Batch #abc12345 — Details                                  │
├────────────────────────────────────────────────────────────┤
│ Status: PROCESSING (70% complete)                          │
│ Submitted: 2026-05-14 10:30:45 by dr.kim                  │
│ Estimated: 4 minutes remaining                              │
│ Supplier: siemens (auto-detected)                          │
│                                                             │
│ Statistics:                                                 │
│ • Total Files: 5,000                                        │
│ • Processed: 3,500                                          │
│ • Succeeded: 3,450                                          │
│ • Failed: 50                                                │
│ • Pending Review: 12                                        │
│                                                             │
│ Normalization Summary:                                      │
│ • Pixel Spacing fixed: 1,200                               │
│ • Missing Tags added: 450                                  │
│ • Photometric inferred: 120                                │
│ • Charset converted: 45                                    │
│                                                             │
│ Per-File Status:                                            │
│ ┌─────────────────────────────────────────────────────┐    │
│ │ Seq  Filename      Status   Modality Changes Err    │    │
│ ├─────────────────────────────────────────────────────┤    │
│ │ 1    CT_0001.dcm   stored   CT       2      -      │    │
│ │ 2    CT_0002.dcm   stored   CT       1      -      │    │
│ │ 3    CT_0003.dcm   pending  CT       1      -      │    │
│ │ 4    CT_0004.dcm   failed   CT       -      FailPh │    │
│ │ ... (50 more files)                                 │    │
│ │ [Load More] [Download CSV]                          │    │
│ └─────────────────────────────────────────────────────┘    │
│                                                             │
│ Actions:                                                    │
│ [Retry Failed] [Download Report] [Approve Pending] [Done]  │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

### 7.3 Page 3: Configuration Panel

**Route**: `/admin/normalization/config`

**Layout**:
```
┌────────────────────────────────────────────────────────────┐
│ Normalization Configuration                 [Save Changes] │
├────────────────────────────────────────────────────────────┤
│                                                             │
│ ▼ Safety Limits                                             │
│   Max Changes per File:         [10    ]  (1-100)          │
│   Max Files per Batch:          [1000  ]  (10-10K)         │
│   Batch Timeout (ms):           [5000  ]                   │
│   Pixel Spacing Tolerance (%):  [20.0  ]  (±% deviation)   │
│   Charset Confidence Threshold: [0.85  ]  (0.0-1.0)        │
│                                                             │
│ ▼ Algorithms by Modality                                    │
│   Modality: [All ▼]                                         │
│   ☑ Pixel Spacing                                          │
│   ☑ Missing Tags                                           │
│   ☐ Photometric Interpretation                            │
│   ☐ Charset Conversion                                     │
│                                                             │
│ ▼ Supplier Rules                                            │
│   ☑ Siemens   [v1.0] (Last modified: 2026-05-13)          │
│       ☑ Extract PixelSpacing from (0019,1008)    [Safe]   │
│       ☑ Infer Photometric from (0019,1010)    [Medium]    │
│   ☑ GE        [v1.0] (Last modified: 2026-05-13)          │
│       ☑ Infer Photometric from JPEG markers  [Medium]    │
│       ☑ Fix SamplesPerPixel for grayscale      [Safe]    │
│   ☐ Philips   [v1.0] (Last modified: 2026-05-13)          │
│       ☑ Detect JPEG artifacts              [Med-High]    │
│                                                             │
│ ▼ Risk Handling                                             │
│   Safe Changes:        [Auto-apply ▼]                      │
│   Medium-Risk Changes: [Manual Review ▼]                   │
│   Risky Changes:       [Reject ▼]                          │
│                                                             │
│ ▼ Medium-Risk Management                                    │
│   Require Manual Approval:          [ON]                   │
│   Alert if Pending Count > :        [100]                  │
│   Auto-approve after (days):        [--inactive--]         │
│                                                             │
│ [Reset to Defaults] [Save Changes]                         │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

### 7.4 Page 4: Audit History & Manual Review

**Route**: `/admin/normalization/audit` & `/admin/normalization/review`

**Audit History**:
```
┌────────────────────────────────────────────────────────────┐
│ Normalization Audit Trail                                  │
├────────────────────────────────────────────────────────────┤
│ Filters: [Supplier ▼] [Modality ▼] [Action ▼] [Date ▼]    │
│                                                             │
│ Date       Supplier  Modality Files Action    Success User  │
├────────────────────────────────────────────────────────────┤
│ 2026-05-14 Siemens   CT       1,200 Batch     98.5%  admin │
│ 2026-05-14 GE        MR       450    Batch     96.2%  dr.kim│
│ 2026-05-14 Philips   US       320    Batch     94.1%  admin │
│ 2026-05-13 Siemens   CT       800    Upload    99.0%  system│
│ ... (more entries)                                          │
│ [Export as CSV] [Export as PDF]                             │
│                                                             │
│ Page 1 of 45                                                │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

**Manual Review Queue**:
```
┌────────────────────────────────────────────────────────────┐
│ Pending Medium-Risk Review (12 items)                      │
├────────────────────────────────────────────────────────────┤
│                                                             │
│ Batch #abc12345 — PhotometricInterpretation (Siemens)     │
│                                                             │
│ File: CT_0050.dcm                                          │
│ Original:  [JPEG] → Inferred: MONOCHROME2 (confidence: 92%)│
│ Rationale: "Extracted from Siemens vendor tag (0019,1010)"│
│                                                             │
│ [Approve] [Reject] [Comments: _____________________]       │
│                                                             │
├────────────────────────────────────────────────────────────┤
│                                                             │
│ Batch #ghi11111 — Charset Conversion (GE)                 │
│                                                             │
│ File: MR_0012.dcm                                          │
│ Original:  ISO_IR 100 (Latin-1) → Convert to UTF-8         │
│ Affected:  PatientName, StudyDescription                   │
│                                                             │
│ [Approve] [Reject] [Approve All Similar]                   │
│                                                             │
│ ... (10 more items)                                         │
│                                                             │
│ Actions: [Approve Selected] [Reject Selected] [Bulk Actions]
│                                                             │
└────────────────────────────────────────────────────────────┘
```

---

## 8. Configuration System

### 8.1 Environment Variables (New in Phase 4)

```bash
# Safety Limits
BATCH_MAX_FILES=1000
BATCH_TIMEOUT_MS=5000
BATCH_MAX_CHANGES=10
BATCH_MAX_SIZE_MB=100

# Performance
BATCH_CONCURRENT_WORKERS=4
BATCH_WORKER_POOL_SIZE=4

# Supplier Rules
SUPPLIER_AUTO_DETECT=true
SUPPLIER_RULES_PATH=/etc/openpacs/suppliers/

# Temporary Storage
BATCH_TEMP_STORAGE_PATH=/tmp/batch-jobs/
BATCH_TEMP_CLEANUP_INTERVAL_HOURS=24
BATCH_MAX_TEMP_SIZE_MB=5000

# Configuration Cache
CONFIG_CACHE_TTL_SECONDS=300
CONFIG_CACHE_BACKEND=redis  # redis or memory

# Feature Flags
FEATURE_BATCH_NORMALIZATION=true
FEATURE_SUPPLIER_RULES=true
FEATURE_MEDIUM_RISK_REVIEW=true
FEATURE_WEBSOCKET_PROGRESS=false  # Phase 5
```

### 8.2 In-Database Configuration (normalization_config table)

```python
# Load from database
class NormalizationConfig(BaseModel):
    """Configuration for DICOM normalization."""
    
    # Safety
    max_changes_per_file: int = 10
    max_files_per_batch: int = 1000
    batch_timeout_ms: int = 5000
    deviation_tolerance_pct: float = 20.0
    charset_confidence_threshold: float = 0.85
    
    # Performance
    timeout_ms_per_file: int = 5000
    batch_concurrent_workers: int = 4
    batch_max_size: int = 10000
    
    # Algorithms (per modality)
    algorithms_enabled: dict[str, list[str]] = {
        "CT": ["pixel_spacing", "missing_tags", "photometric", "charset"],
        "MR": ["pixel_spacing", "missing_tags", "charset"],
        "US": ["pixel_spacing", "missing_tags"],
        "_default": ["pixel_spacing", "missing_tags"],
    }
    
    # Risk tiers
    risk_tiers: dict[str, str] = {
        "safe": "auto_apply",
        "medium": "manual_review",
        "risky": "reject",
    }
    
    # Supplier rules
    supplier_rules_enabled: dict[str, bool] = {
        "siemens": True,
        "ge": True,
        "philips": False,
    }
    
    # Medium-risk handling
    auto_approve_medium_risk: bool = False
    medium_risk_alert_threshold: int = 100
    batch_pause_on_medium_risk: bool = False
```

### 8.3 Configuration Loading & Caching

```python
# backend/app/services/config_service.py

class ConfigService:
    """Load and cache normalization configuration."""
    
    _cache: NormalizationConfig | None = None
    _cache_ttl: int = 300  # 5 minutes
    _cache_time: float = 0
    
    @classmethod
    async def get_config(cls) -> NormalizationConfig:
        """Get configuration (with caching)."""
        now = time.time()
        if cls._cache and (now - cls._cache_time) < cls._cache_ttl:
            return cls._cache
        
        # Load from database
        config = await cls._load_from_db()
        cls._cache = config
        cls._cache_time = now
        return config
    
    @classmethod
    async def _load_from_db(cls) -> NormalizationConfig:
        """Load configuration from normalization_config table."""
        async with get_db() as db:
            # Query default global config
            result = await db.execute(
                select(NormalizationConfigModel).where(
                    NormalizationConfigModel.modality == None
                )
            )
            config_row = result.scalar_one_or_none()
        
        if not config_row:
            return NormalizationConfig()  # Use defaults
        
        return NormalizationConfig(
            algorithms_enabled=config_row.algorithms_enabled,
            risk_tiers=config_row.risk_tiers,
            **config_row.dict()
        )
    
    @classmethod
    async def invalidate_cache(cls):
        """Invalidate cache (called after config update)."""
        cls._cache = None
        cls._cache_time = 0
```

---

## 9. Error Handling & Validation

### 9.1 New Exception Classes

```python
# backend/app/core/exceptions.py

class BatchSizeExceededError(Exception):
    """Batch contains too many files."""
    pass

class BatchTimeoutError(Exception):
    """Batch processing exceeded timeout."""
    pass

class SupplierDetectionError(Exception):
    """Could not identify DICOM supplier."""
    pass

class BatchStorageError(Exception):
    """Failed to store batch results."""
    pass

class InvalidZipError(Exception):
    """ZIP file is corrupt or invalid."""
    pass

class DicomMagicBytesError(Exception):
    """File does not have valid DICOM magic bytes."""
    pass

class MediumRiskPendingError(Exception):
    """Batch paused due to medium-risk items (requires approval)."""
    pass

class SupplierRuleExecutionError(Exception):
    """Supplier rule failed during execution."""
    pass
```

### 9.2 Validation Logic

```python
def validate_batch_upload(
    files: list[UploadFile],
    config: NormalizationConfig
) -> ValidationResult:
    """Validate batch before processing.
    
    Checks:
    1. File count <= MAX_FILES
    2. Total size <= MAX_SIZE_MB
    3. ZIP integrity (if present)
    4. DICOM magic bytes for each file
    """
    
    # 1. File count
    if len(files) > config.max_files_per_batch:
        raise BatchSizeExceededError(
            f"Batch size {len(files)} exceeds max {config.max_files_per_batch}"
        )
    
    # 2. Total size
    total_size = sum(file.size for file in files)
    if total_size > config.batch_max_size_mb * 1024 * 1024:
        raise UploadError(f"Batch size {total_size} bytes exceeds max")
    
    # 3. ZIP integrity (if applicable)
    if any(f.filename.endswith('.zip') for f in files):
        try:
            # Validate ZIP structure
            zipfile.ZipFile(files[0].file).testzip()
        except zipfile.BadZipFile as e:
            raise InvalidZipError(f"Invalid ZIP file: {e}")
    
    # 4. DICOM magic bytes
    for file in files:
        if not _has_dicom_magic_bytes(file.file):
            raise DicomMagicBytesError(
                f"File {file.filename} is not a valid DICOM file"
            )

def _has_dicom_magic_bytes(file_data: bytes) -> bool:
    """Check for DICOM magic bytes (preamble + 'DICM' or implicit VR marker)."""
    if len(file_data) < 132:
        return False
    
    # Check implicit VR: (0002,0000) at offset 128
    if file_data[128:132] == b'DICM':
        return True
    
    # Check for (0x02,0x00,0x00,0x00) at start (implicit VR)
    # This is a simplified check; real implementation would parse DICOM header
    return file_data[:2] == b'\x02\x00' or file_data[:4] == b'\x02\x00\x00\x00'
```

---

## 10. Testing Strategy (Design Perspective)

### 10.1 Unit Tests (50-60 tests)

**Batch Operations** (10 tests):
- `test_batch_job_creation_with_valid_zip`
- `test_batch_upload_exceeds_max_files_raises_error`
- `test_batch_upload_invalid_zip_raises_error`
- `test_batch_progress_calculation_accuracy`
- `test_batch_report_json_generation`
- `test_batch_report_csv_export`
- `test_batch_status_transitions_valid`
- `test_batch_error_summary_aggregation`
- `test_batch_cleanup_removes_temp_files`
- `test_batch_multipart_vs_zip_handling`

**Supplier Registry** (15 tests):
- `test_siemens_detection_by_manufacturer_tag`
- `test_siemens_pixel_spacing_extraction_from_private_tag`
- `test_siemens_photometric_inference_accuracy`
- `test_ge_detection_by_manufacturer`
- `test_ge_photometric_inference_from_jpeg_pattern`
- `test_ge_samples_per_pixel_correction`
- `test_philips_detection_by_manufacturer`
- `test_supplier_registry_auto_detect_fallback`
- `test_supplier_registry_get_by_name`
- `test_supplier_rule_enable_disable`
- `test_supplier_changelog_tracking`
- `test_supplier_pixel_spacing_tolerance_check` (±5% acceptance)
- `test_supplier_rule_execution_error_handling`
- `test_supplier_rule_version_compatibility`
- `test_multiple_supplier_detection_priority_order`

**Configuration** (12 tests):
- `test_config_load_from_database`
- `test_config_cache_ttl_expiration`
- `test_config_cache_invalidation_on_update`
- `test_config_modality_specific_algorithms`
- `test_config_validation_max_changes_bounds`
- `test_config_validation_invalid_supplier_name`
- `test_config_risk_tier_mapping`
- `test_config_supplier_enable_disable_toggle`
- `test_config_medium_risk_alert_threshold`
- `test_config_partial_update_merge`
- `test_config_environment_variable_override`
- `test_config_default_values_applied`

**Charset Detection** (6 tests):
- `test_latin1_detection_accuracy_on_korean_names`
- `test_utf8_validation_no_false_positives`
- `test_charset_conversion_latin1_to_utf8`
- `test_charset_confidence_threshold_check`
- `test_mixed_charset_dataset_handling`
- `test_charset_specific_character_set_update`

**Validation** (10 tests):
- `test_validate_batch_upload_file_count_limit`
- `test_validate_batch_upload_total_size_limit`
- `test_validate_batch_upload_zip_integrity`
- `test_validate_dicom_magic_bytes_implicit_vr`
- `test_validate_dicom_magic_bytes_explicit_vr`
- `test_validate_non_dicom_file_rejection`
- `test_validate_corrupt_dicom_handling`
- `test_validate_max_changes_per_file_enforcement`
- `test_validate_timeout_per_file_enforcement`
- `test_validate_medium_risk_detection`

### 10.2 Integration Tests (20-25 tests)

**End-to-End Batch Processing** (8 tests):
- `test_batch_upload_to_completion_full_flow`
- `test_batch_with_mixed_valid_invalid_files`
- `test_batch_partial_failure_continues_processing`
- `test_batch_retry_on_worker_crash`
- `test_batch_timeout_per_file_skips_slow_files`
- `test_batch_storage_to_orthanc_integration`
- `test_batch_audit_logging_covers_all_changes`
- `test_batch_webhook_notification_on_completion`

**Supplier Rules in Context** (6 tests):
- `test_batch_with_siemens_ct_files_pixel_spacing_extraction`
- `test_batch_with_ge_mri_photometric_inference`
- `test_batch_mixed_suppliers_auto_detection`
- `test_batch_supplier_rule_audit_trail`
- `test_batch_config_toggle_disables_supplier_rule`
- `test_batch_supplier_confidence_score_filtering`

**Configuration Application** (5 tests):
- `test_batch_respects_per_modality_algorithm_config`
- `test_batch_respects_max_changes_safety_limit`
- `test_batch_respects_timeout_per_file_config`
- `test_batch_config_change_affects_new_batches_not_active`
- `test_batch_risk_tier_assignment_by_config`

**Admin Dashboard APIs** (4 tests):
- `test_dashboard_metrics_calculation_accuracy`
- `test_dashboard_filter_and_search_functionality`
- `test_dashboard_export_to_csv_format`
- `test_dashboard_real_time_progress_polling`

### 10.3 Functional Tests (15-20 tests, from Phase 3 + new)

**Real-World Scenarios** (10 tests):
- `test_legacy_siemens_ct_500_files_known_issues`
- `test_ge_mri_batch_unknown_photometric`
- `test_mixed_supplier_archive_detection`
- `test_batch_with_medium_risk_manual_review_workflow`
- `test_batch_with_all_safe_changes_auto_applied`
- `test_batch_recovery_from_medium_risk_approval`
- `test_batch_with_network_failure_during_upload`
- `test_large_batch_1000_files_performance`
- `test_concurrent_batch_jobs_up_to_10`
- `test_batch_cleanup_on_disk_space_low`

**Performance Benchmarks** (5 tests):
- `test_batch_100_files_under_4_2_seconds` (42ms × 100)
- `test_batch_1000_files_under_60_seconds` (4 workers)
- `test_batch_api_upload_response_under_2_seconds`
- `test_dashboard_load_with_1m_audit_records_under_500ms`
- `test_config_cache_invalidation_effective_within_5_seconds`

### 10.4 Regression Tests (Phase 3 baseline)

- All 22 unit tests from Phase 3 must still pass
- Single-instance STOW-RS with `auto_normalize=true` unchanged
- Audit logging format compatible with existing dashboards
- Re-validation post-normalization still enforced
- Medium-risk items still logged to audit_logs

---

## 11. Implementation Order (Do Phase Reference)

### Phase 4.1: Database & Core Services (Days 1-2)

**Day 1 (8 hours)**:
1. Create database migrations for batch_jobs, batch_job_files, normalization_config tables
2. Extend audit_logs with batch_id, supplier columns
3. Create supplier_rules table with initial Siemens, GE, Philips records
4. Create SQLAlchemy models for all new tables
5. Write unit tests for schema (5+ tests)

**Day 2 (8 hours)**:
1. Implement ConfigService (load/cache/invalidate from database)
2. Implement SupplierRegistry base class + plugin pattern
3. Write unit tests for ConfigService & SupplierRegistry (8+ tests)
4. Verify Phase 3 dicom_normalizer still works

### Phase 4.2: Supplier Implementations (Days 2-3)

**Day 2-3 (16 hours)**:
1. Implement SiemensNormalizer (pixel spacing extraction, photometric inference)
2. Implement GENormalizer (photometric inference, SamplesPerPixel)
3. Implement PhilipsNormalizer (placeholder for Phase 4, active in Phase 5)
4. Integration tests with real DICOM samples (5+ test cases per supplier)
5. Verify supplier detection accuracy (99%+ target)

### Phase 4.3: Batch API & Celery Tasks (Days 3-5)

**Day 3 (8 hours)**:
1. Create batch_operations.py API endpoints:
   - POST /dicomweb/batch-normalize
   - GET /normalization/batch/{batch_id}
2. Implement ZIP extraction + file parsing
3. Implement progress polling endpoint
4. Write unit tests (8+ tests)

**Day 4 (8 hours)**:
1. Create batch_normalizer.py with Celery task chain:
   - batch_upload_task, validate_file_task, normalize_file_task
   - store_file_task, audit_file_task, finalize_batch_task
2. Implement chord pattern for parallel processing
3. Implement error handling & retry logic
4. Write integration tests (5+ tests)

**Day 5 (8 hours)**:
1. Implement report generation (JSON/CSV)
2. Implement batch cleanup (temp file removal)
3. Implement configuration endpoint (GET/PUT)
4. Write integration tests (4+ tests)

### Phase 4.4: Admin Dashboard (Days 5-7)

**Day 5-6 (16 hours)**:
1. Create dashboard pages using Next.js:
   - `/admin/normalization/page.tsx` (overview)
   - `/admin/normalization/batch/page.tsx` (list view)
   - `/admin/normalization/batch/[id]/page.tsx` (detail view)
2. Implement metrics calculation (algorithm effectiveness, supplier distribution)
3. Implement filtering/sorting/pagination
4. Connect to backend APIs

**Day 7 (8 hours)**:
1. Create `/admin/normalization/config/page.tsx` (configuration panel)
2. Create `/admin/normalization/audit/page.tsx` (audit history)
3. Create `/admin/normalization/review/page.tsx` (manual review queue)
4. Implement bulk approve/reject functionality

### Phase 4.5: Polish & Testing (Days 7-10)

**Day 7-8 (16 hours)**:
1. Gap analysis: Design vs Implementation verification
2. Performance testing (batch of 1K files, 4 workers)
3. Security review (temp file cleanup, permission checks)
4. Backward compatibility verification (Phase 3 unchanged)
5. Stress testing (10 concurrent batches)

**Day 9 (8 hours)**:
1. Documentation updates (API spec, admin guide, troubleshooting)
2. Deployment checklist + runbook
3. Create migration guide for Phase 4 upgrade

**Day 10 (4 hours)**:
1. Production readiness review
2. Final sign-off

---

## 12. Known Design Decisions

### Decision 1: Async Celery (not sync API)

**Rationale**:
- 1,000+ file batches would timeout sync API (>50s with 42ms baseline)
- Celery with 4 workers processes 100 files/min sustainably
- Decouples upload response from processing completion
- Redis queue already deployed

**Alternative Considered**: FastAPI background tasks (limited to single worker)

**Mitigation**: Comprehensive logging of task transitions, automatic retry (3x), DLQ monitoring

---

### Decision 2: Plugin Architecture (not config-driven rules)

**Rationale**:
- Vendor-specific logic (private tag parsing) requires imperative code
- Tests per supplier easily written as unit tests
- Flexible for future ML-based models per supplier
- Proven pattern in Phase 3 (DicomValidator extensions)

**Alternative Considered**: Rule DSL (YAML/JSON, complex for medical imaging logic)

**Mitigation**: Document plugin API, provide template for new suppliers, test thoroughly

---

### Decision 3: Manual Review for Medium-Risk (not auto-apply)

**Rationale**:
- PhotometricInterpretation changes can affect diagnostic accuracy
- Builds trust with clinical staff (transparent, auditable)
- Can auto-approve after Phase 4 validation + Phase 5 ML confidence

**Alternative Considered**: Auto-approve with manual override option

**Mitigation**: Provide "bulk approve by rule" UI, alert if queue > 100, detailed rationale per change

---

### Decision 4: WebSocket Optional (fallback to polling)

**Rationale**:
- Polling simpler for MVP (10-14 day timeline)
- Works for admin dashboard (5s refresh acceptable)
- WebSocket adds complexity (connection management, scaling)

**Alternative Considered**: Required WebSocket from start

**Mitigation**: Design allows WebSocket layer addition in Phase 5 without breaking change

---

### Decision 5: Per-Modality Configuration

**Rationale**:
- CT, MR, US have different diagnostic requirements
- Photometric interpretation varies by modality
- Allows per-modality safety thresholds

**Alternative Considered**: Single global config

**Mitigation**: Database schema supports per-modality override with _default fallback

---

## 13. Critical Files for Implementation

**Backend Services** (6 new, 3 modified):
```
NEW:
- backend/app/services/batch_normalizer.py (250 LOC) — Celery tasks
- backend/app/api/batch_operations.py (180 LOC) — Batch endpoints
- backend/app/services/config_service.py (120 LOC) — Config loading/caching
- backend/app/services/supplier_registry.py (80 LOC) — Plugin registry
- backend/app/services/suppliers/siemens.py (120 LOC) — Siemens rules
- backend/app/services/suppliers/ge.py (100 LOC) — GE rules
- backend/app/services/suppliers/philips.py (90 LOC) — Philips rules

MODIFIED:
- backend/app/main.py — Add batch router
- backend/app/services/dicom_normalizer.py — Add supplier param
- backend/app/core/exceptions.py — Add new exception classes
```

**Frontend** (4 new):
```
NEW:
- admin/src/app/normalization/page.tsx (250 LOC) — Overview dashboard
- admin/src/app/normalization/batch/page.tsx (200 LOC) — Batch list
- admin/src/app/normalization/batch/[id]/page.tsx (300 LOC) — Batch detail
- admin/src/app/normalization/config/page.tsx (200 LOC) — Configuration
- admin/src/app/normalization/audit/page.tsx (150 LOC) — Audit history
- admin/src/app/normalization/review/page.tsx (200 LOC) — Manual review
```

**Database** (4 new migrations):
```
NEW:
- backend/db/migrations/001_create_batch_tables.sql — batch_jobs, batch_job_files
- backend/db/migrations/002_create_config_table.sql — normalization_config
- backend/db/migrations/003_create_supplier_rules.sql — supplier_rules, normalization_reviews
- backend/db/migrations/004_extend_existing_tables.sql — audit_logs, dicom_instances
```

**Models** (3 new):
```
NEW:
- backend/app/models/batch.py — BatchJob, BatchJobFile models
- backend/app/models/normalization_config.py — NormalizationConfig model
- backend/app/models/supplier_rule.py — SupplierRule model
```

---

## 14. Success Criteria for Design Approval

Before proceeding to Do phase, verify:

- [x] All 3 endpoints fully specified (request/response)
- [x] Database schema documented with indexes, FK relationships
- [x] Supplier plugin interface clear and extensible
- [x] Celery task chain flow diagram complete
- [x] Dashboard wireframes detailed (5 pages)
- [x] Configuration system defined (env + DB + cache)
- [x] Error handling & exceptions mapped with recovery strategies
- [x] 10-14 day implementation realistic (300+ LOC backend, 150+ LOC frontend)
- [x] Backward compatibility maintained (Phase 3 API unchanged)
- [x] Testing strategy detailed (50+ unit, 20+ integration tests)

---

## 15. Appendix: Schema Migration SQL Examples

### Migration 001: Create Batch Tables

```sql
-- Create batch_jobs table
CREATE TABLE batch_jobs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id VARCHAR(128) NOT NULL,
  username VARCHAR(128),
  ip_address VARCHAR(45),
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  status_reason TEXT,
  total_files INTEGER NOT NULL,
  processed_files INTEGER DEFAULT 0,
  succeeded_files INTEGER DEFAULT 0,
  failed_files INTEGER DEFAULT 0,
  pending_review_files INTEGER DEFAULT 0,
  supplier VARCHAR(64),
  max_changes_per_file INTEGER DEFAULT 10,
  auto_normalize BOOLEAN DEFAULT true,
  temp_file_path VARCHAR(512),
  temp_storage_bytes BIGINT,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at TIMESTAMP WITH TIME ZONE,
  completed_at TIMESTAMP WITH TIME ZONE,
  processing_duration_ms BIGINT,
  error_summary JSONB,
  success_rate_percent NUMERIC(5,2)
);

CREATE INDEX idx_batch_jobs_user_id ON batch_jobs(user_id);
CREATE INDEX idx_batch_jobs_status ON batch_jobs(status);
CREATE INDEX idx_batch_jobs_created_at ON batch_jobs(created_at DESC);
CREATE INDEX idx_batch_jobs_supplier ON batch_jobs(supplier);

-- Create batch_job_files table
CREATE TABLE batch_job_files (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  batch_id UUID NOT NULL REFERENCES batch_jobs(id) ON DELETE CASCADE,
  filename VARCHAR(255) NOT NULL,
  sequence_number INTEGER NOT NULL,
  sop_instance_uid VARCHAR(128),
  study_instance_uid VARCHAR(128),
  series_instance_uid VARCHAR(128),
  modality VARCHAR(16),
  manufacturer VARCHAR(128),
  file_size_bytes BIGINT,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  status_description TEXT,
  normalization_changes JSONB,
  normalization_summary JSONB,
  supplier_applied VARCHAR(64),
  error_message TEXT,
  error_details JSONB,
  requires_review BOOLEAN DEFAULT false,
  review_status VARCHAR(32),
  review_note TEXT,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  processing_start_ms BIGINT,
  processing_duration_ms BIGINT
);

CREATE INDEX idx_batch_job_files_batch_id ON batch_job_files(batch_id);
CREATE INDEX idx_batch_job_files_status ON batch_job_files(status);
CREATE INDEX idx_batch_job_files_sop_instance_uid ON batch_job_files(sop_instance_uid);
CREATE INDEX idx_batch_job_files_sequence ON batch_job_files(batch_id, sequence_number);
```

### Migration 002: Create Configuration Table

```sql
CREATE TABLE normalization_config (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  modality VARCHAR(32) UNIQUE,
  algorithms_enabled JSONB,
  algorithms_disabled JSONB,
  max_changes_per_file INTEGER DEFAULT 10,
  deviation_tolerance_pct NUMERIC(5,2) DEFAULT 20.0,
  charset_confidence_threshold NUMERIC(3,2) DEFAULT 0.85,
  timeout_ms_per_file INTEGER DEFAULT 5000,
  batch_concurrent_workers INTEGER DEFAULT 4,
  batch_max_size INTEGER DEFAULT 1000,
  risk_tiers JSONB,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_by VARCHAR(128),
  change_reason TEXT
);

CREATE INDEX idx_normalization_config_modality ON normalization_config(modality);

-- Insert default global config
INSERT INTO normalization_config (
  modality,
  algorithms_enabled,
  algorithms_disabled,
  risk_tiers
) VALUES (
  NULL,
  '{"pixel_spacing": true, "missing_tags": true, "photometric": false, "charset": false}'::jsonb,
  '{"photometric": true, "charset": true}'::jsonb,
  '{"safe": "auto_apply", "medium": "manual_review", "risky": "reject"}'::jsonb
);
```

---

**Document Status**: READY FOR IMPLEMENTATION  
**Phase**: Design (Phase 4)  
**Next Step**: Do Phase — Backend implementation, Database migrations, Frontend implementation  
**Estimated Timeline**: 10-14 days (2 weeks)

**Approval Sign-off** (to be filled):
- [ ] Backend Lead: _________________ Date: _______
- [ ] Frontend Lead: ________________ Date: _______
- [ ] QA Lead: _____________________ Date: _______
- [ ] DevOps: ______________________ Date: _______
