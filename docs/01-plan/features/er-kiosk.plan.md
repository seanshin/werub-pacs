# 응급실 영상 보드 운영 기획서

> **Summary**: 응급실 PC에서 전용 계정으로 영상 보드에 즉시 접근하는 운영 방안
>
> **Project**: OpenPACS (WeRU.B)
> **Version**: v7.5+
> **Date**: 2026-05-20
> **Status**: Draft

---

## 1. 개요

### 1.1 목적

응급실(ER) 의료진이 별도 설정 없이 **전용 URL + 전용 계정**으로 영상 보드에 접근하여, 촬영된 영상의 판독 상태를 실시간으로 확인하고 즉시 뷰어로 열 수 있도록 한다.

### 1.2 현재 구현 상태

| 항목 | 상태 | 위치 |
|------|:----:|------|
| 응급 보드 API | ✅ | `GET /api/v1/emergency/board` |
| 응급 보드 UI | ✅ | `/pacs-admin/emergency` |
| STAT/긴급 우선 정렬 | ✅ | urgent/stat → unread → done |
| 대기 시간 색상 경고 | ✅ | 30분(주황), 60분(빨강+pulse) |
| 판독 완료 impression 미리보기 | ✅ | 초록색 요약 표시 |
| 15초 자동 갱신 | ✅ | setInterval |

---

## 2. 응급실 전용 계정

### 2.1 계정 정보

| 항목 | 값 |
|------|-----|
| **Username** | `er.doctor` |
| **Password** | `CHANGE_ME` |
| **Role** | `physician` |
| **Full Name** | `응급실` |
| **Department** | `Emergency` |

### 2.2 계정 생성 방법

```bash
# API로 생성 (admin 토큰 필요)
curl -sk -X POST https://his.example.org/pacs-api/api/v1/auth/register \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "er.doctor",
    "email": "er@hospital.local",
    "password": "CHANGE_ME",
    "full_name": "응급실",
    "role": "physician",
    "department": "Emergency"
  }'
```

### 2.3 권한 범위

`physician` 역할로 접근 가능한 기능:

| 기능 | API | 접근 |
|------|-----|:----:|
| 응급 보드 | `GET /api/v1/emergency/board` | ✅ |
| 판독 리포트 조회 | `GET /api/v1/reports` | ✅ |
| 영상 뷰어 | `/werub-viewer/?StudyInstanceUIDs=...` | ✅ |
| 환자 포털 | `GET /api/v1/patient-portal/*` | ✅ |
| 판독 서명/수정 | `POST /api/v1/reports/*/sign` | ❌ |
| QC/병합/분리 | `POST /api/v1/qc/*` | ❌ |
| 사용자 관리 | `*/users` | ❌ |

---

## 3. 접근 URL 및 링크

### 3.1 주요 URL

| 용도 | URL | 비고 |
|------|-----|------|
| **응급 보드** | `https://his.example.org/pacs-admin/emergency` | 메인 화면 |
| **영상 뷰어** (Study별) | `https://his.example.org/werub-viewer/?StudyInstanceUIDs={UID}` | 보드에서 클릭 |
| **판독 리포트** (Study별) | `https://his.example.org/pacs-admin/reading/view?study={UID}` | 판독 결과 상세 |
| **로그인** | `https://his.example.org/pacs-admin` → `er.doctor` / `CHANGE_ME` | 첫 접속 시 |

### 3.2 응급실 PC 설정 가이드

```
1. Chrome 브라우저 열기
2. 주소: https://his.example.org/pacs-admin/emergency
3. 로그인: er.doctor / CHANGE_ME
4. F11 → 전체 화면 모드
5. 즐겨찾기 등록 (Ctrl+D)
```

### 3.3 모바일 접근 (태블릿)

```
동일 URL 사용 — 반응형 UI 지원
Safari/Chrome에서 "홈 화면에 추가"로 앱처럼 사용 가능
```

---

## 4. API 명세

### 4.1 응급 보드 조회

```
GET /api/v1/emergency/board?hours=24
Authorization: Bearer {token}
```

**Response:**

```json
{
  "board": [
    {
      "study_uid": "1.2.3.4.5",
      "patient_name": "홍길동",
      "patient_id": "P001",
      "modality": "CT",
      "study_description": "CT ABDOMEN",
      "study_date": "20260520",
      "study_time": "083000",
      "read_status": "unread",       // unread | draft | preliminary | final
      "urgency": "urgent",           // normal | urgent | stat
      "wait_minutes": 45,            // 판독 대기 시간 (분)
      "impression": null,            // 판독 완료 시 요약 (최대 150자)
      "reader": null,                // 판독의 이름
      "signed_at": null,             // 서명 시각
      "viewer_url": "/werub-viewer/?StudyInstanceUIDs=1.2.3.4.5"
    }
  ],
  "total": 40,
  "urgent_count": 2,
  "pending_count": 15
}
```

### 4.2 로그인

```
POST /api/v1/auth/login
Content-Type: application/json

{ "username": "er.doctor", "password": "CHANGE_ME" }
```

**Response:**

