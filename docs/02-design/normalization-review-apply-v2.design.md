# 설계 노트 — 정규화 검토 "승인=적용" (v2)

**작성**: 2026-06-29 (감사 그룹2 P5 후속)
**상태**: 설계 정의(미착수). 구현 전 선결 조건(§5·§1) 충족 필요.
**배경**: v13.10에서 정규화 검토 큐(`/api/v1/batch/reviews`)를 **결정 기록**까지 구현. 승인 시 medium-risk
DICOM 변경의 **실제 적용**은 데이터/검증 한계로 v2로 분리(아래 §0).

---

## 0. 왜 v2로 미뤘나 (현실 제약, 실측)
- medium-risk 변경은 정규화 시 **미적용 'defer' 보류**(safe만 자동적용) → "승인"이 의미하려면 ingested
  study에 DICOM 재적용 필요.
- 그러나 구현 전 실측에서:
  1. 기존 `reviewed_changes`가 **요약 dict**(`{charset_fixed, missing_tags_added, pixel_spacing_corrected}`)
     — 태그별 적용 목록 없음.
  2. `decision` 리터럴 불일치(데이터 `approved/deferred` vs 코드 `approve/defer`).
  3. batch 정규화 기능 **미운영**(2026-05-14 데모, 완료 배치 0) → apply 검증할 실 런 부재.
  → 형식 표준화 + 실 배치 골든 데이터 확보가 선결.

---

## 1. change 형식 표준화 (선결) — ✅ Step A 완료 (2026-06-29)
**실측 결과**: 적용 경로(batch task → `normalizer_engine` → `supplier_normalizer`)의 change는 **이미 적용가능**
(`NormalizationChange.tag="0028,0030"` clean + `corrected` 새값, engine에 `_apply_change_to_dicom`/`_guess_vr_for_tag` 보유).
표시문자열 tag는 `normalization_settings.py`의 *분석 표시* 경로일 뿐 apply 경로 아님.
**Step A 구현**: ① `supplier_normalizer.CHANGE_SCHEMA_VERSION=1` + `is_applicable_change()`(캐논 태그 `GGGG,EEEE`
+ corrected 존재 검증, 레거시 요약dict/표시문자열=False) + 스키마 docstring(단일 출처) ② batch task가
`reviewed_changes={"schema_version":1,"changes":[...]}` 버전 엔벨로프로 저장(레거시 구분) ③ `/batch/reviews`가
각 항목에 `applicable`·`schema_version` 노출. 라이브 입증(캐논 리뷰→applicable=true·schema_version=1) + 검증자
단위테스트 5케이스. **Step C는 `applicable=true`만 적용 대상**으로 게이트.

**(참고) 원래 문제 정의**: 생산자마다 `tag` 형식이 다름.
- `services/supplier_normalizer.py`: `tag="0028,0030"` (적용 가능, GGGG,EEEE).
- `services/normalizer_engine.py`·`api/normalization_settings.py`: `"SpecificCharacterSet (0008,0005)"`,
  `"PixelSpacing (0028,0030) vs ImagerPixelSpacing (0018,1164)"` (표시 문자열, **적용 불가**).

**정의할 캐논 스키마** (NormalizationReview.reviewed_changes.changes[]):
```jsonc
{
  "tag": "0028,0030",          // GGGG,EEEE — 적용 대상 태그(필수, 기계적용용)
  "vr": "DS",                  // Value Representation
  "level": "instance",         // instance | series | study (적용 범위)
  "new_value": "0.143\\0.143", // 적용할 값(필수)
  "original": "0.2\\0.2",      // 표시/감사용
  "display": "PixelSpacing 정합성", // 사람용 라벨(적용과 분리)
  "rationale": "...", "risk_level": "medium"
}
```
- 표시 문자열과 **적용 스펙(tag/vr/level/new_value) 분리**.
- 기존 reviewed_changes는 schema_version 부여 + 마이그레이션(또는 구버전=apply 불가로 명시 거부).
- normalizer_engine/normalization_settings 출력도 이 스키마로 정렬(현재 표시문자열 producer 수정).

---

