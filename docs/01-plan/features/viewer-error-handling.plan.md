# 뷰어 오류 표시 개선 Plan

## 배경
RTSTRUCT, SR, PR, KO 등 픽셀 데이터가 없는 모달리티를 뷰어에서 열면 로딩 프로그레스바만 무한 표시되고 사용자에게 아무 피드백이 없다. 의료진은 "시스템 장애"로 오해하고 IT 부서에 문의하게 된다.

## 문제 정의

### 현재 동작
1. WeRU.B/OHIF 뷰어에서 Study를 로드
2. DICOMweb으로 시리즈/인스턴스 메타데이터 조회
3. Cornerstone3D가 픽셀 데이터 로드 시도
4. 픽셀 데이터 없음 → **무한 로딩 (사용자 오해 유발)**

### 영향받는 모달리티
| 모달리티 | 설명 | 픽셀 데이터 | 표시 방법 |
|----------|------|:-----------:|----------|
| RTSTRUCT | 방사선 치료 구조물 | 없음 | CT 오버레이 필요 |
| RTPLAN | 방사선 치료 계획 | 없음 | 전용 뷰어 필요 |
| RTDOSE | 방사선 선량 분포 | 있음(3D) | 전용 렌더러 필요 |
| SR | Structured Report | 없음 | 텍스트 표시 |
| PR | Presentation State | 없음 | 참조 영상에 적용 |
| KO | Key Object Selection | 없음 | 참조 목록 |
| SEG | Segmentation | 있음 | CT 오버레이 필요 |
| ANN | Annotation | 없음 | 참조 영상에 오버레이 |
| DOC/ENCAP PDF | 문서 | 없음 | PDF 뷰어 |

## 목표
- 표시 불가 Study를 열 때 **3초 이내** 명확한 오류/안내 메시지 표시
- 의료진이 원인을 즉시 이해하고 적절한 행동을 취할 수 있게 안내
- 가능한 경우 대체 표시 방법 제공 (SR → 텍스트, PDF → 임베드)

## 구현 범위

### 1단계: 사전 감지 & 안내 메시지 (필수)

**판독 큐 / 워크리스트 단계에서 사전 표시**
- 모달리티가 비렌더링 대상인 경우 목록에 아이콘/배지로 표시
- "뷰어 열기" 버튼 클릭 시 확인 다이얼로그:
  > "이 Study는 RTSTRUCT (방사선 치료 구조물) 모달리티로, 영상 데이터가 포함되어 있지 않습니다.  
  > 연결된 CT Study와 함께 열어야 구조물이 표시됩니다."

**뷰어 내 로딩 타임아웃 & 안내**
- DICOMweb 메타데이터 조회 후 렌더링 가능 여부 즉시 판단
- 판단 기준: Rows/Columns 태그 유무, SOP Class UID 확인
- 표시 불가 시 로딩 대신 안내 화면:

```
┌─────────────────────────────────────────┐
│         ⚠ 영상 표시 불가                  │
│                                         │
│  모달리티: RTSTRUCT                      │
│  설명: 방사선 치료 구조물 데이터           │
│                                         │
│  이 유형은 영상 픽셀 데이터를 포함하지     │
│  않아 뷰어에서 직접 표시할 수 없습니다.    │
│                                         │
│  [연결 CT 찾기]  [Study 정보 보기]  [닫기] │
└─────────────────────────────────────────┘
```

### 2단계: 대체 표시 (선택)

| 모달리티 | 대체 표시 방법 |
|----------|--------------|
| SR | 구조화 리포트 텍스트 파싱 후 HTML 렌더링 |
| ENCAP PDF/DOC | `<iframe>` PDF 뷰어 임베드 |
| RTSTRUCT/SEG | "연결 CT Study 찾기" → 함께 로드 |
| PR/KO | 참조 Study로 자동 리다이렉트 |

### 3단계: 로딩 타임아웃 가드 (범용)

