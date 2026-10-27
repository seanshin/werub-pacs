"""WeRU.B AI Server 고급 연동 API.

미연동 API 전체 통합:
- 5단계 추론 체인 (reasoning chain)
- 구조화 영상 판독 (BI-RADS/Lung-RADS)
- 약물 상호작용 검사
- 예측 모델 (재입원/합병증/약물부작용)
- FHIR R4 래퍼
- KCD/EDI 코드 검색
- GPU 스케줄러 모니터링
- 의무기록 초안
- 의학 참고문헌 RAG
"""
import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import AuditLogger
from app.core.config import settings
from app.core.database import get_db
from app.core.security import RequireRole, get_current_user
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai/advanced", tags=["ai-advanced"])

AI_SERVER_URL = settings.ai_server_url
AI_API_KEY = settings.ai_api_key
AI_HEADERS = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
MEDICAL_HEADERS = {
    "Authorization": f"Bearer {AI_API_KEY}",
    "X-Medical-Key": settings.ai_medical_key,
    "Content-Type": "application/json",
}


async def _post_ai(path: str, json_body: dict, timeout: float = 60.0, headers: dict | None = None) -> dict:
    """WeRU.B AI Server POST 호출 공통 헬퍼."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{AI_SERVER_URL}{path}",
            headers=headers or MEDICAL_HEADERS,
            json=json_body,
        )
        if resp.status_code == 200:
            return resp.json()
        error = resp.text[:300]
        logger.error(f"AI Server {path} error {resp.status_code}: {error}")
        return {"error": f"AI 서버 오류 ({resp.status_code})", "detail": error}


async def _get_ai(path: str, timeout: float = 10.0, headers: dict | None = None) -> dict:
    """WeRU.B AI Server GET 호출 공통 헬퍼."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"{AI_SERVER_URL}{path}",
            headers=headers or AI_HEADERS,
        )
        if resp.status_code == 200:
            return resp.json()
        return {"error": f"AI 서버 오류 ({resp.status_code})"}


# ═══════════════════════════════════════════════════
# 1. 추론 체인 (Reasoning Chain) — 5단계 진단 추론
# ═══════════════════════════════════════════════════

class ReasoningChainRequest(BaseModel):
    symptoms: str = Field(..., description="환자 증상")
    patient_age: int | None = None
    patient_sex: str | None = None
    medical_history: str | None = None
    findings: str | None = Field(None, description="영상/검사 소견")
    vital_signs: dict | None = None


@router.post("/reasoning-chain")
@AuditLogger.log("AI_REASONING_CHAIN", "Report")
async def reasoning_chain(
    body: ReasoningChainRequest,
    db: Annotated[AsyncSession, Depends(get_db)],  # audit decorator용
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """5단계 추론 체인: 증상 → 감별진단 → 순위 → 검사추천 → 종합평가.

    WeRUB /api/medical/reasoning/chain 호출.
    """
    # Build patient_text from structured input
    patient_text = body.symptoms
    if body.findings:
        patient_text += f"\n영상 소견: {body.findings}"
    if body.medical_history:
        patient_text += f"\n과거력: {body.medical_history}"

    payload = {"patient_text": patient_text}
    if body.patient_age:
        payload["patient_age"] = body.patient_age
    if body.patient_sex:
        payload["patient_sex"] = body.patient_sex
    if body.vital_signs:
        payload["vital_signs"] = body.vital_signs

    return await _post_ai("/api/medical/reasoning/chain", payload, timeout=120.0)


# ═══════════════════════════════════════════════════
# 2. 구조화 영상 판독 (BI-RADS / Lung-RADS)
# ═══════════════════════════════════════════════════

class StructuredReportRequest(BaseModel):
    study_instance_uid: str
    modality: str | None = None
    body_part: str | None = None
    clinical_info: str | None = None
    scoring_system: str | None = Field(None, description="bi-rads, lung-rads, li-rads, etc.")


@router.post("/structured-report")
@AuditLogger.log("AI_STRUCTURED_REPORT", "Study")
async def structured_report(
    body: StructuredReportRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],  # audit decorator용
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """구조화 영상 판독 보고서 생성 (BI-RADS/Lung-RADS 스코어링).

    Orthanc에서 영상 추출 → GPU 서버 /api/vision/medical/structured-report 호출.
    """
    from app.api.ai_assist import _get_study_jpeg

    orthanc = request.app.state.http_client
    img_bytes, study_info = await _get_study_jpeg(orthanc, body.study_instance_uid)

    modality = body.modality or study_info.get("modality", "CR")
    modality_map = {"CR": "xray", "DX": "xray", "CT": "ct", "MR": "mri", "US": "ultrasound", "MG": "xray"}
    api_modality = modality_map.get(modality, "xray")

    data = {
        "modality": api_modality,
        "language": "ko",
    }
    if body.body_part:
        data["body_part"] = body.body_part
    if body.clinical_info:
        data["clinical_info"] = body.clinical_info
    if body.scoring_system:
        data["scoring_system"] = body.scoring_system

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{AI_SERVER_URL}/api/vision/medical/structured-report",
            headers={"Authorization": f"Bearer {AI_API_KEY}"},
            files={"image": ("image.jpg", img_bytes, "image/jpeg")},
            data=data,
        )
        if resp.status_code == 200:
            result = resp.json()
            result["study_info"] = study_info
            return result
        error = resp.text[:300]
        logger.error(f"Structured report error {resp.status_code}: {error}")
        return {"error": f"구조화 판독 실패 ({resp.status_code})", "detail": error}


