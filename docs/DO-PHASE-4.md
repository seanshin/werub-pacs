# Phase 4 Do Phase: Implementation Guide

**Feature**: Phase 4 DICOM Normalizer Enhancements  
**Timeline**: 10-14 days (2-3 weeks)  
**Status**: READY TO START  
**Reference Design**: `docs/02-design/features/phase-4-normalizer.design.md`

---

## 📋 Quick Start Checklist

### Pre-Implementation (Day 1)

- [ ] Review Design document thoroughly (1-2 hours)
- [ ] Set up local development environment
- [ ] Create git branch: `feature/phase-4-normalizer`
- [ ] Verify all dependencies installed (see below)
- [ ] Run existing Phase 3 tests to confirm baseline

### Implementation Phases

- [ ] **Phase 4.1** (Days 1-2): Database migrations & ConfigService
- [ ] **Phase 4.2** (Days 2-3): Supplier implementations (Siemens, GE, Philips)
- [ ] **Phase 4.3** (Days 3-5): Batch API & Celery task chain
- [ ] **Phase 4.4** (Days 5-7): Admin dashboard (6 pages)
- [ ] **Phase 4.5** (Days 7-10): Testing, gap analysis, documentation

---

## 🗂️ Key Files & Components

### Backend Files (New)

**Services** (6 files, ~700 LOC):
```
backend/app/services/
├── batch_normalizer.py              (Celery tasks, 250 LOC)
├── config_service.py                (Configuration, 120 LOC)
├── supplier_registry.py             (Plugin registry, 80 LOC)
└── suppliers/
    ├── siemens.py                   (120 LOC)
    ├── ge.py                        (100 LOC)
    └── philips.py                   (90 LOC)
```

**API** (1 file, ~180 LOC):
```
backend/app/api/
└── batch_operations.py              (Batch upload, progress, config endpoints)
```

**Models** (2 files, ~150 LOC):
```
backend/app/models/
├── batch_job.py                     (BatchJob, BatchJobFile, NormalizationReview)
└── normalization_config.py          (NormalizationConfig, RiskTierConfig)
```

### Backend Files (Modified)

```
backend/app/
├── main.py                          (Add batch_operations router)
├── services/dicom_normalizer.py     (Add supplier parameter)
└── api/dicomweb.py                  (Reuse validation, add Phase 3 regression tests)
```

### Frontend Files (New)

**Admin Dashboard** (6 pages, ~1,300 LOC):
```
admin/src/app/normalization/
├── page.tsx                         (Overview, metrics, 250 LOC)
├── batch/
│   ├── page.tsx                     (Batch list, 200 LOC)
│   └── [id]/
│       └── page.tsx                 (Batch detail, 300 LOC)
├── config/
│   └── page.tsx                     (Configuration, 200 LOC)
├── audit/
│   └── page.tsx                     (Audit history, 150 LOC)
└── review/
    └── page.tsx                     (Manual review queue, 200 LOC)
```

### Database Files (4 migrations)

```
backend/db/migrations/
├── 001_create_batch_tables.sql      (batch_jobs, batch_job_files)
├── 002_create_config_table.sql      (normalization_config)
├── 003_create_supplier_rules.sql    (supplier_rules)
└── 004_extend_existing_tables.sql   (audit_logs, dicom_instances)
```

---

## 🔧 Dependency Check

### Python Packages (Already Installed)

Verify these are in `backend/requirements.txt`:
- `celery>=5.2.0` — async task queue
- `redis>=4.0.0` — task broker & caching
- `sqlalchemy>=2.0.0` — ORM
- `pydicom>=2.3.0` — DICOM parsing
- `pydantic>=2.0.0` — validation

Run: `pip list | grep -E 'celery|redis|sqlalchemy|pydicom|pydantic'`

### Node.js Packages (Admin Dashboard)

