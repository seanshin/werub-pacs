# OpenPACS API 빠른 참조

> **Base URL**: `https://his.example.org/pacs-api`
> **인증**: `Authorization: Bearer {JWT_TOKEN}`
> **Swagger**: https://his.example.org/pacs-api/docs

---

## 인증

```bash
# 로그인
POST /api/v1/auth/login
{"username": "admin", "password": "CHANGE_ME"}
→ {"access_token": "eyJ...", "refresh_token": "CHANGE_ME", "role": "admin"}

# SSO (HospitalRun JWT 토큰 그대로 사용 가능)
GET /api/v1/auth/me
Authorization: Bearer {HospitalRun_JWT}
→ {"username": "doctor", "role": "physician"}  # 자동 생성
```

---

## 환자 영상 (HospitalRun 연동 핵심)

```bash
# 환자 영상 목록 (MRN 또는 HospitalRun UUID)
GET /api/v1/patients/{mrn}/studies
→ {"total_studies": 3, "unread_count": 1, "studies": [...]}

# 환자 판독 리포트
GET /api/v1/patients/{mrn}/reports
→ {"total_reports": 2, "reports": [...]}

# ID 매핑 확인
GET /api/v1/patient-mappings/resolve/{mrn_or_uuid}
→ {"his_mrn": "HR-001", "dicom_patient_id": "HR-001", "his_patient_id": "uuid-abc"}
```

---

## 검사 오더

```bash
# 오더 생성 (→ 워크리스트 + 매핑 자동 생성)
POST /api/v1/orders
{
  "patient_id": "HR-20260506-0328",    # MRN
  "patient_name": "홍길동",
  "his_patient_uuid": "uuid-abc-123",  # HospitalRun UUID
  "modality": "CT",
  "body_part": "CHEST",
  "priority": "routine"
}
→ {"accession_number": "ACC-...", "status": "scheduled"}

# 오더 상태 확인
GET /api/v1/orders/{accession_number}/status
→ {"status": "completed", "has_images": true}
```

---

## DICOM 검증

```bash
# 단일 파일 검증
POST /api/v1/validation/validate
Content-Type: multipart/form-data
file=@sample.dcm
→ {"accepted": true, "findings": [...]}
```

---

## 판독 리포트

```bash
# 리포트 생성
POST /api/v1/reports
{"study_instance_uid": "1.2.3...", "patient_id": "HR-001", "findings": "...", "impression": "..."}

# 서명
POST /api/v1/reports/{id}/sign
→ {"status": "final", "signed_at": "2026-05-09T14:30:00Z"}
→ 의뢰의에게 자동 알림 발송
```

---

## AI 추론

```bash
# 추론 요청
POST /api/v1/ai/inference
{"model_name": "chest-xray-analyzer", "study_instance_uid": "1.2.3..."}
→ {"id": "job-uuid", "status": "queued"}

# 결과 확인
GET /api/v1/ai/jobs/{job_id}
→ {"status": "completed", "findings_count": 1, "results": {...}}
```

---

## 워크리스트

```bash
# 목록 (오늘)
GET /api/v1/worklist?scheduled_date=2026-05-12
→ {"total": 5, "results": [...]}

# 통계
GET /api/v1/worklist/stats
→ {"total": 5, "scheduled": 3, "completed": 2}
```

---

## 대시보드

```bash
# 오늘 통계
GET /api/v1/dashboard/today
→ {"pacs": {"total_studies": 10}, "reading": {"pending": 3}, "ai": {"jobs_today": 2}}

# 판독 대기 큐
GET /api/v1/dashboard/reading-queue
→ {"total": 10, "unread": 7, "queue": [...]}
```

---

## 알림

```bash
# 알림 목록
GET /api/v1/notifications?unread_only=true
→ {"count": 1, "unread": 1, "notifications": [...]}

# 읽음 처리
POST /api/v1/notifications/{id}/read
```

---

## AI 고급 기능 (v8.6 신규)

```bash
# 5단계 추론 체인
POST /api/v1/ai/advanced/reasoning-chain
{"symptoms":"흉통, 호흡곤란", "patient_age":55, "patient_sex":"M"}
→ {chain_id, final_assessment: {primary_diagnosis: {diagnosis_ko, icd10}, urgency, red_flags}}

# 약물 상호작용
POST /api/v1/ai/advanced/drug-interactions
{"drugs":["warfarin","aspirin","ibuprofen"]}
→ {interactions: [{drug_a, drug_b, severity:"major", clinical_effect}], has_major: true}

# KCD 질병코드 검색
POST /api/v1/ai/advanced/codes/kcd
{"query":"폐렴"}
→ {results: [{code:"J18.9", name_ko:"폐렴", category:"호흡기"}]}

# EDI 수가코드 검색
POST /api/v1/ai/advanced/codes/edi
{"query":"흉부CT"}
→ {results: [{code:"HZ211", name_ko:"흉부CT", price:168000}]}

# 재입원 위험도 예측
POST /api/v1/ai/advanced/predict/readmission
{"patient_age":70, "patient_sex":"M", "diagnosis":"폐렴", "length_of_stay":7}
→ {prediction: {risk_level:"high", score:8, estimated_readmission_rate:"30%+"}}

# FHIR R4 Condition 검색
POST /api/v1/ai/advanced/fhir/condition-search
{"query":"고혈압"}
→ FHIR Bundle {entry: [{resource: {resourceType:"Condition", code: {coding: [{code:"I10"}]}}}]}

# GPU 스케줄러
GET /api/v1/ai/advanced/gpu/status
→ {current_profile, vram: {total_gb:16, free_gb, loaded_models}, resident_models}
```