# ═══════════════════════════════════════════════════
# 3. 약물 상호작용 검사
# ═══════════════════════════════════════════════════

class DrugInteractionRequest(BaseModel):
    drugs: list[str] = Field(..., description="약물 목록", min_length=2)
    patient_age: int | None = None
    patient_weight: float | None = None
    conditions: list[str] | None = Field(None, description="기저질환")


@router.post("/drug-interactions")
async def drug_interactions(
    body: DrugInteractionRequest,
    user: Annotated[User, Depends(get_current_user)],
):
    """약물 상호작용 검사.

    조영제-약물, 약물-약물 상호작용을 AI + DB로 검증.
    """
    payload = {
        "drugs": body.drugs,
        "patient_age": body.patient_age,
        "patient_weight": body.patient_weight,
        "conditions": body.conditions or [],
    }
    return await _post_ai("/api/medical/drug-interactions", payload)


# ═══════════════════════════════════════════════════
# 4. 예측 모델 (재입원/합병증/약물부작용)
# ═══════════════════════════════════════════════════

class ReadmissionRequest(BaseModel):
    patient_age: int
    patient_sex: str
    diagnosis: str
    length_of_stay: int | None = None
    comorbidities: list[str] | None = None
    lab_results: dict | None = None


class ComplicationRequest(BaseModel):
    procedure: str = Field(..., description="시술/수술명")
    diagnosis: str = Field(..., description="진단명")
    patient_age: int
    patient_sex: str
    comorbidities: list[str] | None = None
    asa_score: int | None = Field(None, ge=1, le=5)


class AdverseDrugRequest(BaseModel):
    medications: list[str] = Field(..., description="약물 목록")
    patient_age: int
    patient_sex: str
    allergies: list[str] | None = None
    liver_function: str | None = None
    kidney_function: str | None = None


@router.post("/predict/readmission")
async def predict_readmission(
    body: ReadmissionRequest,
    user: Annotated[User, Depends(get_current_user)],
):
    """30일 재입원 위험도 예측 (HOSPITAL Score)."""
    return await _post_ai("/api/medical/predict/readmission", {
        "patient_data": body.model_dump(exclude_none=True)
    })


@router.post("/predict/complication")
async def predict_complication(
    body: ComplicationRequest,
    user: Annotated[User, Depends(get_current_user)],
):
    """시술/수술 합병증 위험도 예측."""
    payload = {
        "diagnosis": body.diagnosis,
        "procedure": body.procedure,
        "patient_age": body.patient_age,
        "patient_sex": body.patient_sex,
    }
    if body.comorbidities:
        payload["comorbidities"] = body.comorbidities
    if body.asa_score:
        payload["asa_score"] = body.asa_score
    return await _post_ai("/api/medical/predict/complication", payload)


@router.post("/predict/adverse-drug")
async def predict_adverse_drug(
    body: AdverseDrugRequest,
    user: Annotated[User, Depends(get_current_user)],
):
    """약물 부작용 예측 + DB 검증."""
    payload = {
        "medications": body.medications,
        "patient_age": body.patient_age,
        "patient_sex": body.patient_sex,
    }
    if body.allergies:
        payload["allergies"] = body.allergies
    if body.liver_function:
        payload["liver_function"] = body.liver_function
    if body.kidney_function:
        payload["kidney_function"] = body.kidney_function
    return await _post_ai("/api/medical/predict/adverse-drug", payload)


# ═══════════════════════════════════════════════════
# 5. FHIR R4 래퍼 (HIS 표준 연동)
# ═══════════════════════════════════════════════════

class FHIRDiagnosticRequest(BaseModel):
    symptoms: str
    patient_age: int | None = None
    patient_sex: str | None = None
    findings: str | None = None


class FHIRRiskRequest(BaseModel):
    prediction_type: str = Field(..., description="readmission, complication, adverse-drug")
    patient_data: dict


class FHIRDrugCheckRequest(BaseModel):
    drugs: list[str]


