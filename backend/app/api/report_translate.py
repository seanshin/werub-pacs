"""Report translation — Korean ↔ English bilingual report generation."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import RequireRole
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/reports", tags=["리포트 번역"])

# Simple Korean→English medical term mapping
TERM_MAP = {
    "이상 소견 없음": "No significant abnormality",
    "정상": "Normal",
    "결절": "Nodule",
    "종괴": "Mass",
    "출혈": "Hemorrhage",
    "경색": "Infarction",
    "골절": "Fracture",
    "흉수": "Pleural effusion",
    "복수": "Ascites",
    "폐렴": "Pneumonia",
    "경화": "Consolidation",
    "석회화": "Calcification",
    "부종": "Edema",
    "기흉": "Pneumothorax",
    "심비대": "Cardiomegaly",
    "담석": "Gallstone",
    "신결석": "Renal stone",
    "수신증": "Hydronephrosis",
    "추적 관찰": "Follow-up recommended",
    "비교 판독": "Comparison study",
    "양측": "Bilateral",
    "우측": "Right",
    "좌측": "Left",
    "폐야": "Lung fields",
    "뇌실질": "Brain parenchyma",
}


class TranslateRequest(BaseModel):
    findings: str
    impression: str
    target_language: str = "en"  # en or ko


@router.post("/translate", summary="리포트 번역 (한↔영)")
async def translate_report(
    body: TranslateRequest,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
):
    """판독 소견을 한국어↔영어로 번역합니다.

    기본 의학 용어 매핑 기반. 정밀 번역은 외부 AI API 연동 필요.
    """
    findings = body.findings
    impression = body.impression

    if body.target_language == "en":
        for ko, en in TERM_MAP.items():
            findings = findings.replace(ko, en)
            impression = impression.replace(ko, en)
    else:
        en_to_ko = {v: k for k, v in TERM_MAP.items()}
        for en, ko in en_to_ko.items():
            findings = findings.replace(en, ko)
            impression = impression.replace(en, ko)

    return {
        "findings": findings,
        "impression": impression,
        "target_language": body.target_language,
        "terms_mapped": len(TERM_MAP),
        "note": "기본 용어 매핑. 정밀 번역은 AI API 연동 필요.",
    }