```json
{
  "access_token": "CHANGE_ME",
  "refresh_token": "CHANGE_ME",
  "role": "physician",
  "username": "er.doctor",
  "expires_in": 3600
}
```

### 4.3 리포트 조회

```
GET /api/v1/reports?study_uid={StudyInstanceUID}
Authorization: Bearer {token}
```

### 4.4 관련 API 전체 목록

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/auth/login` | 로그인 |
| POST | `/api/v1/auth/refresh` | 토큰 갱신 |
| GET | `/api/v1/emergency/board` | 응급 보드 |
| GET | `/api/v1/reports?study_uid={uid}` | Study별 리포트 |
| GET | `/api/v1/reports/{id}` | 리포트 상세 |
| GET | `/api/v1/patient-portal/patients/{pid}/studies` | 환자별 검사 목록 |
| GET | `/api/v1/patient-portal/studies/{uid}` | 검사 상세 |
| GET | `/api/v1/dashboard/reading-queue` | 판독 큐 (전체) |

---

## 5. 화면 구성

### 5.1 응급 보드 레이아웃

```
┌────────────────────────────────────────────────────────┐
│ 응급 영상 보드                    STAT 2  대기 15  전체 40│
├────────────────────────────────────────────────────────┤
│ [전체] [STAT/긴급] [판독 대기] [판독 완료]              │
├────────────────────────────────────────────────────────┤
│ ┌────────────────────────────────────────────────────┐ │
│ │ 🔴 대기  홍길동  CT  CT ABDOMEN    45분  [영상보기] │ │ ← STAT (빨간 테두리)
│ └────────────────────────────────────────────────────┘ │
│ ┌────────────────────────────────────────────────────┐ │
│ │ 🟡 대기  김영희  MR  BRAIN MRI     12분  [영상보기] │ │ ← 일반 대기
│ └────────────────────────────────────────────────────┘ │
│ ┌────────────────────────────────────────────────────┐ │
│ │ 🟢 완료  이철수  CR  CHEST PA            [영상보기] │ │ ← 판독 완료
│ │   정상 소견. 폐야 깨끗함. 심비대 없음.               │ │ ← impression
│ └────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────┘
  15초 자동 갱신
```

### 5.2 색상 규칙

| 조건 | 색상 | 효과 |
|------|------|------|
| STAT/긴급 | 빨간 테두리 + `bg-red-50` | pulse 애니메이션 |
| 대기 < 30분 | 회색 | - |
| 대기 30~59분 | 주황색 | 굵은 글씨 |
| 대기 ≥ 60분 | 빨간색 | pulse 애니메이션 |
| 판독 완료 | 초록 배지 | impression 미리보기 |
| 예비 판독 | 보라 배지 | 예비 impression 표시 |

---

## 6. 운영 시나리오

### 6.1 일반 흐름

```
환자 응급실 도착 → CT/X-ray 촬영 → Orthanc 전송 →
응급 보드에 자동 표시 (15초 이내) → 응급의 확인 →
[영상 보기] 클릭 → WeRU.B 뷰어로 영상 확인 →
판독의 판독 완료 → 보드에 impression 표시 →
응급의 판독 결과 확인 → 환자 처치
```

### 6.2 긴급 소견 흐름

```
판독의가 urgent 마킹 → STAT 배지 + pulse 표시 →
WebSocket 알림 (브라우저 Notification) →
응급의 즉시 확인 → 영상 + impression 확인 → 즉시 처치
```

---

## 7. 보안 고려사항

| 항목 | 대응 |
|------|------|
| 공용 PC 로그인 유지 | JWT 60분 만료, 자동 갱신으로 근무 중 유지 |
| PHI 노출 | HTTPS 전송, 병원 내부망 권장 |
| 계정 공유 | `er.doctor`는 응급실 공용 — 개인 계정이 아님 |
| 감사 추적 | 모든 API 호출이 감사 로그에 `er.doctor`로 기록 |
| 퇴근 후 접근 | VPN 또는 내부망 제한 (Nginx IP 제한 가능) |

---

## 8. 테스트 계정 전체 목록

| Username | Password | Role | 용도 |
|----------|----------|------|------|
| `admin` | `CHANGE_ME` | admin | 관리자 |
| `dr.kim` | `CHANGE_ME` | radiologist | 전문의 (최종 서명) |
| `tech.park` | `CHANGE_ME` | technologist | 방사선사 |
| `dr.lee` | `CHANGE_ME` | physician | 주치의 |
| `res.choi` | `CHANGE_ME` | researcher | 연구자 |
| **`er.doctor`** | **`CHANGE_ME`** | **physician** | **응급실 전용** |

---

## 9. 다음 단계

1. [x] `er.doctor` 테스트 계정 생성 (서버)
2. [ ] 응급실 PC에 URL 즐겨찾기 등록
3. [ ] (선택) Nginx IP 제한 — 응급실 서브넷만 허용
4. [ ] (선택) 키오스크 전용 레이아웃 — 헤더 없는 전체화면 버전

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-05-20 | Initial draft | AI Assistant |
