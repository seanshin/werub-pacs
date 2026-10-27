"""DICOM Issue seed data — default rules, modality configs, message templates."""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dicom_issue import DicomIssueRule, DicomMessageTemplate, ModalityRenderConfig

logger = logging.getLogger(__name__)

SEED_RULES = [
    ("PARSE_FAILURE", "DICOM 파싱 실패", "metadata", "critical", True, "DICOM 파일을 파싱할 수 없습니다."),
    ("MISSING_MANDATORY_TAG", "필수 태그 누락", "metadata", "critical", True, "필수(Type 1) DICOM 태그가 누락되었��니다: {tag_name}"),
    ("EMPTY_MANDATORY_TAG", "필수 태그 빈 ��", "metadata", "error", False, "필수 태그 {tag_name}의 값이 비어있습���다."),
    ("MISSING_RECOMMENDED_TAG", "권장 태그 누���", "metadata", "warning", False, "권장(Type 2) 태그 {tag_name}이(가) 누락되었습니다."),
    ("UID_TOO_LONG", "UID 길이 초과", "uid", "error", False, "UID가 64자를 초과합니다 ({length}자)."),
    ("UID_INVALID_CHARS", "UID 비표준 문자", "uid", "error", False, "UID에 비표준 문자�� 포함되어 있습니다."),
    ("MISSING_CHARACTER_SET", "문자셋 누락", "character_set", "error", False, "비ASCII 문자가 있으나 Specific Character Set 태그가 없습���다."),
    ("UNKNOWN_CHARACTER_SET", "알 수 없는 문자셋", "character_set", "warning", False, "지원되지 않는 문자셋입니다: {charset}"),
    ("INVALID_DATE_FORMAT", "날짜 형식 오류", "metadata", "warning", False, "날짜 태그 형식이 YYYYMMDD가 아닙니다: {value}"),
    ("INVALID_IS_VALUE", "정수 값 오류", "metadata", "warning", False, "Integer String VR에 정수가 아닌 값: {value}"),
    ("MISSING_FILE_META", "File Meta 누락", "transfer_syntax", "error", False, "File Meta Information이 누락되었습니다."),
    ("MISSING_TRANSFER_SYNTAX", "Transfer Syntax 누락", "transfer_syntax", "error", False, "Transfer Syntax UID가 누락되었습니다."),
    ("BITS_STORED_GT_ALLOCATED", "Bits 불일치", "pixel_data", "error", False, "BitsStored({bits_stored})가 BitsAllocated({bits_allocated})보다 ���니다."),
    ("UNKNOWN_PHOTOMETRIC", "알 수 없는 Photometric", "pixel_data", "warning", False, "알 수 없는 Photometric Interpretation: {photometric}"),
    ("MISSING_IMAGE_DIMENSIONS", "영상 크기 누락", "pixel_data", "error", False, "픽셀 데이터가 있으나 Rows/Columns 태그가 누락되었습니���."),
    ("JPEG_DENSITY_MISMATCH", "JPEG 밀도 불일치", "jpeg", "warning", False, "JPEG 밀도와 Pixel Spacing이 {x_diff}%/{y_diff}% 차이납니다. 측정값 오류 가능!"),
    ("JPEG_DENSITY_NO_PIXEL_SPACING", "JPEG 밀도-PS 누락", "jpeg", "warning", False, "JPEG에 밀도 정보가 있으나 Pixel Spacing 태그가 없어 교차 검증 불가합니다."),
    ("JPEG_DEFAULT_DENSITY", "JPEG 기본 밀도", "jpeg", "info", False, "JPEG가 기본 1x1 DPI 밀도를 사용합니다 (플레이스홀더)."),
    ("JPEG_NONSQUARE_ASPECT", "JPEG 비정방 종횡비", "jpeg", "warning", False, "JPEG의 종���비가 정방형이 아닙니���: {x_density}:{y_density}"),
    ("PRIVATE_TAGS_PRESENT", "사설 태그 감지", "metadata", "info", False, "제조사 사설 태그가 {count}개 그룹에서 감지되��습니다."),
    ("NON_RENDERABLE_ONLY", "비렌더링 모달리티만", "metadata", "warning", False, "이 스터디에는 렌더링 가능한 시리즈가 없습니다 ({modality})."),
    ("INVALID_STUDY_UID", "Study UID 형식 오류", "uid", "error", False, "Study UID 형식이 DICOM 표준이 아니어서 뷰어에서 표���할 수 없습니���."),
    ("RETIRED_SOP_CLASS", "Retired SOP Class", "transfer_syntax", "warning", False, "폐기된 SOP Class UID({sop_class})를 사용 중입니다. 뷰어에서 렌더링 실패 가능."),
    ("RETIRED_TRANSFER_SYNTAX", "Retired Transfer Syntax", "transfer_syntax", "warning", False, "폐기된 Transfer Syntax({ts})를 사용 중입니���. 뷰어 디코딩 실�� 가능."),
]

