# WeRU.B Viewer 추가 명세서

**문서 버전**: 2.0 (완전 분리 구조로 재설계)  
**작성일**: 2026-05-14  
**핵심 원칙**: 기존 OHIF는 일체 수정하지 않음. WeRU.B는 독립 뷰어로 추가.  
**라이선스**: MIT License (원본 저작권 고지 유지 필수)

---

## 1. 아키텍처 원칙

### 1.1 완전 분리 원칙

```
⚠️ 절대 규칙:
  - 기존 OHIF 컨테이너(openpacs-ohif)를 수정하지 않는다
  - 기존 /viewer/ 경로를 변경하지 않는다
  - 기존 OHIF app-config.js를 수정하지 않는다
  - 기존 OHIF Docker 이미지를 교체하지 않는다

WeRU.B Viewer는 100% 별도 빌드, 별도 컨테이너, 별도 경로로 운영된다.
```

### 1.2 시스템 구조

```
                    ┌──────────────┐
                    │   Nginx      │
                    │   (Proxy)    │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
     /werub-viewer/    /viewer/    /dicom-web/
              │            │            │
     ┌────────┴───┐  ┌────┴────┐  ┌───┴────┐
     │ WeRU.B     │  │ OHIF    │  │ Orthanc │
     │ Viewer     │  │ Viewer  │  │ DICOM   │
     │ :3004      │  │ :3001   │  │ :8042   │
     │ (신규)     │  │ (기존)  │  │ (기존)  │
     └────────────┘  └─────────┘  └────────┘
          │               │            │
          └───────────────┴────────────┘
                       │
              공유: DICOMweb API (읽기 전용)
              공유: 동일한 Orthanc DICOM 저장소
              공유: 동일한 스터디/환자 데이터
```

### 1.3 분리 보장 매트릭스

| 항목 | OHIF (기존) | WeRU.B (신규) | 공유 |
|------|:----------:|:------------:|:----:|
| Docker 컨테이너 | `openpacs-ohif` :3001 | `openpacs-werub` :3004 | ❌ |
| Docker 이미지 | `openpacs-ohif-kr:latest` | `openpacs-werub:latest` | ❌ |
| Nginx 경로 | `/viewer/` | `/werub-viewer/` | ❌ |
| app-config.js | 기존 그대로 | 별도 파일 | ❌ |
| 소스 코드 | 수정 없음 | 별도 디렉토리 | ❌ |
| 브랜딩 (로고, 이름) | OHIF 원본 | WeRU.B 자체 | ❌ |
| DICOMweb 백엔드 | `/dicom-web/` | `/dicom-web/` | ✅ |
| Orthanc 데이터 | 동일 Orthanc | 동일 Orthanc | ✅ |
| FastAPI 백엔드 | `/pacs-api/` | `/pacs-api/` | ✅ |

---

## 2. 수정 대상과 비수정 대상

### 2.1 수정하지 않는 파일 (기존 OHIF)

| 파일/서비스 | 이유 |
|-----------|------|
| `openpacs-ohif` Docker 컨테이너 | 기존 운영 유지 |
| `openpacs-ohif-kr:latest` 이미지 | 교체 금지 |
| OHIF `app-config.js` | 변경 금지 |
| Nginx `/viewer/` 설정 | 변경 금지 |
| `/viewer/` 접근 시 동작 | 현재와 100% 동일 |

### 2.2 신규 생성 (WeRU.B Viewer)

| 파일/서비스 | 내용 |
|-----------|------|
| `werub-viewer/` 디렉토리 (전체 신규) | 빌드 환경, 설정, 에셋 |
| `openpacs-werub` Docker 컨테이너 | 별도 포트 :3004 |
| Nginx `/werub-viewer/` 설정 | 신규 location 블록 추가 |

### 2.3 수정하는 파일 (Admin Dashboard만)