class FHIRConditionSearchRequest(BaseModel):
    query: str = Field(..., description="질병명 또는 KCD 코드")


@router.post("/fhir/diagnostic-report")
async def fhir_diagnostic_report(
    body: FHIRDiagnosticRequest,
    user: Annotated[User, Depends(get_current_user)],
):
    """추론 체인 결과를 FHIR R4 DiagnosticReport + Observation Bundle로 반환."""
    patient_text = body.symptoms
    if body.findings:
        patient_text += f"\n소견: {body.findings}"
    payload = {"patient_text": patient_text}
    if body.patient_age:
        payload["patient_age"] = body.patient_age
    if body.patient_sex:
        payload["patient_sex"] = body.patient_sex
    return await _post_ai("/api/fhir/DiagnosticReport", payload, timeout=120.0)


@router.post("/fhir/risk-assessment")
async def fhir_risk_assessment(
    body: FHIRRiskRequest,
    user: Annotated[User, Depends(get_current_user)],
):
    """예측 결과를 FHIR R4 RiskAssessment로 반환."""
    return await _post_ai("/api/fhir/RiskAssessment", body.model_dump())


@router.post("/fhir/drug-check")
async def fhir_drug_check(
    body: FHIRDrugCheckRequest,
    user: Annotated[User, Depends(get_current_user)],
):
    """약물 상호작용을 FHIR R4 Observation Bundle로 반환."""
    return await _post_ai("/api/fhir/Observation/drug-check", {"medications": body.drugs})


@router.post("/fhir/condition-search")
async def fhir_condition_search(
    body: FHIRConditionSearchRequest,
    user: Annotated[User, Depends(get_current_user)],
):
    """KCD 코드 검색 결과를 FHIR R4 Condition searchset으로 반환."""
    return await _post_ai("/api/fhir/Condition/search", {"query": body.query})


@router.get("/fhir/metadata")
async def fhir_metadata(user: Annotated[User, Depends(get_current_user)]):
    """FHIR CapabilityStatement (서버 지원 리소스 목록)."""
    return await _get_ai("/api/fhir/metadata")


# ═══════════════════════════════════════════════════
# 6. KCD/EDI 코드 검색
# ═══════════════════════════════════════════════════

class KCDSearchRequest(BaseModel):
    query: str = Field(..., description="질병명 또는 코드 (예: 폐렴, J18)")


class EDISearchRequest(BaseModel):
    query: str = Field(..., description="수가명 또는 코드 (예: 흉부CT, HA401)")


class CodeMappingRequest(BaseModel):
    disease: str = Field(..., description="질병명 또는 KCD 코드")
    mapping_type: str = Field("all", description="test, prescription, all")


@router.post("/codes/kcd")
async def search_kcd(
    body: KCDSearchRequest,
    user: Annotated[User, Depends(get_current_user)],
):
    """KCD 질병코드 검색 (한글/영문/코드)."""
    return await _post_ai("/api/medical/code/kcd", {"query": body.query})


@router.post("/codes/edi")
async def search_edi(
    body: EDISearchRequest,
    user: Annotated[User, Depends(get_current_user)],
):
    """EDI 수가코드 검색."""
    return await _post_ai("/api/medical/code/edi", {"query": body.query})


@router.post("/codes/mapping")
async def code_mapping(
    body: CodeMappingRequest,
    user: Annotated[User, Depends(get_current_user)],
):
    """질병 → 검사/처방 매핑 추천."""
    return await _post_ai("/api/medical/code/mapping", {
        "kcd_code": body.disease,
        "mapping_type": body.mapping_type,
    })


# ═══════════════════════════════════════════════════
# 7. GPU 스케줄러 & 모니터링
# ═══════════════════════════════════════════════════

@router.get("/gpu/status")
async def gpu_status(user: Annotated[User, Depends(get_current_user)]):
    """GPU 스케줄러 상태 (프로파일, VRAM, 적재 모델)."""
    return await _get_ai("/api/gpu/scheduler")


@router.get("/gpu/vram")
async def gpu_vram(user: Annotated[User, Depends(get_current_user)]):
    """GPU VRAM 상태."""
    return await _get_ai("/api/gpu/status")


@router.get("/server/models")
async def server_models(user: Annotated[User, Depends(get_current_user)]):
    """AI 서버 설치된 모델 목록."""
    return await _get_ai("/api/models")


@router.get("/server/stats")
async def server_stats(user: Annotated[User, Depends(get_current_user)]):
    """AI 서버 통계 (CPU/RAM/GPU)."""
    return await _get_ai("/api/server/stats")


# ═══════════════════════════════════════════════════
# 8. 의무기록 초안 & 의학 참고
# ═══════════════════════════════════════════════════

