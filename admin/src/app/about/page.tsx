import type { Metadata } from 'next';
import type { LucideIcon } from 'lucide-react';
import {
  Server, Eye, Cpu, ScanSearch, FileText, Boxes, Users, Network, Stethoscope,
  Workflow, Lock, ShieldCheck, Dna, Inbox, Languages, SlidersHorizontal,
  ListChecks, Zap, Globe, Ruler, Layers, Award, ClipboardCheck,
} from 'lucide-react';

export const metadata: Metadata = {
  title: 'WeRU.B PACS 소개',
  description: '구현 기능 · 표준 규격 · 보안 인증 소개',
};

// 정적 소개 페이지 — 인증 불필요 (시스템 역량 쇼케이스)

const FEATURES: { icon: LucideIcon; title: string; desc: string; tags?: string[] }[] = [
  { icon: Server, title: 'DICOM 서버', desc: 'Orthanc 기반 DIMSE(C-STORE/C-FIND/C-MOVE/C-ECHO) + DICOMweb(QIDO/WADO/STOW-RS)', tags: ['PostgreSQL 인덱스', '49 전송구문'] },
  { icon: Eye, title: '웹 뷰어', desc: 'Cornerstone3D 기반 2D · MPR · MIP · 3D 볼륨 렌더링(VRT). 한국어 UI, W/L 프리셋, 멀티모니터', tags: ['MPR/3D', '한국형 프리셋'] },
  { icon: Cpu, title: 'AI 판독 연동', desc: '29개 AI 모델, 5종 추론 파이프라인. 결과를 DICOM 표준 SR(TID 1500)로 저장', tags: ['TID 1500 SR', 'FHIR R4'] },
  { icon: ScanSearch, title: '비표준 DICOM 검증·정규화', desc: 'JPEG 밀도(DPI) vs Pixel Spacing 교차검증 등 22규칙. 측정 오류 위험 자동 감지·정규화', tags: ['22 검증규칙', '13 자동수정'] },
  { icon: FileText, title: '판독 리포트 · 핵심영상', desc: '판독 CRUD/서명/템플릿/매크로, 예비판독, 구조화 SR(BI-RADS 등), 음성 입력, 핵심영상 마킹(KOS 88.59)', tags: ['구조화 SR', 'KOS'] },
  { icon: Boxes, title: 'QC · 영상 수집 허브', desc: 'Study 병합/분리, 관리자 업로드, 환자 셀프 업로드(토큰), 키오스크, 외부 PACS Q/R, 승인 큐' },
  { icon: Users, title: '협진 · 외부 연동', desc: '피어리뷰 · 세컨드오피니언 · 외부 판독 의뢰(토큰 포털), HIS 연동, SLA 에스컬레이션' },
  { icon: Network, title: '기관 간 영상 교환 (XDS-I / XDM)', desc: '선택 검사를 IHE 표준 패키지(XDM)로 생성 — ebRIM METADATA.XML + KOS 매니페스트 + 원본 DICOM. 연동 등록소 없이 타 벤더 PACS가 import 가능, 환자 추출(전용 포맷)과 달리 표준 상호운용', tags: ['IHE XDM', 'ebRIM', 'KOS 88.59'] },
  { icon: Stethoscope, title: '선제 AI 스크리닝 · 거버넌스', desc: '수신 영상 자동 AI 스크리닝→우연소견 알림(참고용), 모델 성능 시계열·드리프트·수용률 모니터링(SaMD 분리 점검)', tags: ['Opportunistic AI', 'AI 거버넌스'] },
  { icon: Workflow, title: '촬영실 워크플로 (MWL·MPPS·StgCmt)', desc: '모달리티가 예약 검사를 자동 조회(MWL)하고 촬영 진행/완료를 보고(MPPS)하며 저장을 확약(Storage Commitment) — DIMSE 워크플로 표준 3종, 수기 입력 오류 사전 예방', tags: ['MWL C-FIND', 'MPPS', 'Storage Commitment'] },
  { icon: Lock, title: '익명화 · 감사', desc: 'PS3.15 Basic Confidentiality Profile 익명화, 전 작업 감사 로그, Break-the-Glass' },
];

