# WeRU.B PACS

**Web-based PACS with AI-assisted Reading for Hospitals and Clinics**

![Version](https://img.shields.io/badge/version-v13.24-blue)
![API](https://img.shields.io/badge/API_endpoints-360+-green)
![License](https://img.shields.io/badge/license-proprietary-red)
![Docker](https://img.shields.io/badge/docker-15_containers-2496ED)
![MFDS](https://img.shields.io/badge/MFDS-Class_2_(pending)-orange)
![Python](https://img.shields.io/badge/python-3.12-3776AB)
![Next.js](https://img.shields.io/badge/Next.js-15-black)
![OHIF](https://img.shields.io/badge/OHIF-v3.12-5ACCE6)
![AI](https://img.shields.io/badge/AI_models-29-purple)

> Formerly **OpenPACS** -- A production-grade, web-based Picture Archiving and Communication System with integrated AI reading assistance, DICOM normalization engine, and Korean regulatory compliance (MFDS Class 2).

---

## Features

- **DICOM Server** -- Orthanc-based with DIMSE (C-STORE/C-FIND/C-MOVE/C-ECHO) and DICOMweb (QIDO/WADO/STOW-RS)
- **WeRU.B Viewer** -- OHIF v3.12 source-level build with native i18n (268 keys), custom Extensions
- **Report Extension** -- OHIF native sidebar panel for reading report CRUD, signing, templates
- **AI Panel Extension** -- In-viewer AI analysis, prior comparison, SOAP, differential diagnosis, DICOM SR
- **Reading Mode** -- Dedicated mode with Report+AI panels, W/L presets (7 modalities), keyboard shortcuts
- **Voice Input** -- 🎤 Speech-to-text in Report Panel (Web Speech API, Korean)
- **Multi-Monitor** -- M key to open second viewer window, dual/split URL modes
- **Next Unread** -- N key auto-navigates to next unread study for fast reading workflow
- **Urgent Alerts** -- WebSocket real-time push + browser Notification for critical findings
- **Admin Dashboard** -- Next.js 15 management portal with 27+ pages, unified stats dashboard
- **Notification Bell** -- Real-time WebSocket alerts with unread badge, urgency-colored dropdown
- **Alert Service** -- Centralized notification dispatch (DB + WebSocket + Email + Webhook) for SLA/retake/urgent events
- **Webhook Integration** -- Slack, Microsoft Teams, generic JSON webhook for external notification delivery
- **TAT Analytics** -- Turn Around Time analysis per radiologist/modality/hour with visual dashboard
- **AI Auto-Draft** -- MedGemma auto-generates preliminary reports on study completion (configurable)
- **Dark Mode** -- Toggle or system-preference dark theme for low-light reading rooms
- **Operation Manual** -- Role-based user guide (radiologist, technologist, admin)
- **AI-Assisted Reading** -- 29 AI models (medical 13 + general 16), 5 orchestration pipelines
- **AI Orchestration** -- Pipeline CRUD, A/B comparison, production promotion, quality evaluation (v8.8)
- **AI Apply-to-Report** -- Viewer AI panel results directly sync to reading report via native extension
- **IOCM Archive** -- Study archive/restore/delete with retention policies, thumbnails, DICOM tag viewer (v8.8)
- **FHIR R4** -- DiagnosticReport, RiskAssessment, Observation, Condition, CapabilityStatement wrappers (v8.6)
- **Retake Request** -- Radiologist→Technologist rescan workflow (request, approve, schedule, complete)
- **SLA Escalation** -- Per-modality thresholds, auto-reassign, supervisor escalation, resolution tracking
- **Reading Workflow** -- Worklist, status tracking, prior study comparison, hanging protocols, critical alerts
- **Patient Portal API** -- 9 endpoints for external portal integration (reports, thumbnails, notifications)
- **Imaging Protocols** -- 8 default protocols (CT/MR/CR/US) with CRUD management
- **Study Comments** -- Technologist notes and quality annotations per study
- **Cohort Builder** -- Research patient group search with batch anonymization
- **On-Call Management** -- Radiologist schedule CRUD with current oncall lookup
- **Preliminary Read** -- Resident draft → attending finalize workflow
- **Report Templates** -- 20 Korean radiology report templates across all modalities
- **DICOM Issue Control Center** -- 22 validation rules, admin-editable severity/message/auto-action, modality render config, error message templates (v9.0)
- **DICOM Auto-Fix** -- 13 auto-fixable rules, cascade fix (SOP-level batch), original backup with SHA256 hash, rollback API, fix history tracking (v9.1)
- **Celery Auto-Validate** -- 5-min periodic scan for unvalidated studies, auto-fix integration (v9.1)
- **Ingestion Hub** -- Admin upload center (drag & drop), patient self-upload portal (token-based), kiosk (touch-optimized), external PACS Q/R (C-FIND/C-MOVE), upload approval queue (v9.2)
- **DICOM Provenance** -- Origin tracking with 9 auto-classifications (internal/external/patient/kiosk/test/research/AI/migration/unknown), 30+ manufacturer patterns, sticky icon badges in reading queue (v9.3)
- **Full-Width Layout** -- Admin portal uses full browser width with no max-width cap, responsive to any screen size (v9.5)
- **Security Hardening** -- Credential externalization, fail-closed token blacklist, PBKDF2 600k iterations, login rate limiting, Break-the-Glass, session idle timeout (v10.0)
- **DICOM AI Standardization** -- AI results encoded as standards-compliant DICOM: TID 1500 Comprehensive SR + Segmentation (SEG) via highdicom, with Device Observer, DCM-coded confidence (Probability), and source-image evidence linkage (v10.1)
- **Credential Encryption at Rest** -- External PACS peer passwords encrypted with Fernet derived from the app secret (v10.1)
- **Connection Pool Hardening** -- Bounded DB pools (backend + Celery) protect the shared PostgreSQL; eliminated a per-task engine leak (v10.1)
- **DIMSE Workflow Standards** -- Modality Worklist (MWL C-FIND), MPPS (N-CREATE/N-SET performed-step tracking), and Storage Commitment (N-ACTION/N-EVENT-REPORT) via a pynetdicom SCP (AE OPENPACS-MWL) — commercial-grade modality workflow (v11.0)
- **HL7 v2 RIS Integration** -- MLLP listener mapping inbound ORM imaging orders to the worklist (→ MWL → MPPS), ADT accept, ACK/ORU construction — completes the standard RIS loop (v11.0)
- **Key Object Selection (KOS)** -- Generate standard KOS documents (88.59, "Of Interest") marking radiologist-selected key images (v11.0)
- **Image Delivery Optimization** -- WADO-RS JPEG2000-lossless transfer (~3× smaller frames) + Nginx gzip & HTTP/2 — faster large-CT loading (v11.0)
- **DICOM Conformance** -- Formal conformance statement v1.2 with PS3.2 §4 (Implementation Model, AE specs, association policies); KOS/MWL/MPPS/Storage Commitment generation documented (v11.0)
- **Auth Hardening** -- Upgrade-on-login migrates legacy password hashes to per-user salt (decoupling from SECRET_KEY for future rotation); FastAPI Prometheus metrics enabled (v11.0)
- **KOS / Measurement UI** -- Viewer panel to mark key images → generate standard KOS, and persist/restore Cornerstone measurements across sessions (canvas re-hydration) (v11.1)
- **Resident Performance Analytics** -- Preliminary-read (resident→attending) volume, attending correction rate, and agreement rate per resident (v11.1)
- **DICOM Reception Monitor** -- Auto-refreshing view of recent inbound studies (C-STORE/upload/Q-R) from Orthanc, enriched with provenance source (v11.1)
- **IRB Approval Registry** -- IRB protocol registry (number/PI/validity) underpinning research-use data governance, with expiry warnings (v11.1)
- **HIS Patient Mapping & Order Sync** -- Verified `MRN = DICOM PatientID` against the live HospitalRun DB; on-demand IMAGING order → worklist sync and patient-merge reconciliation (`merged_into_id`) re-tagging Orthanc studies to the surviving patient (v11.2)
- **PHI Access Control** -- Patient imaging/report endpoints restricted to clinical roles (researcher excluded) with per-access audit logging (v11.2)
- **Shift-based Reading Assignment** -- Auto-routes unread studies to on-duty readers (reuses on-call schedule) with load balancing; admin assignment console (v11.2)
- **Viewer AI Model Selection** -- Radiologist picks the AI model (default MedGemma + 28 active models) for image analysis in the viewer panel (v11.2)
- **Client E2E Suite** -- Playwright smoke tests (8 specs) against production covering HIS sync, reading assignment, viewer AI, data alignment, PHI denial, notifications, and WebSocket dedup (`e2e/`) (v11.3)
- **Notification Center** -- Full notification history page with urgency/unread filters, pagination, acknowledge for criticals; accurate unread badge (was capped at 20) (v11.3)
- **Frontend Performance** -- Single shared notification WebSocket (was 2 per page) and client-side navigation via next/link across the admin portal (v11.3)
- **AI Analysis Robustness** -- pydicom decode fallback for images Orthanc cannot render (e.g. PALETTE COLOR multiframe US) and fixed missing AI-server credentials in container env (v11.3)
- **Predictive Prefetch & Backup/DR** -- nginx frame proxy_cache + Celery prefetch queue warming (assignment+prior rules); backup/DR automation (DB+GPG, DICOM hardlink snapshot, recovery rehearsal) (v11.4–11.5)
- **3D VRT (client-side)** -- Cornerstone3D volume rendering + 3D hanging protocol, measurement lock, usage telemetry; server-GPU render auto-detected via network self-test (direct-link gated) (v11.6)
- **Patient Result Export** -- Medical-network-isolated: external portal pulls an MRN-sealed, Fernet-encrypted package (DICOM + final report) via a one-time gateway; key/data separation (v11.7–11.8)
- **Opportunistic AI Screening + AI Governance** -- Auto-screen incoming studies → actionable-finding alerts (SaMD-disclaimed) + acceptance tracking; model performance trends, drift detection, clinical/research compliance (v12.0–12.1)
- **XDS-I / XDM Export** -- Inter-institution image exchange as an IHE XDM package (ebRIM METADATA.XML + KOS + DICOM), no connected registry required (v12.2)
- **Security Hardening** -- Break-the-Glass scoped to clinical-read (113+ admin/export/destructive endpoints opt out), JIT authorization fail-closed, dead-code cleanup (v12.3)
- **External E-Signature** -- Patient consent (self + guardian PROXY) and radiologist report signing via the hospital common e-sign service (PKI CAdES/PAdES); RS256/JWKS audience-scoped SSO (v12.4)
- **EMR Certification Track** -- 전자의무기록 인증제 mapping (security S001-S013, interoperability I001-I010), IHE ATNA audit emitter; PACS underpins the cert's image interoperability/security (v12.4)
- **Admin UX** -- Role-gated navigation, unified settings hub, physician "내 환자" portal, lucide-react iconography (v12.4)
- **Operational BI Report** -- Management dashboard: received-study volume (incl. unread backlog) via study provenance, reading KPIs (completion, avg/P90 TAT), modality utilization, reader productivity, monthly auto-report (cron) + admin alert, CSV export (v12.5)
- **HSM assuranceLevel Sealing** -- Report e-signatures seal the sign service's reported assurance level (SOFTWARE/HSM_ANCHORED) — PACS holds no keys/HSM (hsm-single-custody) (v12.5)
- **AI Governance Extension** -- On-demand inference acceptance tracking (radiologist feedback → acceptance_at-keyed daily rollup) + drift circuit-breaker auto-quarantine (config-gated default-off, deactivates a drifting model so inference stops selecting it; action log + manual reactivation) (v12.6)
- **Robustness Hardening** -- 3-pass multi-agent system audit: DICOM auto-fix original-byte backup + working rollback (K1), beat-task overlap locks (H1), inference idempotency (H2), reading-assignment unique index (H3), concurrency guards; integration tests (IT 9/9, fix→rollback verified) (v12.8)
- **Performance** -- Orthanc `/tools/find Expand` 1-call replaces reading-queue/check_sla/auto_assign N+1 (0.52s→0.20s, ~60%); growth-path indexes (v12.8–12.9)
- **Operational Hardening** -- Body-size limit middleware (DoS/OOM backstop), startup schema-migration runner (removes per-request DDL lock contention), JWKS bounded-stale window (fail-closed after max-stale; native login unaffected) (v12.9)
- **Upload Chunk Streaming** -- `spool_upload_to_disk` streams uploads to disk in 1MB chunks (RAM-bounded, 413 over limit); removes the full-RAM-load OOM vector on large ZIP/CD imports; streaming paths get a 5GB cap vs 2GB elsewhere (v13.0)
- **Teaching File Library** -- Education case library for reading training: live-study reference + RBAC (view ADMIN/RAD/RESIDENT, write +RESIDENT, delete ADMIN), 4 tables + 14 APIs `/api/v1/teaching/*` (Orthanc metadata auto-capture, no name/MRN stored; search/tags/collections; atomic view counter), admin page with viewer link. Quiz/publish-approval/anonymized-export completed as v2 (v13.0–13.3)
- **XDS-I.b + PIX/MPI (Phase 1)** -- Cross-enterprise patient identity (MPI, 4 tables) + PIXm `$ihe-pix` (ITI-83) + PIX v2 HL7 (ITI-9/8, A40 merge) + ITI-41 SOAP/MTOM submission (config-gated). Mock affinity-domain self-verified; real domain is the remaining external gate (v13.12)
- **LIS (Pathology) Integration** -- With the upstream LIS: image query (svc-lis `Role.SERVICE` read-only + standard QIDO-RS passthrough + viewer launcher, SM→microscopy auto-route), MWL (HL7 ORM→listener→worklist), pathology WSI rendering (v13.19)
- **`/dicom-web` Token Gate** -- Blocks unauthenticated edge PHI exposure: backend `_authcheck` (nginx auth_request, lightweight JWT) + viewer `UserAuthenticationService` injects `pacs_token` + `satisfy any` (internal bypass) + auth cache; `StudyReadRoles` excludes RESEARCHER from QIDO/WADO (v13.19)
- **Pathology WSI Annotations (DICOM Sup 222)** -- Create standard Microscopy Bulk Simple Annotations (ANN, SOPClass …91.1) from computational-pathology AI (2D) or interactive drawing (3D SCOORD3D) via `POST /api/v1/pathology/{uid}/annotations`; microscopy viewer auto-loads ANN overlays + "Save Annotation" panel button; SM studies auto-route to microscopy mode (v13.20–13.24)
- **DICOM TLS (optional)** -- Install-product hardening: encrypt modality-LAN DIMSE (4242) with TLS (default-off; cert tooling `gen-dicom-tls.sh`, isolated C-ECHO verification `it-dicom-tls.sh`) (v13.23)
- **External E-Signature Completion** -- HIS common SSO (aud=pacs RS256/JWKS) activated + verified, JWKS kid-rotation refetch; report external PKI e-sign frontend (same-origin HIS session → staff-token → X-Sign-Token) with HSM-attestation badge (assuranceLevel auto-flips to HSM_ANCHORED after KMS-CA cutover) (v12.7)
- **DICOM Normalization** -- Non-standard DICOM auto-detection and correction (JPEG density manipulation detection), algorithm settings UI, AI-based analysis
- **QC Engine** -- Study merge/split, image quality validation, tag verification
- **Audit Logging** -- Full HIPAA/Korean medical law compliant audit trail
- **User Management** -- JWT + RBAC with Keycloak SSO, role-based access control
- **EMR Integration** -- Bidirectional sync with HospitalRun (patient, order, results)
- **Monitoring** -- Prometheus metrics, Grafana dashboards, health checks
- **Security** -- TLS 1.3, pgcrypto encryption, SBOM, anonymization engine
- **Regulatory** -- 25 MFDS documents ready, IEC 62304 Class B compliance

---

## Architecture

```
                           ┌─────────────────────────────────┐
                           │         WeRU.B PACS              │
                           │      (his.example.org)            │
                           └───────────┬─────────────────────┘
                                       │
                              Nginx (TLS 1.3)
                              Port 443 / 80
                                       │
              ┌────────────────────────┼────────────────────────┐
              │                        │                        │
    ┌─────────▼──────────┐  ┌─────────▼──────────┐  ┌─────────▼──────────┐
    │   /pacs-admin/     │  │   /pacs-api/       │  │   /viewer/         │
    │   Admin Dashboard  │  │   FastAPI Backend  │  │   WeRU.B Viewer    │
    │   (Next.js 15)     │  │   (Python 3.12)    │  │   (OHIF 3.13)      │
    │   Port 3002        │  │   Port 8001        │  │   Port 3001        │
    └────────────────────┘  └────────┬───────────┘  └────────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
    ┌─────────▼──────────┐ ┌────────▼─────────┐  ┌────────▼─────────┐
    │   Orthanc          │ │   PostgreSQL 16  │  │   Redis 7        │
    │   DICOM Server     │ │   (pgcrypto,     │  │   Cache/Queue    │
    │   HTTP: 8042       │ │    uuid-ossp)    │  │   Port 6379      │
    │   DICOM: 4242      │ │   Port 5432      │  │                  │
    └────────────────────┘ └──────────────────┘  └──────────────────┘
              │                                           │
    ┌─────────▼──────────┐                      ┌────────▼─────────┐
    │   Orthanc Storage  │                      │   Celery Workers │
    │   (DICOM files)    │                      │   AI Inference   │
    └────────────────────┘                      │   Queue          │
                                                └──────────────────┘
              ┌──────────────────────────────────────────────┐
              │   Monitoring Stack                           │
              │   ┌──────────────┐  ┌──────────────────┐    │
              │   │ Prometheus   │  │ Grafana           │    │
              │   │ Port 9090    │  │ Port 3003         │    │
              │   └──────────────┘  └──────────────────┘    │
              └──────────────────────────────────────────────┘

    External:
    ┌──────────────┐    ┌──────────────┐
    │ Keycloak SSO │    │ HospitalRun  │
    │ Port 8080    │    │ EMR (3000)   │
    └──────────────┘    └──────────────┘
```

**15 Docker Containers**: PostgreSQL, Redis, Orthanc, OHIF Viewer, **WeRU.B Viewer**, FastAPI Backend, Admin Dashboard, Celery Worker, **Celery Beat**, **mwl-scp (MWL/MPPS/Storage Commitment SCP)**, **hl7-listener (HL7 v2 MLLP)**, Prometheus, Grafana, Node Exporter, Nginx

---

## Quick Start

### Prerequisites

- Docker Engine 24+ and Docker Compose v2
- 8GB+ RAM, 50GB+ disk space
- Domain with SSL certificate (for production)

### Installation

```bash
# Clone the repository
git clone https://github.com/seanshin/openpacs.git
cd openpacs

# Copy environment file and configure
cp .env.example .env
# Edit .env with your settings

# Start all services
docker compose up -d

# Verify all containers are running
docker compose ps
```

### Access URLs (default)

| Service | URL | Auth |
|---------|-----|------|
| **Admin Dashboard** | https://localhost/pacs-admin/ | Set in `.env` |
| **WeRU.B Viewer** | https://localhost/werub-viewer/ | -- |
| **OHIF Viewer** | https://localhost/viewer/ | -- |
| **API Documentation** | https://localhost/pacs-api/docs | -- |
| **Grafana Monitoring** | https://localhost/grafana/ | Set in `.env` |
| **Orthanc Explorer** | https://localhost/pacs/ | Set in `.env` |
| **DICOM Port** | 127.0.0.1:4242 (AET: OPENPACS) | AE Title auth |

### Health Check

```bash
curl -sk https://localhost/pacs-api/health
# {"status": "healthy", "version": "1.2.0", ...}
```

---

## API Overview

350+ endpoints organized across 40+ modules:

| Module | Endpoints | Description |
|--------|:---------:|-------------|
| **Auth** | 8 | JWT login, refresh, Keycloak SSO, session management |
| **Users** | 10 | User CRUD, roles, permissions, profile |
| **Worklist** | 12 | Study worklist, status management, assignments |
| **Reading** | 14 | Reading workflow, status transitions, assignments |
| **Report** | 11 | Report CRUD, signing, batch status, structured reports |
| **Template** | 8 | Report template management (20 Korean templates) |
| **AI** | 12 | Model management, inference pipeline, results |
| **AI Assist** | 7 | SOAP, differential diagnosis, comparison, explain |
| **DICOMweb** | 8 | QIDO-RS, WADO-RS, STOW-RS proxy |
| **Validation** | 6 | DICOM tag validation, JPEG density check |
| **Normalization** | 8 | Batch normalization, rule engine, status tracking |
| **QC** | 6 | Study merge/split, quality control |
| **Audit** | 5 | Audit log query, export, statistics |
| **환자 포털** | 9 | Patient search (초성), studies, reports |
| **주치의 포털** | 9 | My patients, report PDF, thumbnail, notifications |
| **Prior Studies** | 3 | Prior study lookup, comparison |
| **Order** | 5 | Order management, HospitalRun sync |
| **System** | 5 | Health check, statistics, system info |
| **Migration** | 3 | Legacy PACS data import, CD import |
| **촬영 프로토콜** | 5 | Protocol CRUD, modality-specific defaults |
| **촬영 메모** | 3 | Study comments/notes for technologists |
| **연구 코호트** | 2 | Cohort search, UID export for anonymization |
| **온콜 관리** | 4 | On-call schedule CRUD, current oncall lookup |
| **정규화 설정** | 3 | Algorithm config, trigger settings, AI analysis |
| **재촬영 요청** | 5 | Retake request CRUD, approval workflow, stats |
| **SLA 에스컬레이션** | 7 | Threshold config, escalation rules, history, stats |
| **HIS 연동** | 11 | Retake, cancel, additional view, urgent read, patient update, clinical info, schedule, slots, request log |
| **AI Orchestration** | 16 | Pipeline CRUD, run, test, A/B compare, promote, evaluate (v8.8) |
| **AI Advanced** | 21 | Inference chain, BI-RADS, drug interaction, readmission/complication/ADR prediction (v8.6) |
| **FHIR R4** | 5 | DiagnosticReport, RiskAssessment, Observation, Condition, Capability (v8.6) |
| **Archive (IOCM)** | 12 | Archive, restore, delete, stats, retention policy, thumbnails, DICOM tags (v8.8) |
| **KCD/EDI** | 3 | Disease/procedure code search, disease→exam mapping (v8.6) |
| **DICOM Issues** | 23 | Validation rules, auto-fix, scan, modality config, messages (v9.0-9.1) |
| **Ingestion Hub** | 21 | Upload, patient portal, kiosk, external PACS Q/R, approval queue (v9.2) |
| **Provenance** | 6 | Origin tracking, auto-classification, statistics (v9.3) |
| **Key Images (KOS)** | 1 | Key Object Selection 88.59 generation from marked images (v11.0) |
| **Annotations** | 3 | Measurement/key-image persistence + session restore (v11.0) |
| **Resident Stats** | 1 | Preliminary-read performance — correction/agreement rate (v11.1) |
| **Reception Monitor** | 1 | Recent inbound studies (C-STORE/upload/Q-R), origin-enriched, auto-refresh (v11.1) |
| **IRB Approval** | 4 | IRB protocol registry for research-use governance (v11.1) |
| **Admin** | 5 | Dashboard stats, system configuration |

Full API documentation available at `/pacs-api/docs` (Swagger UI) and `/pacs-api/redoc` (ReDoc).

---

## WeRU.B Viewer

<!-- Screenshot placeholder: Add viewer screenshot here -->
<!-- ![WeRU.B Viewer](docs/images/viewer-screenshot.png) -->

Built from OHIF Viewer v3.12.0 source with Cornerstone3D rendering engine.

**Core Features:**
- 2D viewing with Window/Level, Pan, Zoom, Scroll
- MPR (Multi-Planar Reconstruction) -- Axial, Sagittal, Coronal
- Measurement tools -- Length, Angle, Area, ROI statistics
- Annotation tools -- Arrow, Text, Freehand
- Hanging Protocol support with MxN grid + prior comparison

**WeRU.B Customizations (v8.8.1):**
- Native Korean i18n -- 268 translation keys, 16 namespaces
- Date format `YYYY-MM-DD`, patient name Korean-aware formatting
- **Report Extension** -- OHIF sidebar panel for reading CRUD, signing (Ctrl+Enter), templates, macros
- **AI Panel Extension** -- In-viewer AI analysis, SOAP summary, differential diagnosis, pipeline execution, DICOM SR save, apply-to-report bridge
- **Reading Mode** -- Report + AI panels open by default, optimized for radiologist workflow
- W/L presets per modality -- CT (7), MR (3), CR/DX (2), US, MG, PT (Korean labels)
- Keyboard shortcuts:
  - `N` next unread study, `M` second monitor window
  - `1`-`5` W/L presets, `.` `,` layout switch
  - `Ctrl+Enter` sign report, `Ctrl+Z/Y` undo/redo
- Study List -- report status badges (미판독/작성중/완료), batch status API
- About modal -- WeRU.B branding with version and license info

**Configuration:** `werub-viewer/config/werub-app-config.js`
**Build:** `werub-viewer/build.sh` (OHIF source clone → patch → build)

---

## Admin Dashboard

Next.js 15 App Router application with 26+ management pages:

| Page | Path | Description |
|------|------|-------------|
| Dashboard | `/` | System overview, statistics, charts |
| Worklist | `/worklist` | Study worklist with filters, status management |
| Reading | `/reading` | Reading assignment, status tracking, SLA |
| Reading View | `/reading/view` | Professional reading station (redesigned v8.0) |
| Templates | `/templates` | Report template editor (20 templates) |
| AI Models | `/ai` | AI model management, inference history |
| Normalization | `/normalization` | Dashboard / Settings / AI Analysis (3-tab) |
| Batches | `/normalization/batches` | Normalization batch management |
| Retake | `/retake` | Retake request workflow (NEW v8.0) |
| SLA | `/sla` | SLA escalation config, history, stats (NEW v8.0) |
| Users | `/users` | User management, role assignment |
| Audit | `/audit` | Audit log viewer, export |
| Technologist | `/technologist` | Technologist workstation |
| Emergency | `/emergency` | Emergency board with wait-time tracking |
| Consults | `/consults` | Unified consult management |
| Anonymize | `/anonymize` | DICOM anonymization tools |
| HIS | `/his` | HIS/EMR integration request log (NEW v8.1) |
| Archive | `/archive` | IOCM study archive management (NEW v8.8) |
| Pipeline | `/pipeline` | AI orchestration pipeline management (NEW v8.8) |
| AI Models | `/ai/models` | AI model groups, toggle inference targets (v8.8) |
| Tenants | `/tenants` | Multi-tenant configuration |
| **Upload Center** | `/upload` | Drag & drop DICOM upload with validation (v9.2) |
| **Upload Queue** | `/upload-queue` | Patient/kiosk upload approval workflow (v9.2) |
| **DICOM Issues** | `/dicom-issues` | Issue dashboard, auto-fix, scan (v9.0) |
| **Issue Settings** | `/dicom-issues/settings` | Validation rules, modality config, messages (v9.0) |
| **External PACS** | `/remotes` | Peer/modality CRUD, C-ECHO, Q/R (v9.2) |

### Independent Portals (v9.2)

| Portal | Path | Auth | Description |
|--------|------|------|-------------|
| **Patient Upload** | `/pacs-admin/patient-upload?token=...` | Token (24h) | Patient self-upload with consent workflow |
| **Kiosk** | `/pacs-admin/kiosk` | API Key | Touch-optimized CD/USB upload with barcode |
| **Consult Portal** | `/pacs-admin/consult-portal?token=...` | Token (7d) | External radiologist consultation |

---

## Report Templates

20 Korean radiology report templates organized by modality:

| Modality | Templates | Examples |
|----------|:---------:|---------|
| **CT** | 5 | Chest CT, Abdomen CT, Brain CT, Spine CT, CT Angiography |
| **MRI** | 5 | Brain MRI, Spine MRI, Knee MRI, Shoulder MRI, Abdomen MRI |
| **X-Ray (CR/DR)** | 4 | Chest PA, Abdomen, Spine, Extremity |
| **Ultrasound** | 3 | Abdomen US, Thyroid US, Breast US |
| **Mammography** | 1 | Screening Mammography (BI-RADS) |
| **Fluoroscopy** | 1 | UGI Series |
| **Nuclear Medicine** | 1 | Bone Scan |

Templates include structured fields, AI-suggested findings, and Korean medical terminology.

---

## Security

| Layer | Implementation |
|-------|---------------|
| **Transport** | TLS 1.3 via Nginx + Let's Encrypt, HSTS (63M seconds) |
| **Authentication** | JWT (access + refresh tokens), Keycloak SSO, WebSocket JWT auth |
| **Authorization** | RBAC (6 roles) with RequireRole dependency, Break-the-Glass emergency override |
| **Password Security** | PBKDF2-SHA256 (600,000 iterations), 12+ chars with complexity enforcement |
| **Session Management** | Token blacklist (fail-closed), 30-min idle timeout, Redis-backed |
| **Data Encryption** | pgcrypto (at-rest), TLS (in-transit) |
| **Audit** | Full audit trail for all data access, Break-the-Glass events |
| **Anonymization** | DICOM de-identification engine with per-deployment salt |
| **Rate Limiting** | Nginx zone-based (API 30r/s, auth 5r/m, upload 10r/m) + app-level login lockout |
| **Security Headers** | HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy |
| **Container Security** | Non-root backend container, internal port binding, DICOM auth required |
| **CORS** | Strict single-origin whitelisting |

---

## Regulatory Compliance

### MFDS (Korean FDA) Class 2 Medical Device

**Status**: 25 regulatory documents completed, administrative review pending.

**Document Categories:**
- Software Development Plan (IEC 62304 Class B)
- Software Requirements Specification
- Software Architecture Design
- Risk Management (ISO 14971)
- Usability Engineering (IEC 62366)
- Cybersecurity Documentation
- Clinical Evaluation Report
- Labeling and Instructions for Use

**Standards Compliance:**
- IEC 62304:2006/Amd 1:2015 -- Medical device software lifecycle
- ISO 14971:2019 -- Risk management
- IEC 62366-1:2015 -- Usability engineering
- DICOM PS3 -- Digital Imaging and Communications in Medicine
- HL7 FHIR R4 -- Interoperability (via HospitalRun)

**Korean Regulations:**
- 의료기기법 (Medical Device Act)
- 개인정보보호법 (Personal Information Protection Act)
- 의료법 제23조 (5-year retention requirement)

---

## Tech Stack

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **DICOM Server** | Orthanc | 24.12.2 | DIMSE + DICOMweb, PostgreSQL index plugin |
| **Backend API** | FastAPI (Python) | 3.12 | 350+ REST API endpoints |
| **Admin Dashboard** | Next.js | 15 | 21-page management portal |
| **Viewer** | OHIF Viewer | 3.12 | Source-built with custom Extensions |
| **Database** | PostgreSQL | 16 | 40+ tables, pgcrypto, uuid-ossp extensions |
| **Cache/Queue** | Redis | 7 | Session cache, Celery message broker |
| **Task Queue** | Celery | 5.x | AI inference async processing |
| **Auth** | Keycloak | 26.0 | SSO, OIDC, user federation |
| **Monitoring** | Prometheus | latest | Metrics collection |
| **Dashboards** | Grafana | latest | Monitoring visualization |
| **Reverse Proxy** | Nginx | 1.24 | TLS termination, routing, rate limit |
| **AI Server** | WeRU.B AI | v2.50.0 | 29 models (RTX 5080), orchestration platform |
| **Container** | Docker Compose | v2 | 13-container orchestration |

---

## Development

### Prerequisites

- Python 3.12+
- Node.js 20+ and npm
- Docker and Docker Compose v2
- PostgreSQL 16 (or use Docker)

### Backend Development

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn app.main:app --reload --port 8001
```

### Admin Dashboard Development

```bash
cd admin

# Install dependencies
npm install

# Run development server
npm run dev    # Available at http://localhost:3002
```

### WeRU.B Viewer Build

```bash
cd werub-viewer

# Full build from OHIF source (first time: ~10 min, subsequent: ~10 sec)
./build.sh

# Pipeline: clone OHIF v3.12.0 → apply patches → i18n → extensions → build
# Output: werub-viewer/dist/

# Docker build
docker build -t openpacs-werub .
```

### Running Tests

```bash
# Backend tests
cd backend
pytest --cov=app tests/

# Admin dashboard tests
cd admin
npm test
```

### Deployment

```bash
# Build and deploy all services
docker compose build
docker compose up -d

# Deploy backend only (hot reload on server)
scp -P 819 -r backend/app/ deploy@198.51.100.73:/home/deploy/openpacs/backend/app/
ssh deploy@198.51.100.73 -p 819 "cd /home/deploy/hospital-run/infra/docker && docker compose restart backend"

# View logs
docker compose logs -f backend orthanc --tail 50
```

---

## Project Structure

```
pacs/
├── admin/                    # Admin Dashboard (Next.js 15)
│   ├── src/
│   │   └── app/
│   │       ├── ai/           # AI model management
│   │       ├── audit/        # Audit log viewer
│   │       ├── consults/     # Unified consult management
│   │       ├── emergency/    # Emergency board
│   │       ├── dicom-issues/  # DICOM issue control center + settings (v9.0)
│   │       ├── kiosk/        # Touch-optimized kiosk upload (v9.2)
│   │       ├── normalization/ # DICOM normalization (dashboard/settings/AI)
│   │       ├── patient-upload/# Patient self-upload portal (v9.2)
│   │       ├── reading/      # Reading workflow + professional reading view
│   │       ├── remotes/      # External PACS peer/modality management (v9.2)
│   │       ├── retake/       # Retake request workflow (v8.0)
│   │       ├── upload/       # Admin DICOM upload center (v9.2)
│   │       ├── upload-queue/ # Upload approval queue (v9.2)
│   │       ├── sla/          # SLA escalation management (v8.0)
│   │       ├── technologist/ # Technologist workstation
│   │       ├── templates/    # Report templates
│   │       ├── users/        # User management
│   │       └── worklist/     # Study worklist
│   └── package.json
├── backend/                  # FastAPI Backend
│   ├── app/
│   │   ├── api/              # 137 API route handlers
│   │   ├── core/             # Config, security, database
│   │   ├── models/           # SQLAlchemy ORM models
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   ├── services/         # Business logic layer
│   │   ├── celery/           # Celery task definitions
│   │   └── main.py           # FastAPI application entry
│   ├── tests/
│   └── requirements.txt
├── docker/                   # Docker configuration
│   ├── orthanc/              # Orthanc config (orthanc.json)
│   └── postgres/             # DB init scripts
├── docs/                     # Documentation
│   ├── 01-plan/              # Project plans and roadmaps
│   │   └── features/         # Feature plans (v9.0-9.2)
│   ├── 02-design/            # Architecture and design docs
│   ├── api/                  # API integration guides
│   ├── regulatory/           # MFDS regulatory documents
│   └── security/             # Security documentation
├── monitoring/               # Prometheus + Grafana config
├── scripts/                  # Utility scripts
├── viewer/                   # OHIF Viewer configuration (backup viewer)
├── werub-viewer/             # WeRU.B Viewer (OHIF v3.12 source build)
│   ├── extensions/
│   │   ├── werub-report/     # Report Panel OHIF Extension
│   │   └── werub-ai/         # AI Panel OHIF Extension
│   ├── modes/
│   │   └── werub-reading/    # Reading Mode (Report+AI default)
│   ├── i18n/ko-KR.json       # Korean i18n (268 keys)
│   ├── patches/              # Source patches for reproducible builds
│   ├── config/               # WeRU.B app-config.js
│   └── build.sh              # OHIF clone → patch → build pipeline
├── docker-compose.yml        # 13-container orchestration
├── CLAUDE.md                 # AI assistant project context
└── README.md                 # This file
```

---

## License

- **WeRU.B PACS** (backend, admin, custom components): Proprietary -- Weruby
- **OHIF Viewer**: MIT License -- Open Health Imaging Foundation
- **Orthanc**: GPLv3 -- Sebastien Jodogne / Orthanc Team
- **Cornerstone3D**: MIT License -- Open Health Imaging Foundation

---

## Contributing

We welcome contributions to improve WeRU.B PACS. Please follow these guidelines:

1. Fork the repository and create a feature branch
2. Follow the existing code style and conventions
3. Write tests for new features
4. Update documentation as needed
5. Submit a pull request with a clear description

For major changes, please open an issue first to discuss the proposed changes.

**Contact**: Weruby -- [GitHub Issues](https://github.com/seanshin/openpacs/issues)

---

*Built with care for Korean healthcare by Weruby.*
