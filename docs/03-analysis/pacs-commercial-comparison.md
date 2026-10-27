# WeRU.B PACS vs 상용 PACS — 기능 비교

**작성일**: 2026-06-06
**대상**: WeRU.B PACS(본 제품) vs 글로벌·국내 상용 PACS
**기준 상용 제품**: Sectra(KLAS 2025 1위 91.0), Fujifilm Synapse(84.9), GE Centricity(63.1), **INFINITT(국내 1위, 서울)**
**근거**: WeRU.B 실제 구현(CLAUDE.md + 2026-06 검토) + 상용 공개자료 리서치

---

## 0. 한눈에 — 포지셔닝

| | WeRU.B PACS | 글로벌 상용(Sectra/Fujifilm) | 국내 상용(INFINITT) |
|---|---|---|---|
| **본질** | 오픈소스 기반 웹 PACS(중소병원·클리닉) | 엔터프라이즈 통합영상(대형병원) | 엔터프라이즈+클라우드(국내 표준) |
| **강점** | 저비용·웹네이티브·비표준검증·AI표준화·한국화 | 성숙도·3D·엔터프라이즈·규제이력 | 국내 워크플로·AI마켓·인증 |
| **약점** | 신생·단일기관·규제미인증·엔터프라이즈 기능 | 고비용·도입복잡·종속 | 고비용·thick client 잔존 |

> 결론: WeRU.B는 **"중소 규모 + 저비용 + 웹 + 비표준 영상 안전성 + 한국 AI 표준화"** 틈새에서 경쟁력. 대형병원 엔터프라이즈(VNA·다과목·규제이력)는 상용 우위.

---

## 1. 기능 상세 비교표

| 영역 | 기능 | WeRU.B | 상용(글로벌) | 상용(INFINITT) |
|---|---|:---:|:---:|:---:|
| **아키텍처** | 웹 제로풋프린트 뷰어 | ✅ (OHIF/Cornerstone3D) | ✅ | ✅ (일부 thick 잔존) |
| | Docker/컨테이너 배포 | ✅ | 부분 | 부분 |
| | 오픈소스 기반 | ✅ (Orthanc/OHIF) | ❌ 독점 | ❌ 독점 |
| **DICOM** | DIMSE(C-STORE/FIND/MOVE/ECHO) | ✅ | ✅ | ✅ |
| | DICOMweb(QIDO/WADO/STOW) | ✅ | ✅ | ✅ |
| | **MWL SCP**(촬영실 워크리스트) | ✅ **구현(pynetdicom SCP, 2026-06-06)** | ✅ | ✅ |
| | **MPPS**(촬영 수행 단계) | ✅ **구현(N-CREATE/N-SET SCP, 2026-06-06)** | ✅ | ✅ |
| | **Storage Commitment** | ✅ **구현(N-ACTION/N-EVENT-REPORT, 2026-06-06)** | ✅ | ✅ |
| | 적합성 선언문(PS3.2) | ✅ v1.2 | ✅ | ✅ |
| | **비표준 DICOM 검증·정규화** | ✅ **22규칙·JPEG밀도** ⭐ | △ 제한적 | △ 제한적 |
| **뷰어** | 2D/W·L/측정 | ✅ | ✅ | ✅ |
| | MPR/MIP | ✅ | ✅ | ✅ |
| | 3D VRT(볼륨렌더) | △ 엔진보유, 임상튜닝 미완 | ✅ **성숙(fusion·혈관분석)** | ✅ |
| | Hanging Protocol | ✅ (기본+MG자동) | ✅ 고도 | ✅ 고도 |
| | 멀티모니터/판독 UX | ✅ | ✅ 성숙 | ✅ |
| **AI** | AI 추론 연동 | ✅ 29모델·5파이프라인 | ✅ AI마켓 | ✅ AI마켓(Lunit/Vuno) |
| | **AI결과 DICOM표준(TID1500 SR/SEG)** | ✅ **highdicom 실구현** ⭐ | △ 벤더별 | △ |
| | 온프렘+클라우드 하이브리드 | ✅ (GPU폴백) | 부분 | ✅ 클라우드 |
| **판독** | 구조화 리포트/템플릿/매크로 | ✅ | ✅ | ✅ |
| | 음성인식 | △ 입력 인터페이스 | ✅ (Nuance 등) | ✅ |
| | 예비판독·협진·세컨드오피니언 | ✅ | ✅ | ✅ |
| **표준연동** | FHIR R4 | ✅ | ✅ | ✅ |
| | HL7 v2 / HIS·RIS | ✅ **MLLP 리스너(ORM→worklist→MWL, ADT, ACK/ORU), 2026-06** + JWT SSO·API | ✅ 완전 | ✅ 완전 |
| | IHE 프로파일(SWF/XDS-I) | △ 핵심만 | ✅ 전체 | ✅ |
| **수집/QC** | **영상 수집 허브(환자포털·키오스크)** | ✅ ⭐ | △ | △ |
| | Study 병합/분리 QC | ✅ | ✅ | ✅ |
| | **DICOM 이슈 컨트롤 센터** | ✅ ⭐ | △ | △ |
| | 익명화(PS3.15) | ✅ | ✅ | ✅ |
| **엔터프라이즈** | 다중기관/멀티테넌시 | ❌ v2.0 | ✅ | ✅ |
| | VNA(벤더중립아카이브) | ❌ | ✅ | ✅ |
| | 다과목(심장·병리·안과) | ❌ 영상의학 | ✅ | ✅ |
| **보안/규제** | 보안(JWT/RBAC/암호화/BtG) | ✅ | ✅ | ✅ |
| | 한국화(UI/코드/의료법) | ✅ **한국우선** | △ 현지화 | ✅ |
| | 규제 인증 | △ MFDS Class2 **준비중** | ✅ FDA/CE | ✅ FDA510k/MFDS |
| | 설치기반/트랙레코드 | ❌ 신생 | ✅ 광범위 | ✅ 국내광범위 |
| **비용** | 라이선스 | ✅ **오픈소스·저비용** ⭐ | ❌ 고가 | ❌ 고가 |