| 파일 | 변경 내용 | 기존 기능 영향 |
|------|----------|:-------------:|
| `admin/src/app/reading/view/page.tsx` | WeRU.B 뷰어 버튼 **추가** | ❌ 없음 |
| `admin/src/app/layout.tsx` | 헤더에 WeRU.B 링크 **추가** | ❌ 없음 |
| `admin/src/app/reading/page.tsx` | 판독 목록에 WeRU.B 열기 **추가** | ❌ 없음 |
| `admin/src/app/page.tsx` | 메인 대시보드에 WeRU.B 링크 **추가** | ❌ 없음 |
| `docker-compose.yml` | `werub-viewer` 서비스 **추가** | ❌ 기존 서비스 무변경 |

> **원칙**: 기존 OHIF 관련 코드는 그대로 두고, WeRU.B 버튼/링크를 **옆에 추가**

---

## 3. Admin Dashboard UI 변경

### 3.1 판독 화면 (`reading/view/page.tsx`)

**변경 전**:
```
┌───────────────────────────────────────────────────────────┐
│ 듀얼 화면 판독 모드                                        │
│ OHIF 뷰어를 별도 창으로 열어 다른 모니터에 배치하세요        │
│                                                            │
│  [🖥️ OHIF 뷰어 열기]              [단일 화면 모드]          │
└───────────────────────────────────────────────────────────┘
```

**변경 후**:
```
┌───────────────────────────────────────────────────────────────────┐
│ 듀얼 화면 판독 모드                                                │
│ 영상 뷰어를 별도 창으로 열어 다른 모니터에 배치하세요                 │
│                                                                    │
│  [🖥️ WeRU.B 뷰어 열기]  [🔬 OHIF 뷰어 열기]  [단일 화면 모드]      │
│   (권장 뷰어)             (원본 뷰어)                               │
└───────────────────────────────────────────────────────────────────┘
```

**코드 변경**:

```tsx
// 기존 코드 (유지)
const ohifViewerUrl = `/viewer/?StudyInstanceUIDs=${studyUID}`;
const openOhifViewer = () => {
  const w = window.open(ohifViewerUrl, 'ohif-viewer',
    'width=1200,height=900,menubar=no,toolbar=no,location=no,status=no');
  if (w) { setViewerOpened(true); w.focus(); }
};

// 신규 코드 (추가)
const werubViewerUrl = `/werub-viewer/?StudyInstanceUIDs=${studyUID}`;
const openWerubViewer = () => {
  const w = window.open(werubViewerUrl, 'werub-viewer',
    'width=1200,height=900,menubar=no,toolbar=no,location=no,status=no');
  if (w) { setViewerOpened(true); w.focus(); }
};
```

```tsx
{/* 버튼 영역 - WeRU.B 추가, OHIF 유지 */}
<div className="flex gap-2">
  {/* WeRU.B 뷰어 (기본, 강조) */}
  <button onClick={openWerubViewer}
    className="bg-blue-600 text-white px-6 py-2.5 rounded-lg font-semibold
               hover:bg-blue-700 shadow transition flex items-center gap-2">
    {viewerOpened ? '🖥️ WeRU.B 뷰어 다시 열기' : '🖥️ WeRU.B 뷰어 열기'}
  </button>

  {/* OHIF 뷰어 (보조, 기존 유지) */}
  <button onClick={openOhifViewer}
    className="bg-gray-100 text-gray-700 px-4 py-2.5 rounded-lg font-medium
               border hover:bg-gray-200 transition text-sm flex items-center gap-2">
    🔬 OHIF 뷰어 열기
  </button>

  {/* 단일 화면 모드 (기존 유지) */}
  <a href={`/pacs-admin/reading/view?study=${studyUID}&mode=single`}
    className="bg-white text-gray-700 px-4 py-2.5 rounded-lg font-medium
               border hover:bg-gray-50 transition text-sm">
    단일 화면 모드
  </a>
</div>
```

### 3.2 헤더 (`layout.tsx`)

**변경 전**: `뷰어 ↗` (1개 링크)

**변경 후**: `WeRU.B ↗` `OHIF ↗` (2개 링크, 기존 유지)

