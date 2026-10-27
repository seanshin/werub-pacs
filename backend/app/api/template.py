"""Report template API + seed default templates."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.security import RequireRole, get_current_user
from app.models.template import ReportTemplate
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


class TemplateCreate(BaseModel):
    name: str
    modality: str
    body_part: str | None = None
    description: str | None = None
    is_default: bool = False
    sections: list[dict]
    impression_template: str | None = None
    normal_template: str | None = None
    macros: dict | None = None


def _to_response(t: ReportTemplate) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "modality": t.modality,
        "body_part": t.body_part,
        "description": t.description,
        "is_default": t.is_default,
        "sections": t.sections,
        "impression_template": t.impression_template,
        "normal_template": t.normal_template,
        "macros": t.macros,
    }


@router.get("")
async def list_templates(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    modality: str | None = Query(None),
):
    query = select(ReportTemplate).order_by(ReportTemplate.modality, ReportTemplate.name)
    if modality:
        query = query.where(ReportTemplate.modality == modality)
    result = await db.execute(query)
    templates = result.scalars().all()
    return {"count": len(templates), "templates": [_to_response(t) for t in templates]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False))],
):
    t = ReportTemplate(**body.model_dump())
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return _to_response(t)


@router.get("/{template_id}")
async def get_template(
    template_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(select(ReportTemplate).where(ReportTemplate.id == template_id))
    t = result.scalar_one_or_none()
    if not t:
        raise NotFoundError(resource="Template", resource_id=str(template_id))
    return _to_response(t)


@router.post("/seed-defaults")
async def seed_default_templates(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Create default Korean report templates. Admin only."""
    defaults = [
        {
            "name": "흉부 X-ray (Chest PA)",
            "modality": "CR",
            "body_part": "CHEST",
            "description": "흉부 단순촬영 판독 템플릿",
            "is_default": True,
            "sections": [
                {"name": "폐야", "key": "lung", "type": "text", "default": "양측 폐야 깨끗함"},
                {"name": "심장", "key": "heart", "type": "text", "default": "심비대 소견 없음"},
                {"name": "종격동", "key": "mediastinum", "type": "text", "default": "종격동 이상 소견 없음"},
                {"name": "흉막", "key": "pleura", "type": "text", "default": "흉수 없음"},
                {"name": "골격", "key": "bone", "type": "text", "default": "골격 이상 소견 없음"},
            ],
            "normal_template": "양측 폐야 깨끗함. 심비대 소견 없음. 종격동 이상 소견 없음. 흉수 없음.",
            "impression_template": "정상 흉부 소견",
            "macros": {"nl": "이상 소견 없음", "nml": "정상 소견", "cxr_n": "정상 흉부 단순촬영 소견"},
        },
        {
            "name": "뇌 CT (Brain CT)",
            "modality": "CT",
            "body_part": "HEAD",
            "description": "뇌 CT 판독 템플릿",
            "is_default": True,
            "sections": [
                {"name": "뇌실질", "key": "parenchyma", "type": "text", "default": "뇌실질 내 이상 음영 없음"},
                {"name": "뇌실", "key": "ventricle", "type": "text", "default": "뇌실 크기 정상"},
                {"name": "뇌수조", "key": "cistern", "type": "text", "default": "뇌수조 정상 관찰"},
                {"name": "두개골", "key": "skull", "type": "text", "default": "두개골 골절 소견 없음"},
                {"name": "부비동", "key": "sinus", "type": "text", "default": "부비동 이상 소견 없음"},
                {"name": "정중선", "key": "midline", "type": "text", "default": "정중선 편위 없음"},
            ],
            "normal_template": "뇌실질 내 이상 음영 없음. 뇌실 크기 정상. 정중선 편위 없음. 두개골 골절 없음.",
            "impression_template": "정상 뇌 CT 소견",
            "macros": {"ich": "뇌출혈 의심", "sah": "지주막하 출혈 의심", "infarct": "뇌경색 의심"},
        },
        {
            "name": "복부 CT (Abdomen CT)",
            "modality": "CT",
            "body_part": "ABDOMEN",
            "description": "복부 CT 판독 템플릿",
            "is_default": True,
            "sections": [
                {"name": "간", "key": "liver", "type": "text", "default": "간 크기 정상, 국소 병변 없음"},
                {"name": "담낭/담관", "key": "gallbladder", "type": "text", "default": "담낭 정상, 담석 없음"},
                {"name": "췌장", "key": "pancreas", "type": "text", "default": "췌장 정상 소견"},
                {"name": "비장", "key": "spleen", "type": "text", "default": "비장 크기 정상"},
                {"name": "신장", "key": "kidney", "type": "text", "default": "양측 신장 정상"},
                {"name": "장관", "key": "bowel", "type": "text", "default": "장관 이상 소견 없음"},
                {"name": "림프절", "key": "lymph_node", "type": "text", "default": "유의한 림프절 종대 없음"},
                {"name": "복수", "key": "ascites", "type": "text", "default": "복수 없음"},
            ],
            "normal_template": "간, 담낭, 췌장, 비장, 양측 신장 정상 소견. 유의한 림프절 종대 없음. 복수 없음.",
            "impression_template": "복부 CT 특이 소견 없음",
            "macros": {"hcc": "간세포암 의심", "rcc": "신세포암 의심", "app": "급성 충수염 의심"},
        },
        {
            "name": "무릎 MRI (Knee MRI)",
            "modality": "MR",
            "body_part": "KNEE",
            "description": "무릎 MRI 판독 템플릿",
            "is_default": True,
            "sections": [
                {"name": "전방십자인대", "key": "acl", "type": "text", "default": "정상 신호강도 및 연속성 유지"},
                {"name": "후방십자인대", "key": "pcl", "type": "text", "default": "정상 소견"},
                {"name": "내측 반월판", "key": "medial_meniscus", "type": "text", "default": "파열 소견 없음"},
                {"name": "외측 반월판", "key": "lateral_meniscus", "type": "text", "default": "파열 소견 없음"},
                {"name": "관절연골", "key": "cartilage", "type": "text", "default": "관절연골 정상"},
                {"name": "골수", "key": "bone_marrow", "type": "text", "default": "골수 부종 없음"},
                {"name": "관절액", "key": "effusion", "type": "text", "default": "관절삼출 없음"},
            ],
            "normal_template": "전후방 십자인대 정상. 내외측 반월판 파열 없음. 관절연골 정상. 골수 부종 없음.",
            "impression_template": "무릎 MRI 정상 소견",
            "macros": {"acl_t": "전방십자인대 파열", "mm_t": "내측 반월판 파열", "oa": "퇴행성 관절염"},
        },
        {
            "name": "유방 MRI (Breast MRI)",
            "modality": "MR",
            "body_part": "BREAST",
            "description": "유방 MRI 판독 템플릿 (BI-RADS)",
            "is_default": True,
            "sections": [
                {"name": "배경실질조영증강", "key": "bpe", "type": "select", "options": ["미약", "경도", "중등도", "현저"], "default": "미약"},
                {"name": "우측 유방", "key": "right_breast", "type": "text", "default": "이상 조영증강 병변 없음"},
                {"name": "좌측 유방", "key": "left_breast", "type": "text", "default": "이상 조영증강 병변 없음"},
                {"name": "액와 림프절", "key": "axilla", "type": "text", "default": "유의한 림프절 종대 없음"},
                {"name": "BI-RADS", "key": "birads", "type": "select", "options": ["1", "2", "3", "4A", "4B", "4C", "5", "6"], "default": "1"},
            ],
            "normal_template": "양측 유방 이상 조영증강 병변 없음. 액와 림프절 종대 없음.",
            "impression_template": "BI-RADS 1 — 정상",
            "macros": {"mass": "조영증강 종괴", "nme": "비종괴 조영증강"},
        },
    ]

    created = 0
    skipped = 0
    for tmpl in defaults:
        existing = await db.execute(
            select(ReportTemplate).where(ReportTemplate.name == tmpl["name"])
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue
        t = ReportTemplate(**tmpl)
        db.add(t)
        created += 1

    await db.commit()
    return {"created": created, "skipped": skipped, "total_defaults": len(defaults)}