⭐ = WeRU.B 차별/우위 · △ = 부분/제한 · ❌ = 미지원

---

## 2. WeRU.B 차별점 (상용 대비 우위)

1. **비표준 DICOM 안전성** ⭐ — JPEG 밀도(DPI) vs Pixel Spacing 교차검증 등 22규칙 자동 검증·정규화. 상용은 대부분 "표준 입력 가정" → **측정 오류 위험을 본 제품이 선제 차단**. 실무 유입 비표준 영상이 많은 중소 환경의 핵심 가치.
2. **AI 결과 국제표준 인코딩** ⭐ — AI 판독을 TID 1500 SR + SEG(highdicom)로 저장 → 벤더 종속 없는 상호운용. 상용은 벤더별 포맷이 흔함.
3. **영상 수집 허브** ⭐ — 환자 셀프 업로드(토큰), 키오스크, 외부 PACS Q/R, 승인 큐 — 외부 영상 유입이 잦은 클리닉 워크플로 내장.
4. **DICOM 이슈 컨트롤 센터** ⭐ — 검증 규칙·모달리티 렌더링·에러 메시지 관리자 커스터마이즈.
5. **저비용·웹네이티브·오픈소스** — 라이선스 부담 없이 Docker로 자가호스팅. 중소 병원/클리닉 도입 장벽↓.
6. **한국 우선 설계** — UI/날짜/환자명 한국어, KCD/EDI 코드, 의료법·개인정보보호법.

---

## 3. WeRU.B 갭 (상용 대비 열위 — 정직)

1. **3D 임상 성숙도** — VRT 엔진은 보유하나 fusion(PET/CT)·혈관분석·curved MPR 등 고급 3D는 미구현. 상용(특히 Philips/Sectra)이 강함.
2. **엔터프라이즈 규모** — 단일기관(v1.0). 다중기관·VNA·다과목(심장/병리/안과)은 상용 우위.
3. **워크플로 표준** — **MWL + MPPS + Storage Commitment 3종 구현 완료(2026-06-06)**. DIMSE 워크플로 표준 격차 해소(상용 동등). RIS 통합 격차 대부분 해소.
4. **규제 인증·트랙레코드** — MFDS Class 2 준비중(미인증). 상용은 FDA 510(k)/CE/MFDS 보유 + 광범위 설치기반·검증 이력.
5. **음성인식/고급 판독 도구** — 상용의 성숙한 dictation(Nuance) 대비 인터페이스 수준.
6. **지원·SLA** — 상용 벤더의 24/7 지원·교육 대비 신생.

---

## 4. 권장 포지셔닝 / 다음 단계

- **타깃**: 중소 병원·클리닉, 비표준 영상 유입 많은 환경, AI 표준화·저비용 중시 기관.
- **단기 경쟁력 강화**: ① MFDS 인증 완료(트랙레코드 확보), ② 3D 임상 튜닝(전용 HP·VR 프리셋), ③ MWL SCP(촬영실 워크플로 표준).
- **차별화 유지·강조**: 비표준 검증·정규화, AI 표준 인코딩, 수집 허브 — 마케팅 핵심 메시지.
- **장기**: 다중기관(v2.0)·VNA로 엔터프라이즈 진입.

---

## 참고 (Sources)
- [KLAS PACS Comparison 2025 (IntuitionLabs)](https://intuitionlabs.ai/articles/enterprise-pacs-klas-comparison)
- [Sectra PACS 2025 Overview (Taloflow)](https://www.taloflow.ai/guides/products/sectrapacs)
- [Fujifilm Synapse vs Sectra (Taloflow)](https://www.taloflow.ai/guides/comparisons/fujifilmsynapse-vs-sectrapacs-medical-imaging)
- [INFINITT PACS 7.0 FDA 510(k) K172803](https://510k.innolitics.com/device/K172803)
- [INFINITT AI Solutions](https://www.infinitt.com/product.php?ctr=g_eng&solution=Artificial+Intelligence)
- [Top performing PACS companies (Radiology Business)](https://radiologybusiness.com/topics/health-it/enterprise-imaging/pacs/top-performing-pacs-companies-based-user-feedback)