In `admin/`:
```bash
npm install zustand zustand-persist  # State management + persistence
npm install react-query              # Server state (optional, for caching)
npm install ag-grid-react            # Data grids for batch details
```

### Infrastructure Services (Must Be Running)

- PostgreSQL 16+ on localhost:5432 (openpacs database)
- Redis 7+ on localhost:6379 (Celery broker)
- Celery worker process (run in separate terminal)

Check status:
```bash
psql -U openpacs -d openpacs -c "SELECT version();"
redis-cli ping                           # Should return "PONG"
```

---

## 📅 Detailed Implementation Plan

### Phase 4.1: Database & Configuration (Days 1-2)

**Deliverables**:
- 5 new database tables
- ConfigService class
- Environment variable loading
- Redis caching for configs

**Implementation Steps**:

1. **Create database migrations** (Day 1, 1-2 hours)
   ```bash
   # File: backend/db/migrations/001_create_batch_tables.sql
   # Create: batch_jobs (id, user_id, status, total_files, processed_files, etc.)
   #         batch_job_files (id, batch_id, filename, status, normalization_changes, etc.)
   # Indexes: batch_id, status, created_at
   
   # File: backend/db/migrations/002_create_config_table.sql
   # Create: normalization_config (id, modality, algorithms JSONB, risk_tiers JSONB)
   # Indexes: modality (unique)
   ```

2. **Create models** (Day 1, 1-2 hours)
   ```python
   # File: backend/app/models/batch_job.py
   class BatchJob(Base):
       id: UUID
       user_id: str
       status: str  # queued, processing, completed, failed, paused
       total_files: int
       processed_files: int
       succeeded_files: int
       failed_files: int
       supplier: str  # 'auto_detect' or specific
       temp_file_path: str
       created_at: datetime
       started_at: datetime
       completed_at: datetime
       error_summary: dict  # JSONB
   
   class BatchJobFile(Base):
       id: UUID
       batch_id: UUID (FK → BatchJob)
       filename: str
       status: str  # validated, normalizing, normalized, stored, failed
       normalization_changes: dict  # JSON
       error_message: str
       sequence_number: int
   
   class NormalizationReview(Base):
       id: UUID
       batch_id: UUID
       file_id: UUID
       reviewer_id: str
       decision: str  # approve, reject
       created_at: datetime
   ```

3. **Create ConfigService** (Day 2, 2-3 hours)
   ```python
   # File: backend/app/services/config_service.py
   class ConfigService:
       @staticmethod
       async def load_config(modality: str) -> NormalizationConfig:
           # Check Redis cache first
           # If miss, query database
           # Cache for 5 minutes
           pass
       
       @staticmethod
       async def update_config(modality: str, config: dict) -> None:
           # Validate config format
           # Update database
           # Invalidate Redis cache
           pass
       
       @staticmethod
       def get_environment_limits() -> dict:
           # Return: MAX_FILES, TIMEOUT_MS, MAX_CHANGES, etc.
           # From environment variables
           pass
   ```

4. **Run migrations** (Day 2, 30 min)
   ```bash
   cd backend
   alembic upgrade head  # Run migrations
   psql -U openpacs -d openpacs -c "\dt"  # Verify tables created
   ```

**Testing for Phase 4.1**:
- [ ] All 5 tables created with correct schema
- [ ] ConfigService loads/caches configs correctly
- [ ] Environment variable parsing works

---

### Phase 4.2: Supplier Implementations (Days 2-3)

**Deliverables**:
- Siemens, GE, Philips normalizer implementations
- Supplier registry with auto-detection
- 15+ unit tests for supplier logic

**Implementation Steps**:

1. **Create SupplierRegistry** (Day 2, 1 hour)
   ```python
   # File: backend/app/services/supplier_registry.py
   class SupplierRegistry:
       _registry: dict[str, SupplierNormalizer] = {}
       
       @classmethod
       def register(cls, name: str, normalizer: SupplierNormalizer) -> None:
           cls._registry[name] = normalizer
       
       @classmethod
       def auto_detect(cls, ds: pydicom.Dataset) -> Optional[SupplierNormalizer]:
           # Try each registered normalizer's detect() method
           # Return best match or None
           for name, normalizer in cls._registry.items():
               if normalizer.detect(ds):
                   return normalizer
           return None
   ```

