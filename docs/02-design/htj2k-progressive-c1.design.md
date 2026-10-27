# C1 — HTJ2K 진성 점진로딩: 설계 & 측정 우선 PoC

**작성**: 2026-07-08
**상태**: **PoC 측정 완료 → NO-GO / 보류 (2026-07-08)**. 서버 인프라 변경 0으로 결정. 아래 §6.
**관련**: `docs/archive/2026-06/progressive-loading/03-progressive-loading.analysis.md`(v11.9 실사),
`docs/01-plan/v2.0-scope-2026.md`(C1 = P1), [[next-work-candidates]](Track B 잔여·게이트)

---

## 0. 요약 — 왜 "측정 먼저"인가

HTJ2K(High-Throughput JPEG 2000, TS `1.2.840.10008.1.2.4.201/202/203`)는 해상도-점진 디코딩으로
대용량 CT 첫 영상을 빠르게 띄운다. 그러나 **본 프로젝트의 실사·정책상 C1은 이미 두 겹으로 게이트됨**:

1. **주 가치는 이미 제공됨** (v11.9): 3D 볼륨(MPR) 점진 로딩은 cornerstone
   `interleavedRetrieveStages`로 **이미 활성**. C1의 *증분* 가치 = ① 2D 스택 per-image 점진 ②
   대용량 CT 단일영상 첫 타일 가속 — 둘 다 부차적.
2. **과거 정책 게이트**: 저해상도-우선 표시(구 Track B)는 "**프리페치 콜드오픈 비중이 클 때만** 착수"로
   보류 확정. SR(초해상)은 "bicubic 업스케일 0.978 유사도 대비 이득 미미"로 기각.

→ HTJ2K는 **OpenJPH 코덱 신설(C++ 빌드·서버 인프라 변경)이라는 큰 투자**인데 증분 가치가 미검증.
따라서 **인프라를 건드리기 전에 오프-서버 측정으로 실이득을 먼저 정량화**하고 go/no-go를 낸다.
이 프로젝트가 반복한 "측정으로 판정"(SR/HTJ2K PoC·VRT 서버렌더 강등과 동일 노선).

---

## 1. 현 상태 (2026-07-08 재확인)

| 항목 | 상태 | 근거 |
|------|------|------|
| Orthanc | 1.12.11 + 플러그인 gdcm·dicom-web·postgresql-index/storage | `/system`·`/plugins` 실조회 |
| GDCM HTJ2K 인코딩 | **불가** | TS 4.201 요청 → 500 (v11.9 실측) |
| 3D 볼륨(MPR) 점진 | **이미 활성** | `interleavedRetrieveStages` 배선 |
| 2D 스택 per-image 점진 | **무효(inert)** | `stackRetrieveOptions`가 HTJ2K 전제인데 Orthanc 미지원 |
| bicubic 업스케일 유사도 | 0.978 (SR 기각 근거) | v11.4 Track B PoC |
| 프리페치 캐시 | nginx proxy_cache(20GB LRU) + Celery prefetch (v11.4) | 콜드오픈 비중 데이터가 C1 게이트 |

---

## 2. HTJ2K 생성 통합 경로 (3안)

브라우저(cornerstone)는 HTJ2K 디코딩을 이미 지원 — **블로커는 서버가 HTJ2K 바이트를 만들지 못하는 것뿐.**

| 안 | 방식 | 규모 | 리스크 | 비고 |
|----|------|:---:|:---:|------|
| **A. Orthanc 트랜스코더 플러그인** | OpenJPH 링크한 C++ 플러그인, on-the-fly TS 협상 | XL | **높음** | 공식 플러그인 없음·C++ 빌드·live Orthanc 재빌드. 블라스트반경 최대 |
| **B. 사전계산 저장(precompute)** | 워커가 저장 인스턴스를 HTJ2K로 트랜스코드(ojph_compress)→별도 표현 보관, WADO-RS로 서빙 | L | 중 | 스토리지 2배·Orthanc는 단일 표현이라 별도 저장/인덱스 필요 |
| **C. 온디맨드 사이드카(권장 PoC 대상)** | WADO-RS frame 요청(HTJ2K TS)을 사이드카가 가로채→Orthanc 원본 fetch→OpenJPH 트랜스코드→캐시(nginx proxy_cache 재사용) | M | **낮음** | Orthanc 무수정. v11.4 프레임 캐시 인프라와 정합. 첫 요청만 트랜스코드 비용 |

**권고**: **안 C(사이드카)** — Orthanc를 건드리지 않아 블라스트반경 최소, 기존 프레임 캐시(v11.4)와
자연 결합. 단 트랜스코드 지연이 프리페치로 상쇄되는지가 관건 → **측정 필요**.

---

## 3. 측정 우선 PoC (서버 인프라 변경 0)

**목표**: HTJ2K의 실이득(첫 타일 표시 시간·체감)을 인프라 투자 전에 정량화.

### PoC 절차 (오프-서버 / 로컬·스테이징)
1. **샘플**: 대표 대용량 CT study 1~3건(예: 500+ 슬라이스, 압축 전 ~250MB) — 콜드오픈 시나리오.
2. **HTJ2K 생성**: OpenJPH `ojph_compress`(CLI, 서버 미설치)로 각 프레임을 HTJ2K로 변환
   (해상도 레벨 5, 무손실/근무손실 2종). **로컬에서만** — live 서버 미변경.