class MedicalDraftRequest(BaseModel):
    findings: str = Field(..., description="영상/검사 소견")
    patient_age: int | None = None
    patient_sex: str | None = None
    clinical_info: str | None = None
    modality: str | None = None


class MedicalReferenceRequest(BaseModel):
    query: str = Field(..., description="질병/증상/가이드라인 검색어")
    category: str | None = Field(None, description="disease, drug, guideline, lab")


class AutoRecordRequest(BaseModel):
    """진료 대화 → 자동 의무기록."""
    conversation: str = Field(..., description="진료 대화 텍스트")
    patient_age: int | None = None
    patient_sex: str | None = None
    department: str | None = None


@router.post("/medical-draft")
async def medical_draft(
    body: MedicalDraftRequest,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """의무기록 초안 생성.

    영상 소견 기반으로 정식 의무기록 형식의 초안을 AI가 생성.
    """
    # Build data text from structured input
    data_text = body.findings
    if body.patient_age:
        data_text += f" 환자 {body.patient_age}세"
    if body.patient_sex:
        data_text += f" {body.patient_sex}"
    if body.clinical_info:
        data_text += f". 임상정보: {body.clinical_info}"
    if body.modality:
        data_text += f" [검사: {body.modality}]"

    return await _post_ai("/api/medical/draft", {"data": data_text})


@router.post("/medical-reference")
async def medical_reference(
    body: MedicalReferenceRequest,
    user: Annotated[User, Depends(get_current_user)],
):
    """의학 참고문헌 RAG 검색.

    벡터 DB 기반으로 관련 의학 지식(가이드라인, 약물, 질환)을 검색.
    """
    payload = {"question": body.query}
    if body.category:
        payload["category"] = body.category
    return await _post_ai("/api/medical/reference", payload)


@router.post("/auto-record")
async def auto_record(
    body: AutoRecordRequest,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """진료 대화 → NER → SOAP + ICD-10 + 처방 자동 생성.

    진료 대화 텍스트를 분석하여 구조화된 의무기록을 자동 생성.
    """
    payload = {
        "conversation": body.conversation,
        "patient_age": body.patient_age,
        "patient_sex": body.patient_sex,
        "department": body.department or "",
    }
    return await _post_ai("/api/medical/auto-record", payload, timeout=120.0)


# ═══════════════════════════════════════════════════
# 9. 고품질 글쓰기 (Writing Craft Pipeline)
# ═══════════════════════════════════════════════════

class WritingCraftRequest(BaseModel):
    prompt: str = Field(..., description="글쓰기 주제/요청")
    style: str | None = Field(None, description="academic, report, creative, email, etc.")
    length: str | None = Field(None, description="short, medium, long")
    language: str = Field("ko", description="출력 언어")


@router.post("/writing-craft")
async def writing_craft(
    body: WritingCraftRequest,
    user: Annotated[User, Depends(get_current_user)],
):
    """고품질 글쓰기 — 3모델 파이프라인 (qwen→exaone-deep→dna).

    Stage 1: qwen2.5:14b (초안)
    Stage 2: exaone-deep (구조/논리 보강)
    Stage 3: dna:8b (한국어 다듬기)
    ~25초 소요.
    """
    payload = {
        "prompt": body.prompt,
        "language": body.language,
    }
    if body.style:
        payload["style"] = body.style
    if body.length:
        payload["length"] = body.length
    return await _post_ai("/api/writing/craft", payload, timeout=60.0, headers=AI_HEADERS)


# ═══════════════════════════════════════════════════
# 10. 강화 채팅 (Enhanced Chat — 도메인별 멀티모델)
# ═══════════════════════════════════════════════════

class EnhancedChatRequest(BaseModel):
    messages: list[dict] = Field(..., description="채팅 메시지 배열")
    domain: str | None = Field(None, description="medical, coding, writing, legal (자동 감지)")
    session_id: str | None = None
    stream: bool = False


@router.post("/enhanced-chat")
async def enhanced_chat(
    body: EnhancedChatRequest,
    user: Annotated[User, Depends(get_current_user)],
):
    """강화 채팅 — 도메인별 2~3모델 오케스트레이션.

    도메인별 파이프라인:
    - medical: werub → Med42 → werub (감별진단 포함)
    - coding: deepseek-coder → qwen2.5 (코드+리뷰)
    - writing: qwen2.5 → exaone-deep → dna (초안→구조→다듬기)
    - legal: qwen2.5 → exaone-deep (법률→논증)
    ~20-25초 소요.
    """
    payload = {
        "messages": body.messages,
        "stream": body.stream,
    }
    if body.domain:
        payload["domain"] = body.domain
    if body.session_id:
        payload["session_id"] = body.session_id
    return await _post_ai("/api/chat/enhanced", payload, timeout=60.0, headers=AI_HEADERS)