## 2~3. 적용 경로·UID 보존 — ✅ Step C 완료 (2026-06-29)
**구현**: `POST /batch/reviews/{id}` decision=approve → `applicable=true`(캐논) 변경만
`app/services/normalization_apply.apply_canonical_changes`로 SOP 인스턴스에 **in-place 적용**
(SOPInstanceUID 유지) + 원본 바이트를 `DicomFixHistory.original_data`에 백업.
**★드리프트 회피**: 서버는 `dicom_issues`를 **단일파일**(`dicom_issues.py`)로, repo는 패키지로 운영(메모리
드리프트). fix.py에 어댑터를 넣으면 서버가 import 못 함(`from app.api.dicom_issues.fix import …` 실패) →
**신규 공유 모듈 `app/services/normalization_apply.py`**(양쪽 동일 배포)에 둠. fix.py 의존 안 함.
**롤백 무료**: 어댑터가 DicomFixHistory 행을 쓰므로 서버의 기존 dicom_issues `rollback_fix`(K1 original_data
복원, 행 단위라 단일파일/패키지 무관)가 그대로 되돌림.
**라이브 입증**(throwaway 합성 인스턴스): 승인→Orthanc StudyDescription "ORIG"→"STEPC_APPLIED"(in-place)
→ `/dicom-issues/rollback/{id}`→"ORIG" 복원(restored:true). E2E 19-audit 17/17. ReviewRoles `allow_btg=False`(적용은 파괴적).
**E ✅ 완료**: 감사강화(`decide_review`→`NORMALIZATION_REVIEW_DECIDED` audit: decision/applied/fix_history_id) +
통합테스트 자동화 `scripts/server/it-normalization-apply.sh`(합성 SOP→승인→적용검증→롤백→복원검증→정리, 서버 실행 PASS).
**F ✅ 완료**: reviews 페이지에 `applicable` 배지("승인 시 자동 적용"/"기록만") + 승인 토스트에 적용 결과(태그 N개)·
롤백 안내(DICOM 이슈 이력). 롤백 UI는 기존 dicom-issues fix-history(NORMALIZATION_REVIEW 행)가 제공.
**D(비동기) 보류**: 현재 동기 적용 — 리뷰=1 SOP라 충분. 대량/study-레벨 다수 인스턴스 시에만 celery로 전환(선택).
**→ v2 정규화 승인=적용 트랙 사실상 완결**(A~C 구현+E·F 보강, D는 수요 주도).

### (원안) 2. 적용 경로 — ★핵심 결정: 기존 fix 파이프라인 재사용
**이미 검증된 기계**: `api/dicom_issues/fix.py`
- `_apply_supplier_normalizer(ds, norm_result)` — pydicom Dataset에 SupplierNormalizer 변경 적용(이미 bridge).
- `original_data` BYTEA 백업(line ~502) + **실복원 롤백**(v12.8 K1 — 통째 비작동이던 것을 수정해 입증).
- pydicom write 기반 **in-place 재저장**(UID 유지).

**권장**: 검토 승인 시 **이 파이프라인을 호출**(평행 Orthanc `/modify` 경로 신설 금지).
- 이유: ③ UID 보존 / ⑥ 롤백·감사가 **무료로 따라옴**. 평행 경로 신설은 K1(원본 영구소실) 위험 재발.
- 구현 형태: `decide_review(approve)` → reviewed_changes(캐논 스키마)를 fix.py의 apply 함수가 받는 형태로
  변환 → SOPInstanceUID로 인스턴스 패치 → original_data 백업 → 재저장. (per-SOP cascade와 동일 루틴.)

**대안(비권장)**: Orthanc `/studies|instances/{id}/modify` 직접 — 신규 UID 생성으로 참조 깨짐(③ 참조).

---

## 3. 적용 대상·UID 보존 (의료기록 연속성)
- **대상 식별**: `BatchJobFile.sop_instance_uid`(+study/series) → ingested 인스턴스. **staleness 처리**:
  이미 수정/삭제/이동(merge/anonymize/다른 review) 시 적용 거부 + 명확한 사유(409/충돌).
- ★**UID 보존**: 적용 후 SOP/Study/SeriesInstanceUID **유지**(report·prior·KOS 참조 불변). →
  pydicom in-place 재저장(fix.py 방식). Orthanc /modify의 신규UID 생성은 금지.
- **level별 적용**: instance(PixelSpacing/W-L), series, study(PatientName/StudyDate/AccessionNumber).
  study/series 레벨은 대상 인스턴스 전체에 일괄 — fix.py cascade 재사용.

---

## 4. 워크플로·동기성
- **비동기 권장**: 승인 → celery 태스크(배치 진행 WS `batch_progress` 재사용) — 한 review에 여러 change·
  study 레벨은 다수 인스턴스라 동기 응답 부적합.