2. **Implement SiemensNormalizer** (Day 2, 2 hours)
   ```python
   # File: backend/app/services/suppliers/siemens.py
   class SiemensNormalizer(SupplierNormalizer):
       def detect(self, ds: pydicom.Dataset) -> bool:
           # Check for Siemens private tags (0019,10xx)
           return (0x0019, 0x1008) in ds or (0x0019, 0x1010) in ds
       
       def normalize(self, ds: pydicom.Dataset) -> NormalizationResult:
           changes = []
           
           # Extract PixelSpacing from Siemens tag (0019,1008)
           if (0x0019, 0x1008) in ds:
               spacing_value = ds[0x0019, 0x1008].value
               # Convert to standard PixelSpacing
               if spacing_value != ds.get('PixelSpacing'):
                   changes.append(SupplierChangeRecord(
                       tag='PixelSpacing',
                       original=ds.get('PixelSpacing'),
                       corrected=spacing_value,
                       supplier='Siemens'
                   ))
                   ds.PixelSpacing = spacing_value
           
           return NormalizationResult(changes=changes)
   ```

3. **Implement GENormalizer** (Day 2-3, 2 hours)
   ```python
   # File: backend/app/services/suppliers/ge.py
   class GENormalizer(SupplierNormalizer):
       def detect(self, ds: pydicom.Dataset) -> bool:
           # Check for GE manufacturer string in ManufacturerModelName
           mfg = ds.get('ManufacturerModelName', '')
           return 'GE' in str(mfg).upper()
       
       def normalize(self, ds: pydicom.Dataset) -> NormalizationResult:
           changes = []
           
           # Infer PhotometricInterpretation from JPEG markers
           # (Only if transfer syntax is JPEG)
           if 'JPEG' in str(ds.file_meta.TransferSyntaxUID):
               # GE JPEG files often have mismatched PhotometricInterpretation
               inferred = self._infer_photometric(ds)
               if inferred != ds.get('PhotometricInterpretation'):
                   changes.append(...)
           
           return NormalizationResult(changes=changes)
       
       def _infer_photometric(self, ds: pydicom.Dataset) -> str:
           # Logic to infer from PixelData structure
           pass
   ```

4. **Implement PhilipsNormalizer** (Day 3, 1-2 hours)
   ```python
   # File: backend/app/services/suppliers/philips.py
   class PhilipsNormalizer(SupplierNormalizer):
       def detect(self, ds: pydicom.Dataset) -> bool:
           mfg = ds.get('Manufacturer', '')
           return 'Philips' in str(mfg)
       
       def normalize(self, ds: pydicom.Dataset) -> NormalizationResult:
           # Phase 4: Minimal (flag for manual review)
           # Phase 5: Full JPEG artifact detection
           return NormalizationResult(changes=[])
   ```

5. **Register suppliers** (Day 3, 30 min)
   ```python
   # In startup code (e.g., app/main.py)
   SupplierRegistry.register('siemens', SiemensNormalizer())
   SupplierRegistry.register('ge', GENormalizer())
   SupplierRegistry.register('philips', PhilipsNormalizer())
   ```

**Testing for Phase 4.2**:
- [ ] Registry auto-detection works for each supplier
- [ ] SiemensNormalizer extracts correct PixelSpacing
- [ ] GENormalizer detects GE JPEG files
- [ ] PhilipsNormalizer initializes (even if minimal)
- [ ] All 15 unit tests pass

---

### Phase 4.3: Batch API & Celery Tasks (Days 3-5)