3. **측정 3-way 비교** (동일 뷰어·동일 네트워크):
   - (baseline) 현재: 원본 TS(J2K/무압축) 풀 프레임 → 첫 표시 시간
   - (bicubic) 저해상 썸네일 즉시 + 백그라운드 풀해상 (코덱 불요)
   - (htj2k) HTJ2K 해상도-점진 → 저해상 첫 타일 시간
4. **지표**: `time-to-first-pixel`(첫 표시), `time-to-full-res`, 전송 바이트, 디코드 CPU.
5. **콜드오픈 비중**: `GET /prefetch/stats`로 실제 콜드오픈(캐시 MISS) 비율 확인 — HTJ2K는
   콜드오픈에서만 이득. 프리페치 HIT면 이미 로컬이라 이득 없음.

### Go / No-Go 기준
- **GO(안 C 구현)**: HTJ2K 첫타일이 baseline 대비 **≥40% 단축** AND bicubic 대비 **체감 우위**(bicubic는
  저해상이 흐릿·HTJ2K는 실제 저해상 레벨) AND 콜드오픈 비중 **≥30%**.
- **NO-GO / 보류**: 이득 <40% 또는 bicubic이 실용상 동등(0.978 선례) 또는 콜드오픈 비중 낮음
  → SR과 동일 판정(보류), 3D 점진+bicubic로 충분.

---

## 4. 리스크 / 노선
- **서버 인프라 리스크**: 안 A(Orthanc 재빌드)는 live 병원 시스템에 고위험 — PoC로 정당화되기 전 금지.
  안 C도 사이드카 컨테이너 추가라 배포 신중(compose·nginx 경로).
- **"측정으로 판정"**: SR 기각(0.978)·VRT 서버렌더 강등(585ms)과 동일 — 데이터가 정당화할 때만 구현.
- **OpenJPH 라이선스**: OpenJPH는 permissive(2-clause BSD 계열) — 통합 무장애(확인 필요).
- **데이터 의존**: 콜드오픈 비중은 프리페치 stats 누적(1~2주) 필요 — [[next-work-candidates]] 항목2와 결합.

---

## 5. 착수 순서
```
1 [PoC] 샘플 CT 확보 → 로컬 ojph_compress HTJ2K 생성 → 3-way 첫타일 측정 + 콜드오픈 비중
2 [게이트] Go/No-Go 판정 (§3 기준)
3 [GO 시] 안 C 사이드카 구현: WADO-RS 프록시 + OpenJPH 트랜스코드 + nginx 캐시 결합 + 뷰어 stackRetrieveOptions 활성
4 [측정] 운영 첫타일 실측 vs baseline, 회귀 가드 E2E
```

**현재 산출**: 본 설계 + PoC 측정. **PoC 1단계(운영 데이터)로 go/no-go 확정 — 아래 §6.**

---

## 6. PoC 측정 결과 & 판정 (2026-07-08) — **NO-GO / 보류**

서버 인프라 변경 0으로 **가장 싸고 결정적인 데이터(운영 프리페치·점진 stats)**를 먼저 측정.

### 실측 (라이브 `GET /prefetch/stats`, 30일 창 + DB)
| 지표 | 값 | 함의 |
|------|----|------|
| 뷰어 열람(30일) | **47건** (≈1.5/일) | dev/staging 저부하 — 실 임상 대용량 CT 부하 부재 |
| 콜드오픈 첫영상 `avg_load_ms_cold` | **339ms** | **이미 빠름** — HTJ2K가 겨냥하는 "느린 첫타일" 병목 없음 |
| warmed 첫영상 | 455ms (n작아 노이즈) | 콜드가 warmed보다 빠를 만큼 소규모·경량 study |
| `progressive_volume.samples` | **0** | 3D 볼륨(대용량) 로딩 자체가 미발생 |
| `viewer_open_events.volume_complete` | **0** / 47 | 대용량 볼륨 콜드오픈 시나리오 부재 |
| 프리페치 hit_rate | 0.409 | (표본 소·해석 무의미) |

### 판정: **NO-GO (§3 기준 미충족)**
- 콜드오픈 첫영상 **339ms = 이미 빠름** → HTJ2K "≥40% 단축"이 절대시간상 무의미(수십~백ms대).
- **대용량 CT 콜드오픈 시나리오 부재**(volume samples 0, study 극소, 47opens/30d) — HTJ2K 이득 대상이 없음.
- SR 기각(bicubic 0.978)·VRT 서버렌더 강등(수요 없음)과 **동일 결론**: 데이터가 투자를 정당화하지 않음.

### 권고 (재개 조건)
- **보류.** OpenJPH 코덱/사이드카 착수하지 않음(대형·서버 리스크 대비 이득 미검증).
- **재개 트리거**: 실 임상 가동에서 ① 대용량 CT(500+ 슬라이스) 열람이 상시 발생하고 ②
  `avg_load_ms_cold`가 체감 병목(예: ≥1.5s) ③ 콜드오픈 비중이 높을 때. v11.9 계측 인프라가
  이 데이터를 이미 수집하도록 배선돼 있으므로, 실부하 축적 후 §3 PoC부터 재평가.
- 그 전까지 **3D 볼륨 점진(활성) + bicubic 업스케일(0.978)로 충분**.