- **상태 전이**: defer → (approve) → applying → applied / apply_failed. (reject는 즉시 종료, 적용 없음.)
  현재 모델 `decision`은 approve/reject/defer만 → applied/apply_failed/applying 상태 컬럼 추가 정의.
- **원자성**: review 단위 all-or-nothing(부분 실패 시 그 review의 적용분 롤백) vs per-change. 권장 all-or-nothing.
- 멱등: 재승인/재시도 시 이미 applied면 no-op.

---

## 5. 검증 환경 (선결) — ✅ Step B 수행 결과 (2026-06-29)
**★발견 1 — 파이프라인이 미운영이 아니라 고장이었음 → 수정 완료**: batch 업로드 temp dir이 `/tmp`(backend
컨테이너 fs)라 **별도 컨테이너인 celery-worker가 못 읽어 모든 배치가 "Could not load file"로 즉시 실패**
(데모 배치가 stuck/완료0이던 진짜 이유). → `settings.batch_spool_dir`(기존 공유 마운트 `export-staging` 하위)로
변경, backend·worker가 동일 호스트 dir 공유. 실 DICOM 업로드 재현 → **completed·file=stored**(end-to-end 복구).
compose 변경 불요(기존 공유 볼륨 재사용).
**★발견 2 — medium 리뷰는 photometric 설정(기본 off) 활성 시에만 생성**: 모든 medium 변경이
`_is_algorithm_enabled("photometric")` 게이트 아래이고 기본 config `photometric:False`. 즉 **기본 운영에선
medium=0 → 리뷰 큐 항상 비어 Step C(apply) 적용 대상 없음** → Step C는 photometric enable 기관에서만 의미.

**골든 medium 데이터 레시피(Step C 테스트용)**:
1. `normalization_config`에 대상 modality `algorithms.photometric=true` row 삽입(기본 off라 필수).
2. 합성 Siemens DICOM: `Manufacturer(0008,0070)="SIEMENS"` + private `(0019,1010)="MONO"` +
   `PhotometricInterpretation(0028,0004)` **부재**(엔진이 private group 0019 추출→photometric 추론).
3. `POST /batch/normalize/upload` → medium `{tag:"0028,0004", corrected:"MONOCHROME2"}` →
   `NormalizationReview(decision='defer', reviewed_changes={schema_version:1, changes:[...]})`.
4. `/batch/reviews`에서 `applicable=true`(Step A 검증자) 확인 → Step C 적용 대상.
- (Step A에서 동일 캐논 엔벨로프를 SQL 삽입으로 endpoint까지 입증 — applicable=true/schema_version=1.)
- 통합테스트: defer→approve→applied(태그 실변경)·rollback(원본 복원) 입증(IT 패턴, v12.8 K1 선례).

---

## 6. 권한·감사·롤백
- 적용 EP는 파괴적 → `RequireRole(ADMIN, RADIOLOGIST, TECHNOLOGIST, allow_btg=False)`.
- 감사: 적용 전후 태그값 + reviewer + SOP. fix.py의 dicom_fix_history/original_data 재사용.
- 롤백: 적용 review를 되돌리면 original_data로 복원(fix.py rollback 재사용). UI에 롤백 버튼.

---

## 7. 작업 순서(제안)
1. (선결) change 캐논 스키마 정의 + producer 정렬(supplier_normalizer는 OK, engine/settings 수정). §1
2. (선결) 실 배치 1회 운영 → 골든 medium 데이터 확보. §5
3. fix.py apply/backup/rollback을 review-approve에서 호출하는 어댑터(캐논 스키마→pydicom 적용). §2
4. 비동기 태스크 + 상태 전이 + WS 진행. §4
5. 권한/감사/롤백 UI + 통합테스트(apply→rollback 실증). §6
6. 검토 큐 프론트에 적용 상태/롤백 노출.

---

## 부록 — AI 키 회전 (별건, v2 아님 — 운영 절차)
v13.5에서 `normalization_settings.py` 하드코딩 AI 키를 `settings.ai_api_key`로 외부화했으나, **구 키가
git/번들에 이미 노출**됨. 코드 변경 불요 — 운영자 단발 액션:
1. AI 서버(WeRU.B)에서 새 키 발급, 구 키 폐기.
2. 서버 `.env`의 `AI_API_KEY` 교체 → `docker compose restart backend celery-worker celery-beat`(AI 호출 주체).
3. 검증: `/api/v1/ai/server-status` 200.