**Deliverables**:
- 3 API endpoints (batch upload, progress, config)
- Celery task chain (7 tasks)
- ZIP file parsing & validation
- Progress tracking & reporting

**Implementation Steps**:

1. **Create batch_operations.py endpoint** (Day 3, 2-3 hours)
   ```python
   # File: backend/app/api/batch_operations.py
   router = APIRouter(prefix="/api/v1", tags=["batch"])
   
   @router.post("/dicomweb/batch-normalize")
   async def batch_normalize(
       request: Request,
       user: User,
       db: AsyncSession,
       files: List[UploadFile],  # or single zip
       supplier: Optional[str] = Query(None),
       auto_normalize: bool = Query(True),
   ):
       # 1. Validate batch size
       total_size = sum(f.size for f in files)
       if total_size > MAX_BATCH_SIZE:
           raise BatchSizeExceededError()
       
       # 2. Create batch_job record
       batch_job = BatchJob(
           user_id=user.id,
           status='queued',
           total_files=len(files),
           supplier=supplier or 'auto_detect'
       )
       db.add(batch_job)
       await db.commit()
       
       # 3. Save files to temp storage
       temp_files = await save_temp_files(files)
       batch_job.temp_file_path = temp_dir
       await db.commit()
       
       # 4. Enqueue to Celery
       batch_upload_task.delay(batch_job.id)
       
       return {
           "batch_id": batch_job.id,
           "status": "queued",
           "total_files": len(files),
           "progress_url": f"/api/v1/normalization/batch/{batch_job.id}"
       }
   
   @router.get("/normalization/batch/{batch_id}")
   async def get_batch_status(batch_id: UUID, db: AsyncSession):
       batch = await db.get(BatchJob, batch_id)
       files = await db.execute(
           select(BatchJobFile).where(BatchJobFile.batch_id == batch_id)
       )
       
       return {
           "batch_id": batch.id,
           "status": batch.status,
           "total_files": batch.total_files,
           "processed": batch.processed_files,
           "succeeded": batch.succeeded_files,
           "failed": batch.failed_files,
           "files": [
               {"filename": f.filename, "status": f.status, ...}
               for f in files
           ]
       }
   
   @router.get("/admin/normalization/config")
   @router.put("/admin/normalization/config")
   async def manage_config(modality: str, db: AsyncSession):
       # Load/update configuration
       pass
   ```

2. **Create Celery tasks** (Day 4, 3-4 hours)
   ```python
   # File: backend/app/services/batch_normalizer.py
   @shared_task
   def batch_upload_task(batch_id: str):
       # 1. Extract ZIP
       # 2. Validate DICOM magic bytes
       # 3. Create BatchJobFile records
       # 4. Enqueue parallel tasks
       pass
   
   @shared_task
   def validate_file_task(batch_id: str, file_id: str):
       # Use DicomValidator from Phase 3
       # Update status in batch_job_files
       pass
   
   @shared_task
   def normalize_file_task(batch_id: str, file_id: str):
       # 1. Detect supplier
       # 2. Load appropriate normalizer
       # 3. Apply normalization
       # 4. Check for medium-risk items
       # 5. Update batch_job_files with changes
       pass
   
   @shared_task
   def store_file_task(batch_id: str, file_id: str):
       # Upload to Orthanc
       # Update status
       pass
   
   @shared_task
   def audit_file_task(batch_id: str, file_id: str):
       # Log all changes to audit_logs
       # Include supplier attribution
       pass
   
   @shared_task
   def finalize_batch_task(batch_id: str):
       # Update batch_jobs.status = 'completed'
       # Generate report
       # Cleanup temp files
       pass
   ```

3. **Implement task chain** (Day 5, 1-2 hours)
   ```python
   from celery import chord
   
   def enqueue_batch_processing(batch_id: str):
       # Chord pattern: fork → parallel → join
       callback = finalize_batch_task.s(batch_id)
       
       jobs = [
           validate_file_task.s(batch_id, file_id),
           normalize_file_task.s(batch_id, file_id),
           store_file_task.s(batch_id, file_id),
           audit_file_task.s(batch_id, file_id),
       ]
       
       header = chord(jobs)
       return (header | callback).apply_async()
   ```