SEED_MODALITIES = [
    ("RTSTRUCT", "non_renderable", "방사선 치료 구조물", "윤곽선/구조물 데이터로, 영상 픽셀이 포함되어 있지 않습니다.", "연결된 CT 영상과 함께 열어야 구조물이 표시됩니다.", 1),
    ("RTPLAN", "non_renderable", "방사선 치료 계획", "치료 계획 데이터로, 영상 픽셀이 포함되어 있지 않습��다.", "전용 RT 뷰어가 필요합니다.", 2),
    ("RTDOSE", "non_renderable", "방사선 선량 분포", "3D 선량 데이터로, 일반 뷰어에서 정확히 표시되지 않을 수 있습니다.", "전용 RT 뷰어 사용을 권장합니다.", 3),
    ("SR", "non_renderable", "구조화 리포트", "텍스트 기반 리포트로, 영상 데이터가 포함되어 ���지 않습니다.", "판독 리포트에서 내용을 확인하세���.", 4),
    ("PR", "non_renderable", "Presentation State", "영상 표시 설정 데이터로, 단독 표시가 불가능합니다.", "참조 영상에 적용되는 표시 설정입니다.", 5),
    ("KO", "non_renderable", "Key Object Selection", "주요 영상 참조 목록으로, 영상 자체가 아닙니다.", "참조된 원본 영상을 확인하세요.", 6),
    ("ANN", "non_renderable", "주석 데이터", "영상 주석(Annotation)으로, 단독 표시가 불��능합니다.", "참조 영상에 오버레이로 표시됩니다.", 7),
    ("SEG", "partial", "분할 데이터", "세그멘테이션 오버레이로, 원본 영상과 함께 표시됩니다.", "원본 영상과 함께 열어야 합니다.", 8),
    ("DOC", "renderable", "문서", "캡슐화된 문서(PDF 등)입니다.", "OHIF PDF Extension으로 표시 가능합니다.", 9),
]

SEED_MESSAGES = [
    ("viewer.non_renderable.title", "viewer", "영상 표시 불가", ["{modality}", "{modality_label}"]),
    ("viewer.non_renderable.description", "viewer", "{modality_label}(으)로, 영상 데이터가 포함되어 있지 않습니다.", ["{modality_label}"]),
    ("viewer.non_renderable.action_open", "viewer", "그래도 열기", []),
    ("viewer.invalid_uid.title", "viewer", "비표준 Study UID", []),
    ("viewer.invalid_uid.description", "viewer", "DICOM 표준 UID 형식이 아니어서 뷰���에서 열 수 없습니다.", ["{uid}"]),
    ("validation.critical.title", "validation", "DICOM 검증 실패", []),
    ("validation.jpeg_density", "validation", "JPEG 밀도와 Pixel Spacing이 {diff}% 차이납니다. 측정�� 오류 가능!", ["{diff}", "{ae_title}"]),
    ("queue.non_renderable_badge", "queue", "영상 표시 불가 모달리티", ["{modality}"]),
]


async def seed_dicom_issue_data(db: AsyncSession):
    """Seed default rules, modality configs, and message templates if empty."""
    # Rules
    existing = await db.execute(select(func.count()).select_from(DicomIssueRule))
    if (existing.scalar() or 0) == 0:
        for rule_code, name, cat, sev, locked, msg in SEED_RULES:
            db.add(DicomIssueRule(
                rule_code=rule_code, display_name=name, category=cat,
                default_severity=sev, severity=sev, severity_locked=locked,
                default_message=msg, auto_action="none",
            ))
        logger.info("Seeded %d DICOM issue rules", len(SEED_RULES))

    # Modalities
    existing = await db.execute(select(func.count()).select_from(ModalityRenderConfig))
    if (existing.scalar() or 0) == 0:
        for mod, rtype, label, desc, action, order in SEED_MODALITIES:
            db.add(ModalityRenderConfig(
                modality=mod, render_type=rtype, display_label=label,
                description=desc, action_text=action, sort_order=order,
            ))
        logger.info("Seeded %d modality render configs", len(SEED_MODALITIES))

    # Messages
    existing = await db.execute(select(func.count()).select_from(DicomMessageTemplate))
    if (existing.scalar() or 0) == 0:
        for key, ctx, txt, vars_ in SEED_MESSAGES:
            db.add(DicomMessageTemplate(
                message_key=key, context=ctx, default_text=txt, variables=vars_ or None,
            ))
        logger.info("Seeded %d message templates", len(SEED_MESSAGES))

    await db.commit()