모든 Study에 대해 로딩 타임아웃 적용:
- **10초** 경과 시: "로딩이 오래 걸리고 있습니다" 경고
- **30초** 경과 시: "Study를 표시할 수 없습니다" + 재시도/닫기 버튼
- 네트워크 오류 시: 즉시 "서버 연결 실패" 표시

## 비렌더링 모달리티 판별 로직

```python
# Backend: /api/v1/studies/{uid}/renderability
NON_RENDERABLE_SOP_CLASSES = {
    "1.2.840.10008.5.1.4.1.1.481.3",  # RT Structure Set
    "1.2.840.10008.5.1.4.1.1.481.5",  # RT Plan
    "1.2.840.10008.5.1.4.1.1.88.*",   # SR (Enhanced/Comprehensive/Basic)
    "1.2.840.10008.5.1.4.1.1.11.*",   # Presentation State
    "1.2.840.10008.5.1.4.1.1.88.59",  # Key Object Selection
    "1.2.840.10008.5.1.4.1.1.104.1",  # Encapsulated PDF
}

NON_RENDERABLE_MODALITIES = {"RTSTRUCT", "RTPLAN", "SR", "PR", "KO", "DOC"}
```

```typescript
// Frontend: 메타데이터 조회 후 판단
function isRenderable(metadata: DICOMMetadata): boolean {
  const hasPixels = metadata.Rows && metadata.Columns;
  const isNonRenderable = NON_RENDERABLE_MODALITIES.includes(metadata.Modality);
  return hasPixels && !isNonRenderable;
}
```

## 구현 대상 파일

| 위치 | 파일 | 변경 내용 |
|------|------|----------|
| Backend | `api/dicomweb.py` | Study renderability 판별 API 추가 |
| Admin | `app/reading/page.tsx` | 목록에서 비렌더링 모달리티 배지 표시 |
| Admin | `app/reading/view/page.tsx` | 뷰어 열기 전 확인 다이얼로그 |
| Admin | `components/ViewerButton.tsx` | 모달리티 확인 후 경고 표시 |
| WeRU.B | 뷰어 설정 | 로딩 타임아웃 & fallback 화면 |

## 메시지 사전

| 모달리티 | 한국어 안내 |
|----------|-----------|
| RTSTRUCT | 방사선 치료 구조물 데이터입니다. 연결된 CT 영상과 함께 열어야 합니다. |
| RTPLAN | 방사선 치료 계획 데이터입니다. 전용 RT 뷰어가 필요합니다. |
| RTDOSE | 방사선 선량 분포 데이터입니다. 전용 RT 뷰어가 필요합니다. |
| SR | 구조화 리포트(텍스트)입니다. 영상 데이터가 없습니다. |
| PR | Presentation State입니다. 참조 영상에 적용되는 표시 설정입니다. |
| KO | Key Object Selection입니다. 주요 영상 참조 목록입니다. |
| SEG | 분할(Segmentation) 데이터입니다. 원본 영상과 함께 열어야 합니다. |
| DOC/PDF | 문서 파일입니다. PDF 뷰어로 표시됩니다. |
| (타임아웃) | Study를 불러오는 데 시간이 오래 걸리고 있습니다. 네트워크 상태를 확인하세요. |
| (로드 실패) | Study를 표시할 수 없습니다. DICOM 파일이 손상되었거나 지원하지 않는 형식입니다. |

## 우선순위
1. **1단계** — 사전 감지 + 안내 메시지 (핵심, 즉시 구현)
2. **3단계** — 로딩 타임아웃 가드 (범용 안전장치)
3. **2단계** — 대체 표시 (SR/PDF, 추후)

## 제외 항목
- OHIF 뷰어 코어 수정 (WeRU.B 뷰어만 대상)
- RT 전용 뷰어 개발 (별도 프로젝트)
- DICOM 파일 자체 변환/수정