**Testing for Phase 4.3**:
- [ ] Batch upload endpoint accepts files & creates batch record
- [ ] Progress endpoint returns correct status
- [ ] Celery tasks execute in correct order
- [ ] ZIP parsing handles edge cases
- [ ] Config endpoint loads/updates configs
- [ ] All 20 integration tests pass

---

### Phase 4.4: Admin Dashboard (Days 5-7)

**Deliverables**:
- 6 Next.js pages (1,300+ LOC)
- State management (Zustand)
- Real-time metrics & batch monitoring
- Manual review workflow UI

**Implementation Steps**:

1. **Create layout & navigation** (Day 5, 1 hour)
   ```tsx
   // admin/src/app/normalization/layout.tsx
   export default function NormalizationLayout({ children }) {
       return (
           <div className="normalization-layout">
               <nav>
                   <Link href="/normalization">Overview</Link>
                   <Link href="/normalization/batch">Batches</Link>
                   <Link href="/normalization/config">Config</Link>
                   <Link href="/normalization/audit">Audit</Link>
                   <Link href="/normalization/review">Reviews</Link>
               </nav>
               {children}
           </div>
       )
   }
   ```

2. **Overview page** (Day 5-6, 250 LOC)
   ```tsx
   // admin/src/app/normalization/page.tsx
   // Displays:
   // - 4 metric cards (total files, success rate, avg time, pending reviews)
   // - 24h trends graph
   // - Active batch jobs table
   // - Recent activity feed
   ```

3. **Batch management pages** (Day 6, 500 LOC)
   ```tsx
   // admin/src/app/normalization/batch/page.tsx
   // List view with:
   // - Filtering, sorting, pagination
   // - Status badges
   // - Actions (retry, download, cancel)
   
   // admin/src/app/normalization/batch/[id]/page.tsx
   // Detail view with:
   // - Per-file status table
   // - Normalization changes detail
   // - Error messages
   // - Progress bar
   ```

4. **Configuration page** (Day 6, 200 LOC)
   ```tsx
   // admin/src/app/normalization/config/page.tsx
   // Modality tabs with:
   // - Algorithm toggles
   // - Risk tier dropdowns
   // - Safety limits (max changes, timeout)
   // - Supplier rule management
   ```

5. **Audit & Review pages** (Day 7, 350 LOC)
   ```tsx
   // admin/src/app/normalization/audit/page.tsx
   // Filterable audit history table
   
   // admin/src/app/normalization/review/page.tsx
   // Queue of pending medium-risk items for approval
   ```

**Testing for Phase 4.4**:
- [ ] All 6 pages render without errors
- [ ] Overview metrics update in real-time
- [ ] Batch detail shows correct per-file status
- [ ] Config page saves changes to API
- [ ] Review page displays medium-risk items
- [ ] All 15 functional tests pass

---

### Phase 4.5: Testing, Gap Analysis & Deployment (Days 7-10)

**Deliverables**:
- 85-105 total tests (50 unit, 20 integration, 35 functional)
- Gap analysis (vs Design)
- Documentation updates
- Production deployment checklist

**Implementation Steps**:

1. **Write unit tests** (Day 7-8, 3 hours)
   - Batch operations: ZIP parsing, size validation, error handling
   - Supplier registry: auto-detection, plugin loading
   - ConfigService: load, cache, update
   - Validation: DICOM magic bytes, file counts

2. **Write integration tests** (Day 8-9, 3 hours)
   - End-to-end batch flow: upload → normalize → store
   - Supplier-specific rules with real DICOM files
   - Configuration application per modality
   - Celery task chain execution
   - Dashboard APIs