```tsx
<a href="/werub-viewer/" target="_blank"
   className="text-xs sm:text-sm bg-blue-600 text-white px-2 sm:px-3 py-1 rounded hover:bg-blue-700">
  WeRU.B ↗
</a>
<a href="/viewer/" target="_blank"
   className="text-xs sm:text-sm bg-gray-100 text-gray-700 px-2 sm:px-3 py-1 rounded hover:bg-gray-200">
  OHIF ↗
</a>
```

---

## 4. WeRU.B Viewer 빌드 (신규 생성)

### 4.1 디렉토리 구조

```
openpacs/
├── werub-viewer/                       # 🆕 전체 신규
│   ├── Dockerfile                      # Nginx + 정적 파일 서빙
│   ├── nginx.conf                      # SPA 라우팅 설정
│   ├── build.sh                        # OHIF 클론 → 커스터마이징 → 빌드
│   ├── LICENSE                         # OHIF MIT + WeRU.B 저작권
│   │
│   ├── config/
│   │   └── werub-app-config.js         # DICOMweb + 브랜딩 설정
│   │
│   ├── branding/
│   │   ├── werub-logo.svg              # 뷰어 헤더 로고
│   │   ├── werub-logo-dark.svg         # 다크 모드 로고
│   │   ├── werub-favicon.ico           # 파비콘
│   │   ├── werub-favicon-16.png
│   │   ├── werub-favicon-32.png
│   │   └── werub-apple-touch.png       # iOS 아이콘
│   │
│   ├── i18n/
│   │   └── ko-KR.json                  # 한국어 번역 (OHIF→WeRU.B 치환)
│   │
│   └── extensions/
│       ├── ai-panel.js                 # AI 추론 패널
│       └── report-panel.js             # 판독 리포트 패널
│
├── admin/                              # 기존 (버튼 추가만)
├── docker-compose.yml                  # werub-viewer 서비스 추가
│
│   ⚠️ 아래는 수정하지 않음
├── (기존 OHIF 이미지: openpacs-ohif-kr)  # 변경 금지
└── (기존 /viewer/ 경로)                  # 변경 금지
```

### 4.2 app-config.js (WeRU.B 전용)

```javascript
// werub-viewer/config/werub-app-config.js
// 기존 OHIF app-config.js와 완전 별도 파일

window.config = {
  routerBasename: '/werub-viewer',

  // WeRU.B 브랜딩
  whiteLabeling: {
    createLogoComponentFn: function(React) {
      return React.createElement('div', {
        style: { display: 'flex', alignItems: 'center', gap: '8px' }
      },
        React.createElement('img', {
          src: '/werub-viewer/werub-logo.svg',
          alt: 'WeRU.B',
          style: { height: '28px' }
        }),
        React.createElement('span', {
          style: { color: '#fff', fontSize: '16px', fontWeight: 'bold' }
        }, 'WeRU.B Viewer')
      );
    },
  },

  language: 'ko-KR',
  showStudyList: true,
  investigationalUseDialog: { option: 'never' },
  showPatientInfo: 'visible',
  showErrorDetails: 'always',
  maxNumberOfWebWorkers: 3,

  // DICOMweb — 기존 OHIF와 동일한 Orthanc 백엔드를 공유
  defaultDataSourceName: 'dicomweb',
  dataSources: [
    {
      namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
      sourceName: 'dicomweb',
      configuration: {
        friendlyName: 'WeRU.B PACS',
        name: 'orthanc',
        wadoUriRoot: '/wado',
        qidoRoot: '/dicom-web',
        wadoRoot: '/dicom-web',
        qidoSupportsIncludeField: false,
        supportsReject: false,
        dicomUploadEnabled: true,
        imageRendering: 'wadors',
        thumbnailRendering: 'wadors',
        enableStudyLazyLoad: true,
        supportsFuzzyMatching: false,
        supportsWildcard: true,
        omitQuotationForMultipartRequest: true,
        bulkDataURI: { enabled: true, relativeResolution: 'studies' },
      },
    },
  ],

  customizationService: {
    'ohif.overlayItem': {
      topLeft: ['PatientName', 'PatientID', 'PatientBirthDate'],
      topRight: ['InstitutionName', 'StudyDate', 'StudyTime', 'StudyDescription'],
      bottomLeft: ['SeriesNumber', 'SeriesDescription', 'InstanceNumber'],
      bottomRight: ['WindowLevel', 'Zoom', 'SliceLocation'],
    },
  },

  hotkeys: [
    { commandName: 'incrementActiveViewport', label: '다음 뷰포트', keys: ['right'] },
    { commandName: 'decrementActiveViewport', label: '이전 뷰포트', keys: ['left'] },
    { commandName: 'rotateViewportCW', label: '시계방향 회전', keys: ['r'] },
    { commandName: 'flipViewportHorizontal', label: '좌우반전', keys: ['h'] },
    { commandName: 'flipViewportVertical', label: '상하반전', keys: ['v'] },
    { commandName: 'resetViewport', label: '초기화', keys: ['space'] },
    { commandName: 'toggleCine', label: '동영상', keys: ['c'] },
    { commandName: 'invertViewport', label: '반전', keys: ['i'] },
  ],
};
```