---

## 핵심영상(KOS) · 측정/주석 (뷰어 연동)

```bash
# 핵심영상을 표준 KOS(88.59) 문서로 생성·Orthanc 저장
POST /api/v1/reports/key-images
  { "sop_instance_uids": ["1.2.3...", "1.2.4..."], "description": "핵심영상" }
  → { orthanc_id, key_image_count, missing: [] }     # ADMIN/RADIOLOGIST

# 측정값·핵심영상·메모 영속화 (다음 세션 복원용)
GET  /api/v1/studies/{study_uid}/annotations
  → { measurements: [...], key_images: [...], notes }
POST /api/v1/studies/{study_uid}/annotations
  { "measurements": [...], "key_images": [...], "notes": null }
```

## 레지던트 성과 통계 (v11.1 신규)

```bash
# 예비판독(레지던트→전문의) 성과 — 수정률/일치율
GET /api/v1/reports/statistics/residents?days=90        # ADMIN/RADIOLOGIST
  → { period_days,
      summary: { resident_count, preliminary_count, finalized_count,
                 avg_correction_rate, avg_agreement_rate },
      by_resident: [ { resident, preliminary_count, finalized_count, pending_count,
                       impression_changed, findings_changed,
                       correction_rate, agreement_rate, avg_prelim_min } ] }
```

## DICOM 수신 모니터 (v11.1 신규)

```bash
# 최근 수신 스터디(C-STORE/업로드/Q-R) — Orthanc LastUpdate 역순 + 출처 결합
GET /api/v1/reception/recent?limit=40        # ADMIN/RADIOLOGIST/TECHNOLOGIST
  → { count, studies: [ { study_uid, received_at, patient_name, patient_id,
                          study_description, modality, series_count, is_stable,
                          origin, upload_method, source_ae_title,
                          source_institution, source_device } ] }
  # Orthanc 장애 시 { count:0, studies:[], error:"orthanc_unavailable" }
```

## IRB 승인 레지스트리 (v11.1 신규)

```bash
GET    /api/v1/irb                # 목록 + summary{active,expiring_soon,expired}  (ADMIN/RADIOLOGIST/RESEARCHER)
POST   /api/v1/irb                # 등록 (409 중복 프로토콜)                       (ADMIN)
  { "protocol_number":"IRB-2026-001", "title":"...", "principal_investigator":"...",
    "institution":"...", "approved_at":"2026-06-08", "expires_at":"2027-06-08", "scope_note":"..." }
PUT    /api/v1/irb/{id}           # 수정(상태 active|suspended)                    (ADMIN)
DELETE /api/v1/irb/{id}           # 삭제                                          (ADMIN)
  # 응답의 effective_status: 만료일 경과 시 'expired' 자동 표기, days_left 포함
```

---

## 전체 API 목록 (350+)

| 그룹 | 수 | 인증 |
|------|:--:|:----:|
| Auth | 5 | 일부 |
| Validation | 2 | 불필요 |
| DICOMweb | 3 | 필수 |
| Worklist | 6 | 필수 |
| Reports | 7 | 필수 |
| Reports — KOS(핵심영상) | 1 | RBAC |
| Reports — 레지던트 성과 (v11.1) | 1 | RBAC |
| Annotations(측정/주석) | 3 | 필수 |
| 수신 모니터 (v11.1) | 1 | RBAC |
| IRB 승인 (v11.1) | 4 | RBAC |
| QC | 3 | RBAC |
| Audit | 2 | Admin |
| AI (기본) | 8 | 필수 |
| AI Assist | 8 | RBAC |
| **AI Advanced** | **21** | **필수** |
| Migration | 2 | Admin |
| Patients | 2 | 필수 |
| Patient Mapping | 3 | 필수 |
| Orders | 2 | 필수 |
| Dashboard | 2 | 필수 |
| Templates | 4 | 필수 |
| Notifications | 4 | 필수 |
| WebSocket | 1 | - |
| System | 5 | 필수 |
| HIS 연동 | 11 | 필수 |
| 협진/외부 | 15 | RBAC |
| 기타 (SLA, 정규화 등) | 150+ | 필수 |