3. **Regression tests** (Day 9, 1 hour)
   - [ ] All 22 Phase 3 unit tests still pass
   - [ ] Phase 3 STOW-RS single-file endpoint unchanged
   - [ ] Phase 3 audit logging still works

4. **Run gap analysis** (Day 9, 2 hours)
   ```bash
   /pdca analyze phase-4-normalizer
   # Gap detector compares Design vs Implementation
   # Target: ≥90% match rate
   ```

5. **Fix any gaps** (Day 9-10, as needed)
   - If match rate < 90%, iterate on implementation
   - Update code to match Design spec

6. **Production deployment** (Day 10, 1-2 hours)
   ```bash
   # 1. Run migrations on production
   psql -U openpacs -d openpacs < db/migrations/001_create_batch_tables.sql
   # ... etc for all 4 migrations
   
   # 2. Deploy backend code
   docker build -t openpacs-backend:phase4 .
   docker push openpacs-backend:phase4
   # Update docker-compose.yml to use new image
   docker-compose up -d backend
   
   # 3. Deploy admin dashboard
   npm run build
   docker build -t openpacs-admin:phase4 .
   docker-compose up -d admin
   
   # 4. Start Celery worker (if not already running)
   celery -A app.services.batch_normalizer worker -l info
   
   # 5. Verify health
   curl -s https://his.example.org/pacs-api/health | jq .
   curl -s https://his.example.org/pacs-admin/normalization | grep -q batch
   ```

---

## ✅ Success Criteria

### Code Quality
- [ ] 85+ total tests (50 unit, 20 integration, 35 functional)
- [ ] All tests passing (100% pass rate)
- [ ] ≥90% design match rate (verified by gap analysis)
- [ ] Zero breaking changes to Phase 3 API

### Performance
- [ ] Batch processing: 100+ files/minute
- [ ] Single file upload: <2 seconds
- [ ] Configuration load: <100ms (cached)
- [ ] Supplier detection: <50ms

### Functionality
- [ ] Batch upload accepts ZIP or multipart files
- [ ] Progress tracking shows per-file status
- [ ] Supplier-specific rules apply correctly
- [ ] Manual review workflow for medium-risk items
- [ ] Admin dashboard displays all metrics
- [ ] Configuration per-modality working

### Production Readiness
- [ ] Database migrations run cleanly
- [ ] Celery workers start without errors
- [ ] All services healthy (health endpoint returns 200)
- [ ] Admin dashboard accessible
- [ ] Audit logging records all changes
- [ ] 48+ hours of monitoring shows stability

---

## 🚨 Common Pitfalls to Avoid

1. **Celery task timeout** — Set reasonable timeouts per task (5-10 minutes for batch)
2. **Redis memory** — Monitor Redis growth; implement key expiration
3. **Temp file cleanup** — Ensure failed batches clean up temp files
4. **UUID collisions** — Use proper UUID generation (already in SQLAlchemy)
5. **Database connection pooling** — Reuse connections in Celery tasks
6. **Missing indexes** — Add indexes on frequently filtered columns (batch_id, status)
7. **Frontend state sync** — Use React Query or Zustand with persistence
8. **Permission checks** — Verify user has admin role before updating configs

---

## 📚 Reference Documents

- **Design Document**: `docs/02-design/features/phase-4-normalizer.design.md`
- **Phase 3 Code**: `backend/app/services/dicom_normalizer.py`, `backend/app/api/dicomweb.py`
- **Celery Docs**: https://docs.celeryproject.io/
- **SQLAlchemy Async**: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html

---

## 📝 Daily Standup Template

```
Date: [Date]
Phase: 4.[Phase Number]
Completed: [What was done]
In Progress: [What's being worked on]
Blockers: [Any issues]
Next: [Tomorrow's plan]
```

---

**Start Date**: 2026-05-15 (estimated)  
**Target Completion**: 2026-05-28 (10-14 days)  
**Status**: READY FOR DEVELOPMENT
