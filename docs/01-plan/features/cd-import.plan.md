# CD/DVD 영상 Import 고도화 기획

**작성일**: 2026-05-18  
**우선순위**: P1 (실무 즉시 필요)  
**예상 기간**: 1주

---

## 1. 배경

타원에서 환자 영상 CD를 받아 PACS에 등록하는 업무는 병원에서 **매일 발생**합니다. 현재는 파일을 개별 업로드하는 기본 기능만 있어 실무 적용이 어렵습니다.

### 현재 vs 목표

| 항목 | 현재 | 목표 |
|------|------|------|
| 업로드 방식 | 개별 파일 선택 | **폴더/ZIP/DICOMDIR 일괄** |
| DICOMDIR 파싱 | ❌ | ✅ CD 구조 자동 인식 |
| 환자 매칭 | ❌ | ✅ 기존 환자와 자동/수동 매칭 |
| 중복 감지 | ❌ | ✅ StudyInstanceUID 기반 |
| 진행률 표시 | ❌ | ✅ 실시간 WebSocket |
| Import 이력 | ❌ | ✅ 누가 언제 어떤 CD 등록했는지 |
| 정규화 연동 | ❌ | ✅ 비표준 DICOM 자동 정규화 |

## 2. API 설계

### 신규 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/v1/import/cd` | CD/ZIP/폴더 업로드 + Import 시작 |
| GET | `/api/v1/import/cd/{id}` | Import 작업 상태 조회 |
| GET | `/api/v1/import/cd/{id}/dicomdir` | DICOMDIR 파싱 결과 (환자/스터디 목록) |
| POST | `/api/v1/import/cd/{id}/confirm` | 환자 매칭 확인 후 Import 실행 |
| GET | `/api/v1/import/history` | Import 이력 목록 |
| WS | `/api/v1/ws/import/{id}` | Import 진행률 실시간 스트리밍 |

### 워크플로우

```
1. 사용자가 CD 파일(ZIP/폴더) 업로드
   → POST /api/v1/import/cd
   
2. 서버가 DICOMDIR 파싱 → 환자/스터디 목록 반환
   → GET /api/v1/import/cd/{id}/dicomdir
   
3. 사용자가 환자 매칭 확인 (기존 환자 vs 신규)
   → POST /api/v1/import/cd/{id}/confirm
   
4. 서버가 Orthanc에 업로드 (파일별 검증 + 정규화)
   → WebSocket으로 진행률 전송
   
5. 완료 → Import 이력 저장
   → GET /api/v1/import/history
```

## 3. 구현 항목

- `app/api/cd_import.py` — API 엔드포인트
- `app/services/dicomdir_parser.py` — DICOMDIR 파싱 서비스
- `app/services/cd_import_service.py` — Import 비즈니스 로직
- `app/models/import_history.py` — Import 이력 DB 모델
- `admin/src/app/import/page.tsx` — Admin Import UI
