# DICOM 기술 동향 검토 + 코드 대조 (2026-07)

> 방식: 최신 DICOM 표준/생태계 변화 조사 → OpenPACS 구현과 대조 → **실제 갭만** 추림
> (프로젝트 "트렌드조사→코드대조로 과투자 방지" 방식, cf. `market-trends-gap-2026.md`).
> 기준: DICOM 2025a~2025e 에디션, WG-26/WG-27 진행분.

## A. 이미 충족 (강점 — 재투자 불요)
| 표준/기능 | OpenPACS |
|---|---|
| DICOMweb QIDO/WADO/STOW-RS | ✅ + 인증 표준 passthrough `/rs/*`(v13.19) |
| 고전 DIMSE MWL/MPPS + HL7 ORM 워크리스트 | ✅ `mwl_scp.py` + LIS HL7 ORM→worklist(v13.19, 취소 CA 포함) |
| SR(TID 1500) + SEG | ✅ highdicom 0.27.0 |
| WSI(Sup 145 VL Whole Slide Microscopy) | ✅ 뷰어 microscopy 모드(v13.19 렌더 검증) |
| J2K 전송 압축(3×) | ✅ 저장 무압축(Explicit VR LE)+delivery 4.90 transcoding |
| 병리 주석 **표시**(Sup 222 계열) | 🟡 뷰어 `DicomMicroscopyANN` 핸들러(표시만, 생성 없음) |

## B. 실제 갭 — 신규 표준(2025~), 수요 시 고려
| # | 표준 | 내용 | OpenPACS | 관련성/게이트 |
|---|---|---|---|---|
| **G1** | **Sup 222 — Microscopy Bulk Annotations** (WG-26) | 계산병리 AI 출력(슬라이드당 수백만 주석: point/polyline/polygon/ellipse/seg mask) 저장·교환 표준 | ✅ **완료(v13.19, 커밋 dc743fc)** — 뷰어 표시 O + **백엔드 생성 신설** | ★신규 병리/AI 트랙 직결. `services/microscopy_annotation`(highdicom hdann)+`POST /api/v1/pathology/{uid}/annotations`. 라이브: ANN SOPClass …91.1/2그룹, WSI study에 SM+ANN. 병리 write RBAC |
| **G2** | **Sup 246 — DICOMweb Modality Services (UPS-RS)** (Final Text 2025) | DIMSE MWL/MPPS의 **웹 네이티브 후계**(HTTP `/workitems` 워크리스트·상태·이벤트) | 고전 DIMSE MWL만 | 모더나이제이션. **현 고전 MWL이 LIS로 실증 동작**하므로 저긴급. 벤더 UPS-RS 채택률 낮음(2025 대부분 부분/미지원, 하이브리드 상용) |
| **G3** | **Sup 172 — Parametric Map** | AI 연속값 출력(확률·히트맵·SUV 등) DICOM IOD | SEG/SR만(이산) | AI 히트맵/신뢰도맵. highdicom 지원. SEG/SR가 대부분 커버 → LOW-MED |
| **G4** | **SEG 압축**(2025a) | 세그멘테이션 픽셀 압축 | 무압축 SEG | 저장 최적화, 경미 |

## C. 결정됨/무수요 (조치 불요)
- **HTJ2K(Sup 235)** — Orthanc/DCMTK/GDCM **여전히 미지원**(확인). 프로젝트 **C1 측정 PoC→NO-GO**
  (콜드오픈 첫영상 339ms 이미 빠름). 재개 트리거: OpenJPH 코덱 Orthanc 편입 or 대용량 CT 콜드 체감병목.
- **STL 캡슐화(Sup 205)** — 3D 프린팅 모델. 무수요(클라이언트 3D VRT는 있음, DICOM STL 불요).
- Fetal US 리포트·구조심장 템플릿·waveform PS 등 — 도메인 외.

## 권장 (요약)
1. **G1(Microscopy Bulk Annotations)만 주시** — 신규 병리(LIS)+AI(트윈) 트랙이 **계산병리 AI로 확장되면**
   결과 저장 정본이 이것. 지금은 수요 게이트(병리 AI 모델 도입 시 highdicom로 소규모 구현).
2. **G2~G4는 현행 유지** — 고전 MWL·SEG/SR가 실동작, UPS-RS는 생태계 채택 미성숙, 파라메트릭맵/STL/SEG압축은
   수요·최적화 게이트. HTJ2K는 NO-GO 유지.
3. **highdicom 라이브러리는 이미 G1·G3 지원** — 필요 시 라이브러리 교체 없이 사용만.

**결론: DICOM 기본기는 최신 대비 견고. 유일한 "지켜볼" 항목 = 계산병리 AI 도입 시 Sup 222(G1).**
그 외는 이미 충족이거나 수요/생태계 게이트 — 선제 투자 불요.

## 출처
- [DICOM News/Progress](https://www.dicomstandard.org/news-dir/progress/index.html) · [DICOM WSI](https://dicom.nema.org/dicom/dicomwsi/)
- [Sup 222 Microscopy Bulk Annotations](https://www.dicomstandard.org/docs/librariesprovider2/dicomdocuments/sup222_pc_wsiannotations88f52878-287c-4356-b3bb-72dbbb1dad89.pdf)
- [Sup 246 DICOMweb Modality Services (UPS-RS)](https://www.dicomstandard.org/news-dir/current/docs/sups/sup246-slides.pdf) · [UPS-RS](https://www.dicomstandard.org/using/dicomweb/workflow-ups-rs/)
- [Sup 235 HTJ2K](https://www.dicomstandard.org/News-dir/ftsup/docs/sups/sup235.pdf) · [Sup 172 Parametric Map](https://www.dicomstandard.org/News-dir/ftsup/docs/sups/sup172.pdf)
- [Evolving role of DICOM in digital pathology (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC13142108/)
