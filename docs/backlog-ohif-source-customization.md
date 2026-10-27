# OHIF 소스 레벨 커스터마이징 백로그

**상태**: 대기 (다음 세션에서 진행)  
**우선순위**: P1  
**전제 조건**: OHIF 소스 전체 분석 완료 후 착수

---

## 배경

런타임 app-config.js 패칭 방식의 한계:
- MutationObserver → React 렌더 트리 충돌 (무한 루프, 검은 화면)
- DOM 직접 조작 → OHIF 가상 스크롤 테이블 구조 파괴
- About 모달 → OHIF React 모달 시스템과 충돌 (React #130)
- 인라인 onclick → JS 문자열 이스케이프 구문 오류

**결론**: config 수준 커스터마이징은 테마/색상/단축키까지만 안전. UI 컴포넌트 변경은 소스 레벨 필요.

---

## 1단계: 소스 구조 분석

| 디렉토리 | 분석 대상 |
|---------|----------|
| `platform/core/` | 데이터 모델, 서비스, 유틸리티 |
| `platform/app/` | 앱 엔트리포인트, 라우팅, WorkList |
| `platform/ui/` | UI 컴포넌트 라이브러리 |
| `platform/i18n/` | 국제화/로케일 시스템 |
| `extensions/` | cornerstone, dicom-pdf, dicom-microscopy 등 |
| `modes/` | longitudinal, tmtv, segmentation 등 |

### 핵심 파일

| 파일 | 기능 | 커스터마이징 필요 |
|------|------|:----------------:|
| `platform/app/src/routes/WorkList/WorkList.tsx` | Study List 화면 | ✅ 한국어, 날짜, 컬럼 |
| `platform/core/src/utils/formatDate.js` | 날짜 포맷 | ✅ YYYY-MM-DD |
| `platform/ui/src/components/AboutModal/` | About 다이얼로그 | ✅ WeRU.B 정보 |
| `platform/app/src/components/Header/` | 상단 헤더 | ✅ 로고, 메뉴 |
| `platform/i18n/src/locales/` | 번역 파일 | ✅ ko-KR 추가 |
| `platform/ui/src/components/StudyListTable/` | 테이블 컴포넌트 | ✅ 컬럼 정렬 |
| `platform/app/public/config/default.js` | 기본 설정 | ✅ DICOMweb |

---

## 2단계: 분석 항목

### A. i18n 시스템
- 로케일 파일 구조 (JSON 키 체계)
- ko-KR 번역 파일 전체 생성
- 날짜/시간 포맷 로케일 연동
- 동적 번역 키 vs 하드코딩 텍스트

### B. 컴포넌트 아키텍처
- React 컴포넌트 트리 (Provider 구조)
- 상태 관리 (Redux? Context? Zustand?)
- 모달 시스템 (Portal? Overlay?)
- 이벤트 버스 / 커맨드 시스템

### C. Extension 시스템
- Extension 등록 방법
- Custom Panel 추가 (Report Panel, AI Panel)
- Custom Tool 추가
- Custom Mode 생성

### D. 빌드 시스템
- Webpack 설정
- PUBLIC_URL / routerBasename 처리
- Monorepo 구조 (Lerna/Nx)
- 빌드 최적화 (QUICK_BUILD vs 전체)

---

## 3단계: 커스터마이징 목표

| # | 기능 | 현재 (런타임) | 목표 (소스) |
|---|------|:----------:|:---------:|
| 1 | Study List 한국어 | setTimeout 패칭 | i18n ko-KR 네이티브 |
| 2 | 날짜 포맷 | 빌드 시 sed 교체 | i18n 로케일 설정 |
| 3 | About 모달 | ❌ 충돌로 제거 | AboutModal 컴포넌트 교체 |
| 4 | 컬럼 정렬 | CSS !important | StudyListTable 컴포넌트 수정 |
| 5 | 환자명 포맷 | 미구현 | formatPatientName 수정 |
| 6 | 판독 상태 컬럼 | 미구현 | WorkList에 커스텀 컬럼 추가 |
| 7 | WeRU.B 테마 | CSS 주입 | Tailwind 테마 설정 |
| 8 | Report Panel | OHIF Extension 별도 | 내장 Extension |
| 9 | AI Panel | OHIF Extension 별도 | 내장 Extension |

---

## 4단계: 리팩토링 전략

### 업스트림 충돌 최소화
```
OHIF upstream (v3.13+)
    ↓ fork
WeRU.B fork
    ↓ 커스터마이징
    ├── platform/i18n/src/locales/ko-KR/ (신규, 충돌 없음)
    ├── platform/app/public/config/ (설정 파일, 충돌 적음)
    ├── extensions/werub-panel/ (신규 Extension, 충돌 없음)
    └── modes/werub-mode/ (신규 Mode, 충돌 없음)
    
최소 수정 (충돌 가능):
    ├── platform/core/src/utils/formatDate.js (1줄)
    └── platform/ui/src/components/AboutModal/ (컴포넌트 교체)
```

### 권장 접근
1. **OHIF fork 생성** (GitHub)
2. **ko-KR 로케일 파일 완성** (충돌 없음)
3. **WeRU.B Extension 개발** (충돌 없음)
4. **WeRU.B Mode 개발** (충돌 없음)
5. **최소 소스 수정** (formatDate, AboutModal만)
6. **upstream merge 테스트** (주기적)

---

## 예상 소요

| 단계 | 기간 |
|------|:----:|
| 소스 분석 | 3일 |
| ko-KR 로케일 | 2일 |
| WeRU.B Extension | 5일 |
| WeRU.B Mode | 3일 |
| 소스 수정 (최소) | 2일 |
| 테스트 + 빌드 | 2일 |
| **합계** | **~3주** |

---

## 현재 안정 상태 (런타임 패칭)

유지되는 기능:
- ✅ 날짜 포맷 YYYY-MM-DD (빌드 시 소스 수정)
- ✅ 컬럼 헤더 한국어 (setTimeout 패칭, 안정)
- ✅ 컬럼 정렬 (CSS table-layout: fixed)
- ✅ WeRU.B 로고/브랜딩
- ✅ 커스텀 CSS 테마
- ✅ DICOMweb 설정
- ✅ 에러 다이얼로그 비활성화

제거된 기능 (불안정):
- ❌ About 모달 (React 충돌)
- ❌ MutationObserver 기반 실시간 번역 (무한 루프)

---

*다음 세션에서 OHIF 소스 전체 분석부터 시작*