const STANDARDS: { name: string; detail: string }[] = [
  { name: 'DICOM PS3 (2024b)', detail: '적합성 선언문 v1.2 — Storage/Q-R/Verification SCP·SCU, PS3.2 §4 상세' },
  { name: 'Modality Worklist (MWL)', detail: 'C-FIND SCP — 촬영실이 예약 검사 자동 조회(환자정보 자동입력). AE OPENPACS-MWL' },
  { name: 'MPPS', detail: 'Performed Procedure Step N-CREATE/N-SET — 촬영 진행→완료 상태 추적. 예약→촬영 루프 완성' },
  { name: 'Storage Commitment', detail: 'Push Model N-ACTION/N-EVENT-REPORT — 저장 확약 응답. MWL·MPPS와 함께 DIMSE 워크플로 표준 3종 완비' },
  { name: 'HL7 v2 (RIS)', detail: 'MLLP 리스너 — HIS의 ORM(검사 오더)을 워크리스트로 매핑(→MWL→MPPS), ADT/ACK/ORU. 표준 RIS 루프' },
  { name: 'DICOM SR — TID 1500', detail: 'AI 결과를 Comprehensive SR(88.33) Measurement Report로. Device Observer + 근거영상' },
  { name: 'KOS (88.59)', detail: 'Key Object Selection — 핵심영상 마킹("Of Interest"), highdicom 생성' },
  { name: 'IHE XDS-I / XDM', detail: '기관 간 영상 교환 — ebRIM 3.0 METADATA.XML(SubmissionSet/DocumentEntry/Association) + KOS + DICOM 패키지. 연동 등록소 없이 표준 문서셋 생성(구조적 최소 적합)' },
  { name: 'DICOM SEG (66.4)', detail: '표준 Segmentation 빌더 (highdicom) — 분할 모델 연동 대기' },
  { name: 'DICOMweb', detail: 'QIDO-RS · WADO-RS · STOW-RS · WADO-URI (J2K 무손실 전송 3×↓)' },
  { name: '문자집합', detail: 'UTF-8(ISO_IR 192) 기본 · 한국어(ISO_IR 149) · 일본어/중국어' },
  { name: 'FHIR R4', detail: 'DiagnosticReport · RiskAssessment · Observation · Condition · Capability' },
  { name: 'PS3.15 익명화', detail: 'Basic Application Level Confidentiality Profile (Sup 142)' },
  { name: '코드체계', detail: 'KCD · EDI 코드 검색, 질병→검사 매핑. 로컬 개념은 사설 스킴(99OPENPACS, PS3.16 적합)' },
];

const SECURITY: { name: string; detail: string }[] = [
  { name: 'JWT 인증', detail: 'Access 1h / Refresh 7d, fail-closed 토큰 블랙리스트' },
  { name: 'RBAC (6역할)', detail: '관리자 · 영상의학과 전문의 · 전공의 · 방사선사 · 주치의 · 연구자' },
  { name: '비밀번호 보안', detail: 'PBKDF2 600,000회, 복잡도(12자+), 로그인 rate limit' },
  { name: '자격증명 암호화', detail: '외부 PACS 비밀번호 Fernet 암호화 저장 (저장 시 평문 금지)' },
  { name: 'Break-the-Glass', detail: '응급 접근(임상 read 한정) + 사후 감사. 세션 유휴 타임아웃(30분)' },
  { name: '전송 보안', detail: 'TLS 1.3 (Let\'s Encrypt), HSTS · CSP · X-Frame 보안 헤더' },
  { name: 'HIS SSO', detail: 'HIS JWT 검증(공유 시크릿/JWKS), JIT 프로비저닝(fail-closed), 역할 매핑' },
  { name: '인프라', detail: 'non-root 컨테이너, DICOM 포트 바인딩, pgcrypto · LUKS' },
];

const STATS = [
  { value: '345+', label: 'REST API' },
  { value: '29', label: 'AI 모델' },
  { value: '40+', label: 'DB 테이블' },
  { value: '15', label: 'Docker 컨테이너' },
  { value: '180ms', label: 'p95 응답(100동시)' },
  { value: '26+', label: '관리 페이지' },
];

const TECH = ['Orthanc 1.12.11', 'Cornerstone3D / OHIF v3.12', 'FastAPI (Python 3.12)', 'PostgreSQL 16', 'Redis 7 · Celery', 'Next.js 15', 'Nginx 1.24', 'highdicom · pydicom'];