### 4.3 빌드 스크립트

```bash
#!/bin/bash
# werub-viewer/build.sh
set -e

OHIF_VERSION="v3.9.0"
BUILD_DIR="$(dirname "$0")"

echo "=== WeRU.B Viewer Build ==="
echo "OHIF base: $OHIF_VERSION"

# 1. OHIF 소스 클론 (별도 디렉토리, 기존 OHIF과 무관)
if [ ! -d "$BUILD_DIR/.ohif-src" ]; then
  git clone --depth 1 --branch $OHIF_VERSION \
    https://github.com/OHIF/Viewers.git "$BUILD_DIR/.ohif-src"
fi
cd "$BUILD_DIR/.ohif-src"

# 2. WeRU.B 브랜딩 에셋 복사
cp "$BUILD_DIR/branding/"* platform/app/public/
cp "$BUILD_DIR/config/werub-app-config.js" platform/app/public/config/default.js

# 3. 한국어 번역 복사
mkdir -p platform/app/public/locales/ko-KR/
cp "$BUILD_DIR/i18n/ko-KR.json" platform/app/public/locales/ko-KR/translation.json

# 4. Extension 복사
cp "$BUILD_DIR/extensions/"* platform/app/public/

# 5. HTML 타이틀 변경
find platform/app -name "*.html" -exec \
  sed -i '' 's/<title>OHIF Viewer<\/title>/<title>WeRU.B Viewer<\/title>/g' {} +

# 6. 빌드
yarn install --frozen-lockfile
QUICK_BUILD=true PUBLIC_URL=/werub-viewer/ yarn build

# 7. 빌드 결과물 복사
cp -r platform/app/dist "$BUILD_DIR/dist"

echo "=== Build complete: $BUILD_DIR/dist ==="
```

### 4.4 Dockerfile

```dockerfile
# werub-viewer/Dockerfile
FROM nginx:1.24-alpine

# 빌드된 정적 파일 복사
COPY dist/ /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 라이선스 파일
COPY LICENSE /usr/share/nginx/html/LICENSE

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### 4.5 Nginx 설정 (컨테이너 내부)

```nginx
# werub-viewer/nginx.conf
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    # SPA 라우팅 — 모든 경로를 index.html로
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 캐싱
    location ~* \.(js|css|png|svg|ico|woff2?)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

### 4.6 LICENSE 파일

```
WeRU.B Viewer
Copyright (c) 2026 WeRU.B Inc.

Based on OHIF Viewer (https://ohif.org)
Copyright (c) 2018 Open Health Imaging Foundation

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 5. 서버 설정 (추가만, 기존 변경 없음)

### 5.1 docker-compose.yml (추가)

```yaml
  # 🆕 WeRU.B Viewer (OHIF 기반 리브랜딩, 별도 컨테이너)
  werub-viewer:
    build:
      context: /home/deploy/openpacs/werub-viewer
      dockerfile: Dockerfile
    container_name: openpacs-werub
    restart: unless-stopped
    ports:
      - "127.0.0.1:3004:80"

  # ⚠️ 기존 OHIF — 변경 없음
  # ohif:
  #   image: openpacs-ohif-kr:latest
  #   container_name: openpacs-ohif
  #   restart: unless-stopped
  #   ports:
  #     - "127.0.0.1:3001:80"
