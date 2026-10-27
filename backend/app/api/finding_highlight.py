"""Critical finding keyword detection and highlighting."""
import re
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import RequireRole
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/findings", tags=["소견 분석"])

# Critical keywords — Korean radiology
CRITICAL_KEYWORDS = {
    "urgent": [
        "출혈", "hemorrhage", "bleeding", "골절", "fracture", "기흉", "pneumothorax",
        "색전", "embolism", "파열", "rupture", "천공", "perforation",
        "뇌경색", "infarct", "뇌출혈", "ICH", "SAH", "지주막하",
        "대동맥 박리", "dissection", "장폐색", "obstruction",
        "긴장성", "tension", "심낭삼출", "tamponade",
    ],
    "important": [
        "종괴", "mass", "결절", "nodule", "tumor", "종양",
        "전이", "metastasis", "림프절 종대", "lymphadenopathy",
        "흉수", "effusion", "복수", "ascites",
        "수신증", "hydronephrosis", "담석", "stone",
        "폐렴", "pneumonia", "경화", "consolidation",
        "협착", "stenosis", "혈전", "thrombus",
    ],
    "attention": [
        "의심", "suspicious", "r/o", "rule out", "감별",
        "추적", "follow-up", "f/u", "비교", "증가", "감소",
        "새로운", "new", "변화", "change", "진행", "progression",
    ],
}


class FindingsText(BaseModel):
    findings: str
    impression: str = ""


@router.post("/highlight", summary="소견 키워드 하이라이트")
async def highlight_findings(
    body: FindingsText,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
):
    """소견 텍스트에서 중요 키워드를 감지하고 하이라이트합니다."""
    text = body.findings + " " + body.impression
    found = {"urgent": [], "important": [], "attention": []}

    for severity, keywords in CRITICAL_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text.lower():
                found[severity].append(kw)

    is_critical = len(found["urgent"]) > 0
    suggested_urgency = "urgent" if is_critical else "non_urgent" if found["important"] else "normal"

    return {
        "highlights": found,
        "is_critical": is_critical,
        "suggested_urgency": suggested_urgency,
        "total_keywords": sum(len(v) for v in found.values()),
    }