// 상용 PACS(Sectra/Fujifilm/INFINITT) 대비 차별점 — docs/03-analysis/pacs-commercial-comparison.md
const DIFFERENTIATORS: { icon: LucideIcon; title: string; desc: string }[] = [
  { icon: ShieldCheck, title: '비표준 DICOM 안전성', desc: 'JPEG 밀도(DPI) vs Pixel Spacing 교차검증 등 22규칙 자동 검증·정규화. 상용은 표준 입력 가정 → 측정 오류를 선제 차단' },
  { icon: Dna, title: 'AI 결과 국제표준 인코딩', desc: 'AI 판독을 TID 1500 SR·SEG(highdicom)로 저장 — 벤더 종속 없는 상호운용' },
  { icon: Inbox, title: '영상 수집 허브', desc: '환자 셀프 업로드(토큰)·키오스크·외부 PACS Q/R·승인 큐 — 외부 영상 유입 워크플로 내장' },
  { icon: Languages, title: '한국 우선 설계', desc: '한국어 UI·환자명·날짜, KCD/EDI 코드, 의료법·개인정보보호법 준수' },
  { icon: SlidersHorizontal, title: 'DICOM 이슈 컨트롤 센터', desc: '검증 규칙·모달리티 렌더링·에러 메시지를 관리자가 직접 커스터마이즈' },
  { icon: ListChecks, title: '표준 워크플로 완비', desc: 'HL7 v2(ORM) → MWL → MPPS → Storage Commitment + KOS — HIS 오더부터 촬영실·저장확약까지 상용 대형 PACS급 표준 워크플로를 경량·웹 환경에 구현 (2026-06)' },
  { icon: Zap, title: '영상 전달 최적화', desc: 'WADO-RS J2K 무손실 전송으로 프레임 3×↓(524→176KB) + HTTP/2 멀티플렉싱 — 대용량 CT 빠른 로딩 (2026-06)' },
  { icon: Globe, title: '표준 기관 간 교환 + 선제 AI', desc: 'IHE XDS-I/XDM 표준 패키지 생성(연동 등록소 불요) + 수신 영상 선제 AI 스크리닝·AI 거버넌스(드리프트/수용률) — 해외 PACS 트렌드(opportunistic AI·AI governance·image liquidity) 선반영 (2026-06)' },
];

function SectionCard({ children }: { children: React.ReactNode }) {
  return <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800">{children}</div>;
}

function SectionTitle({ icon: Icon, children, className = '' }: { icon: LucideIcon; children: React.ReactNode; className?: string }) {
  return (
    <h2 className={`mb-3 flex items-center gap-2 text-lg font-bold text-gray-900 dark:text-gray-100 ${className}`}>
      <Icon className="h-5 w-5 text-blue-500 dark:text-blue-400" strokeWidth={1.75} aria-hidden />
      {children}
    </h2>
  );
}