```

### 5.2 Nginx (추가 location 블록만)

```nginx
# 🆕 WeRU.B Viewer — 신규 추가
location /werub-viewer/ {
    proxy_pass http://127.0.0.1:3004/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# ⚠️ 기존 OHIF Viewer — 변경 없음
# location /viewer/ {
#     proxy_pass http://127.0.0.1:3001/;
#     ...
# }
```

---

## 6. 브랜딩 에셋

### 6.1 필요 파일

| 파일 | 용도 | 크기 | 비고 |
|------|------|------|------|
| `werub-logo.svg` | 뷰어 헤더 (어두운 배경) | 28px 높이 | 흰색/밝은색 |
| `werub-logo-dark.svg` | 밝은 배경용 | 28px 높이 | 어두운색 |
| `werub-favicon.ico` | 브라우저 탭 | 32×32 | Multi-size |
| `werub-favicon-16.png` | 작은 아이콘 | 16×16 | PNG |
| `werub-favicon-32.png` | 일반 아이콘 | 32×32 | PNG |
| `werub-apple-touch.png` | iOS 홈 화면 | 180×180 | PNG |

### 6.2 색상 테마

| 요소 | OHIF 기본 | WeRU.B |
|------|----------|--------|
| Primary | `#5ACCE6` | `#2563EB` (Admin과 통일) |
| Header BG | `#000000` | `#1E293B` |
| Accent | `#5ACCE6` | `#3B82F6` |

---

## 7. 충돌 방지 체크리스트

| # | 확인 항목 | 검증 방법 |
|---|----------|----------|
| 1 | OHIF 컨테이너 이미지 변경 없음 | `docker images` 해시 비교 |
| 2 | OHIF app-config.js 변경 없음 | `docker exec openpacs-ohif cat /usr/share/nginx/html/app-config.js` |
| 3 | `/viewer/` 접근 시 OHIF 원본 동작 | 브라우저 테스트 |
| 4 | `/werub-viewer/` 접근 시 WeRU.B 동작 | 브라우저 테스트 |
| 5 | 두 뷰어 동시 열기 시 충돌 없음 | 같은 스터디를 양쪽에서 열기 |
| 6 | DICOMweb 데이터 동일 | 양쪽 뷰어에서 같은 스터디 목록 확인 |
| 7 | Admin에서 OHIF 버튼 기존과 동일 동작 | 기존 OHIF 버튼 클릭 테스트 |
| 8 | Admin에서 WeRU.B 버튼 정상 동작 | 신규 WeRU.B 버튼 클릭 테스트 |
| 9 | OHIF 컨테이너 재시작 시 WeRU.B 영향 없음 | `docker restart openpacs-ohif` |
| 10 | WeRU.B 컨테이너 재시작 시 OHIF 영향 없음 | `docker restart openpacs-werub` |

---

## 8. 일정

| 작업 | 일수 | 기존 영향 |
|------|:----:|:---------:|
| 브랜딩 에셋 제작 (로고, 파비콘) | 1일 | ❌ 없음 |
| OHIF 소스 클론 → WeRU.B 빌드 환경 구성 | 1일 | ❌ 없음 |
| werub-app-config.js + 한국어 번역 | 1일 | ❌ 없음 |
| Docker 이미지 빌드 + 서버 배포 | 1일 | ❌ 없음 |
| Nginx 프록시 추가 (location 블록만) | 0.5일 | ❌ 없음 |
| Admin Dashboard 버튼 추가 | 0.5일 | ❌ 기존 버튼 유지 |
| 충돌 방지 체크리스트 검증 (10항목) | 1일 | ❌ 없음 |
| **합계** | **6일** | **기존 시스템 영향 제로** |

---

**작성**: Claude Code  
**핵심**: 기존 OHIF 일체 수정 없음. WeRU.B는 별도 빌드 + 별도 컨테이너 + 별도 경로.  
**다음 단계**: 로고 에셋 준비 → OHIF 소스 클론 → WeRU.B 빌드 → 배포
