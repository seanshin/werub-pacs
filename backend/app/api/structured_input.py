"""Structured report input schemas — checkbox/dropdown based finding entry."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import RequireRole
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/structured-input", tags=["구조화 입력"])


# Pre-defined structured schemas per modality+body_part
SCHEMAS = {
    "CT:HEAD": {
        "name": "뇌 CT 구조화 입력",
        "sections": [
            {
                "key": "parenchyma", "name": "뇌실질",
                "type": "checklist",
                "items": [
                    {"id": "normal", "label": "이상 없음", "default": True, "text": "뇌실질 내 이상 음영 없음"},
                    {"id": "hemorrhage", "label": "출혈", "text": "뇌실질 내 출혈 소견", "urgent": True},
                    {"id": "infarct", "label": "경색", "text": "뇌경색 의심 소견", "urgent": True},
                    {"id": "mass", "label": "종괴", "text": "뇌실질 내 종괴 소견"},
                    {"id": "edema", "label": "부종", "text": "뇌부종 소견"},
                    {"id": "calcification", "label": "석회화", "text": "뇌실질 내 석회화"},
                ],
            },
            {
                "key": "ventricle", "name": "뇌실",
                "type": "select",
                "options": [
                    {"id": "normal", "label": "정상", "text": "뇌실 크기 정상"},
                    {"id": "dilated", "label": "확장", "text": "뇌실 확장 소견 (수두증 의심)"},
                    {"id": "compressed", "label": "압박", "text": "뇌실 압박 소견"},
                ],
            },
            {
                "key": "midline", "name": "정중선",
                "type": "select",
                "options": [
                    {"id": "normal", "label": "편위 없음", "text": "정중선 편위 없음"},
                    {"id": "left", "label": "좌측 편위", "text": "정중선 좌측 편위", "urgent": True},
                    {"id": "right", "label": "우측 편위", "text": "정중선 우측 편위", "urgent": True},
                ],
            },
            {
                "key": "skull", "name": "두개골",
                "type": "checklist",
                "items": [
                    {"id": "normal", "label": "이상 없음", "default": True, "text": "두개골 골절 소견 없음"},
                    {"id": "fracture", "label": "골절", "text": "두개골 골절 소견", "urgent": True},
                    {"id": "scalp", "label": "두피 종창", "text": "두피 연부조직 종창"},
                ],
            },
            {
                "key": "sinus", "name": "부비동",
                "type": "checklist",
                "items": [
                    {"id": "normal", "label": "이상 없음", "default": True, "text": "부비동 이상 소견 없음"},
                    {"id": "sinusitis", "label": "부비동염", "text": "부비동 점막 비후 (부비동염 의심)"},
                    {"id": "fluid", "label": "액체 저류", "text": "부비동 내 액체 저류"},
                ],
            },
        ],
    },
    "CR:CHEST": {
        "name": "흉부 X-ray 구조화 입력",
        "sections": [
            {
                "key": "lung", "name": "폐야",
                "type": "checklist",
                "items": [
                    {"id": "normal", "label": "깨끗함", "default": True, "text": "양측 폐야 깨끗함"},
                    {"id": "opacity", "label": "음영 증가", "text": "폐야 음영 증가 소견"},
                    {"id": "nodule", "label": "결절", "text": "폐 결절 소견"},
                    {"id": "consolidation", "label": "경화", "text": "폐 경화 소견 (폐렴 의심)"},
                    {"id": "atelectasis", "label": "무기폐", "text": "무기폐 소견"},
                    {"id": "emphysema", "label": "폐기종", "text": "폐기종 소견"},
                ],
            },
            {
                "key": "heart", "name": "심장",
                "type": "select",
                "options": [
                    {"id": "normal", "label": "정상", "text": "심비대 소견 없음 (CTR 정상)"},
                    {"id": "cardiomegaly", "label": "심비대", "text": "심비대 소견 (CTR 증가)"},
                ],
            },
            {
                "key": "pleura", "name": "흉막",
                "type": "checklist",
                "items": [
                    {"id": "normal", "label": "이상 없음", "default": True, "text": "흉수 없음"},
                    {"id": "effusion_r", "label": "우측 흉수", "text": "우측 흉수 소견"},
                    {"id": "effusion_l", "label": "좌측 흉수", "text": "좌측 흉수 소견"},
                    {"id": "pneumothorax", "label": "기흉", "text": "기흉 소견", "urgent": True},
                ],
            },
            {
                "key": "mediastinum", "name": "종격동",
                "type": "checklist",
                "items": [
                    {"id": "normal", "label": "이상 없음", "default": True, "text": "종격동 이상 소견 없음"},
                    {"id": "widening", "label": "확장", "text": "종격동 확장 소견"},
                    {"id": "lymphadenopathy", "label": "림프절 종대", "text": "종격동 림프절 종대 의심"},
                ],
            },
        ],
    },
    "CT:ABDOMEN": {
        "name": "복부 CT 구조화 입력",
        "sections": [
            {
                "key": "liver", "name": "간",
                "type": "checklist",
                "items": [
                    {"id": "normal", "label": "정상", "default": True, "text": "간 크기 정상, 국소 병변 없음"},
                    {"id": "mass", "label": "종괴", "text": "간 내 종괴 소견"},
                    {"id": "cyst", "label": "낭종", "text": "간 낭종"},
                    {"id": "fatty", "label": "지방간", "text": "지방간 소견"},
                    {"id": "cirrhosis", "label": "경변", "text": "간경변 소견"},
                ],
            },
            {
                "key": "gallbladder", "name": "담낭",
                "type": "checklist",
                "items": [
                    {"id": "normal", "label": "정상", "default": True, "text": "담낭 정상, 담석 없음"},
                    {"id": "stone", "label": "담석", "text": "담석 소견"},
                    {"id": "cholecystitis", "label": "담낭염", "text": "급성 담낭염 의심 소견", "urgent": True},
                ],
            },
            {
                "key": "pancreas", "name": "췌장",
                "type": "checklist",
                "items": [
                    {"id": "normal", "label": "정상", "default": True, "text": "췌장 정상 소견"},
                    {"id": "pancreatitis", "label": "췌장염", "text": "급성 췌장염 소견", "urgent": True},
                    {"id": "mass", "label": "종괴", "text": "췌장 종괴 소견"},
                ],
            },
            {
                "key": "kidney", "name": "신장",
                "type": "checklist",
                "items": [
                    {"id": "normal", "label": "정상", "default": True, "text": "양측 신장 정상"},
                    {"id": "stone", "label": "결석", "text": "신결석 소견"},
                    {"id": "cyst", "label": "낭종", "text": "신장 낭종"},
                    {"id": "hydronephrosis", "label": "수신증", "text": "수신증 소견"},
                ],
            },
            {
                "key": "ascites", "name": "복수",
                "type": "select",
                "options": [
                    {"id": "none", "label": "없음", "text": "복수 없음"},
                    {"id": "small", "label": "소량", "text": "소량의 복수"},
                    {"id": "moderate", "label": "중등량", "text": "중등량의 복수"},
                    {"id": "large", "label": "다량", "text": "다량의 복수"},
                ],
            },
        ],
    },
}


class StructuredInput(BaseModel):
    modality: str
    body_part: str
    selections: dict  # { section_key: [selected_item_ids] or selected_option_id }


@router.get("/schemas", summary="구조화 입력 스키마 목록")
async def list_schemas(
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
):
    """사용 가능한 구조화 입력 스키마를 조회합니다."""
    return {
        "schemas": [
            {"key": k, "name": v["name"], "modality": k.split(":")[0], "body_part": k.split(":")[1]}
            for k, v in SCHEMAS.items()
        ]
    }


@router.get("/schemas/{schema_key}", summary="스키마 상세")
async def get_schema(
    schema_key: str,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
):
    """구조화 입력 스키마의 섹션/항목을 조회합니다."""
    schema = SCHEMAS.get(schema_key)
    if not schema:
        return {"error": "Schema not found", "available": list(SCHEMAS.keys())}
    return schema


@router.post("/generate-text", summary="구조화 입력 → 텍스트 변환")
async def generate_text(
    body: StructuredInput,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
):
    """체크박스/드롭다운 선택을 자연어 텍스트로 변환합니다."""
    key = f"{body.modality}:{body.body_part}"
    schema = SCHEMAS.get(key)
    if not schema:
        return {"error": "Schema not found"}

    findings_parts = []
    is_urgent = False

    for section in schema["sections"]:
        sec_key = section["key"]
        selected = body.selections.get(sec_key, [])

        if section["type"] == "checklist":
            if isinstance(selected, list):
                for item in section["items"]:
                    if item["id"] in selected:
                        findings_parts.append(item["text"])
                        if item.get("urgent"):
                            is_urgent = True
            elif not selected:
                # Default selection
                for item in section["items"]:
                    if item.get("default"):
                        findings_parts.append(item["text"])

        elif section["type"] == "select":
            if isinstance(selected, str):
                for opt in section["options"]:
                    if opt["id"] == selected:
                        findings_parts.append(opt["text"])
                        if opt.get("urgent"):
                            is_urgent = True
                        break
            else:
                # Default: first option
                if section["options"]:
                    findings_parts.append(section["options"][0]["text"])

    findings_text = ". ".join(findings_parts) + "." if findings_parts else ""

    return {
        "findings": findings_text,
        "is_urgent": is_urgent,
        "urgency": "urgent" if is_urgent else "normal",
        "section_count": len(findings_parts),
    }