export default function AboutPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      {/* Hero */}
      <div className="mb-8 rounded-2xl bg-gradient-to-br from-blue-600 to-blue-800 p-8 text-white shadow-lg">
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-white/20 text-2xl font-extrabold">W</div>
          <div>
            <h1 className="text-2xl font-bold">WeRU.B PACS</h1>
            <p className="text-sm text-blue-100">Web-based PACS with AI-assisted Reading · v11.0</p>
          </div>
        </div>
        <p className="mt-4 max-w-3xl text-sm leading-relaxed text-blue-50">
          중소 병원·클리닉을 위한 웹 기반 PACS 서버 + 뷰어 + 의료 AI 연동 시스템.
          비표준 DICOM 검증·정규화로 측정 정확도를 보장하고, AI 판독 결과를 DICOM 국제표준(TID 1500 SR)으로 저장합니다.
          MFDS Class 2 의료기기 소프트웨어(SaMD) 인허가를 준비 중입니다.
        </p>
        <div className="mt-5 grid grid-cols-3 gap-3 sm:grid-cols-6">
          {STATS.map((s) => (
            <div key={s.label} className="rounded-lg bg-white/10 p-3 text-center">
              <div className="text-xl font-bold">{s.value}</div>
              <div className="text-[11px] text-blue-100">{s.label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 핵심 기능 */}
      <SectionTitle icon={Layers}>핵심 기능</SectionTitle>
      <div className="mb-8 grid gap-4 sm:grid-cols-2">
        {FEATURES.map((f) => {
          const Icon = f.icon;
          return (
            <SectionCard key={f.title}>
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-300">
                  <Icon className="h-5 w-5" strokeWidth={1.75} aria-hidden />
                </div>
                <div>
                  <h3 className="font-semibold text-gray-900 dark:text-gray-100">{f.title}</h3>
                  <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">{f.desc}</p>
                  {f.tags && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {f.tags.map((t) => (
                        <span key={t} className="rounded bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">{t}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </SectionCard>
          );
        })}
      </div>

      {/* 표준·규격 / 보안·인증 (2열) */}
      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <SectionTitle icon={Ruler}>표준 · 규격</SectionTitle>
          <SectionCard>
            <ul className="space-y-3">
              {STANDARDS.map((s) => (
                <li key={s.name} className="border-b border-gray-100 pb-2 last:border-0 last:pb-0 dark:border-gray-700">
                  <div className="text-sm font-semibold text-gray-900 dark:text-gray-100">{s.name}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{s.detail}</div>
                </li>
              ))}
            </ul>
          </SectionCard>
        </div>
        <div>
          <SectionTitle icon={ShieldCheck}>보안 · 인증</SectionTitle>
          <SectionCard>
            <ul className="space-y-3">
              {SECURITY.map((s) => (
                <li key={s.name} className="border-b border-gray-100 pb-2 last:border-0 last:pb-0 dark:border-gray-700">
                  <div className="text-sm font-semibold text-gray-900 dark:text-gray-100">{s.name}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{s.detail}</div>
                </li>
              ))}
            </ul>
          </SectionCard>
        </div>
      </div>

      {/* 기술 스택 */}
      <SectionTitle icon={Boxes} className="mt-8">기술 스택</SectionTitle>
      <div className="mb-8 flex flex-wrap gap-2">
        {TECH.map((t) => (
          <span key={t} className="rounded-full border border-gray-200 bg-white px-3 py-1 text-sm text-gray-700 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300">{t}</span>
        ))}
      </div>

      {/* 상용 PACS 대비 경쟁력 */}
      <SectionTitle icon={Award} className="mb-1 mt-8">타 PACS 대비 경쟁력</SectionTitle>
      <p className="mb-3 text-xs text-gray-500 dark:text-gray-400">Sectra · Fujifilm Synapse · INFINITT 대비 차별점 (상세: docs/03-analysis/pacs-commercial-comparison.md)</p>
      <div className="mb-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {DIFFERENTIATORS.map((d) => {
          const Icon = d.icon;
          return (
            <div key={d.title} className="rounded-xl border border-blue-100 bg-blue-50/40 p-4 dark:border-blue-900/40 dark:bg-blue-900/10">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
                  <Icon className="h-4 w-4" strokeWidth={1.75} aria-hidden />
                </div>
                <h3 className="text-sm font-semibold text-blue-900 dark:text-blue-200">{d.title}</h3>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-gray-600 dark:text-gray-300">{d.desc}</p>
            </div>
          );
        })}
      </div>
      <SectionCard>
        <p className="text-xs leading-relaxed text-gray-500 dark:text-gray-400">
          <span className="font-semibold text-gray-700 dark:text-gray-300">포지셔닝</span> — 중소 병원·클리닉, 비표준 영상 유입이 많은 환경, AI 표준화·저비용을 중시하는 기관에 최적.
          표준 워크플로(MWL·MPPS·Storage Commitment)와 표준 객체(SR·KOS)까지 구현해 상용 PACS와 동등한 촬영실 연동·표준 적합성을 제공한다. 대형병원 엔터프라이즈(VNA·다과목·다중기관)·고급 3D(fusion/혈관분석)는 상용 우위이며, 본 제품은 해당 영역을 로드맵(v2.0)으로 확장 중.
        </p>
      </SectionCard>

      {/* 인허가 */}
      <SectionTitle icon={ClipboardCheck} className="mt-8">인허가 · 규제</SectionTitle>
      <SectionCard>
        <div className="grid gap-3 text-sm sm:grid-cols-3">
          <div><span className="font-semibold text-gray-900 dark:text-gray-100">MFDS Class 2</span><div className="text-xs text-gray-500">의료기기 소프트웨어(SaMD) 인허가 준비</div></div>
          <div><span className="font-semibold text-gray-900 dark:text-gray-100">개인정보보호법 · 의료법</span><div className="text-xs text-gray-500">5년 보존, 개인정보 보호 준수</div></div>
          <div><span className="font-semibold text-gray-900 dark:text-gray-100">규제 문서 25종</span><div className="text-xs text-gray-500">DHF, 위험관리, SOP, 적합성 선언문 등</div></div>
        </div>
      </SectionCard>

      <p className="mt-8 text-center text-xs text-gray-400">© 2026 WeRU.B Inc. · Based on Orthanc(GPLv3) · OHIF/Cornerstone3D(MIT)</p>
    </div>
  );
}
