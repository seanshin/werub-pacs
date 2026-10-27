"""API endpoints for normalization algorithm settings and AI-based analysis."""
import json
import logging
import struct
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import get_async_db
from app.core.auth import get_current_user
from app.core.security import ClinicalWriteRoles, RequireRole
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/normalization", tags=["Normalization Settings"])


# ─── Models ───

class AlgorithmParam(BaseModel):
    threshold: Optional[float] = None

class AlgorithmConfig(BaseModel):
    id: str
    name: str
    description: str
    risk_level: str  # safe, medium, risky
    enabled: bool = True
    auto_apply: bool = False
    params: dict = {}

class TriggerConfig(BaseModel):
    on_receive: bool = False
    scheduled: bool = False
    schedule_time: str = "02:00"

class SettingsPayload(BaseModel):
    algorithms: list[AlgorithmConfig]
    trigger: TriggerConfig

class AiAnalyzeRequest(BaseModel):
    study_instance_uid: str


# ─── Default Algorithms ───

DEFAULT_ALGORITHMS = [
    {"id": "jpeg_density", "name": "JPEG 밀도(DPI/DPM) 수정", "description": "JFIF 헤더 vs DICOM Pixel Spacing 교차 검증", "risk_level": "risky", "enabled": True, "auto_apply": False, "params": {"threshold": 0.01}},
    {"id": "pixel_spacing", "name": "Pixel Spacing 정합성", "description": "ImagerPixelSpacing ↔ PixelSpacing 불일치 교정", "risk_level": "risky", "enabled": True, "auto_apply": False, "params": {}},
    {"id": "charset_utf8", "name": "Character Set (UTF-8)", "description": "SpecificCharacterSet 누락/오류 → ISO_IR 192", "risk_level": "safe", "enabled": True, "auto_apply": True, "params": {}},
    {"id": "window_level", "name": "Window Center/Width 정규화", "description": "비표준 W/L 값 정규화", "risk_level": "safe", "enabled": True, "auto_apply": True, "params": {}},
    {"id": "patient_name_kr", "name": "환자명 한국어 인코딩", "description": "EUC-KR → UTF-8 변환", "risk_level": "safe", "enabled": True, "auto_apply": True, "params": {}},
    {"id": "date_format", "name": "DA 날짜 형식", "description": "비표준 날짜 → YYYYMMDD 강제", "risk_level": "safe", "enabled": True, "auto_apply": True, "params": {}},
    {"id": "uid_normalize", "name": "UID 정규화", "description": "비표준 UID 접두사 수정", "risk_level": "medium", "enabled": True, "auto_apply": False, "params": {}},
    {"id": "transfer_syntax", "name": "Transfer Syntax 변환", "description": "비표준 전송 구문 변환", "risk_level": "medium", "enabled": True, "auto_apply": False, "params": {}},
]

DEFAULT_TRIGGER = {"on_receive": False, "scheduled": False, "schedule_time": "02:00"}


# ─── Settings Endpoints ───

@router.get("/settings")
async def get_settings(
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """Get normalization algorithm settings and trigger configuration."""
    try:
        result = await db.execute(
            text("SELECT value FROM openpacs_config WHERE key = 'normalization_settings'")
        )
        row = result.scalar_one_or_none()
        if row:
            data = json.loads(row) if isinstance(row, str) else row
            return data
    except Exception:
        pass
    return {"algorithms": DEFAULT_ALGORITHMS, "trigger": DEFAULT_TRIGGER}


@router.put("/settings")
async def update_settings(
    payload: SettingsPayload,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, allow_btg=False)),
):
    """Update normalization algorithm settings. Admin or Technologist only."""
    data = payload.model_dump()
    value_json = json.dumps(data, ensure_ascii=False)

    # openpacs_config table is created at startup (core/schema_migrations).
    await db.execute(text(
        """INSERT INTO openpacs_config (key, value, updated_by)
           VALUES ('normalization_settings', :val, :user)
           ON CONFLICT (key) DO UPDATE SET value = :val, updated_by = :user, updated_at = NOW()"""
    ), {"val": value_json, "user": user.username})
    await db.commit()

    logger.info("Normalization settings updated by %s", user.username)
    return {"status": "ok", "message": "설정이 저장되었습니다"}


# ─── AI Non-standard Analysis ───

@router.post("/ai-analyze")
async def ai_analyze_study(
    req: AiAnalyzeRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(ClinicalWriteRoles),
):
    """AI-based non-standard DICOM analysis for a study.

    Analyzes DICOM metadata to detect non-standard elements and suggests
    appropriate normalization algorithms.
    """
    import time
    import httpx

    start = time.time()
    study_uid = req.study_instance_uid
    issues = []

    try:
        # Fetch study instances from Orthanc
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Find study in Orthanc
            orthanc_url = settings.orthanc_url
            auth = (settings.orthanc_username, settings.orthanc_password)

            # Search for the study
            search_resp = await client.post(
                f"{orthanc_url}/tools/find",
                json={"Level": "Study", "Query": {"StudyInstanceUID": study_uid}},
                auth=auth,
            )
            if search_resp.status_code != 200 or not search_resp.json():
                raise HTTPException(404, f"Study not found: {study_uid}")

            orthanc_id = search_resp.json()[0]

            # Get study details
            study_resp = await client.get(f"{orthanc_url}/studies/{orthanc_id}", auth=auth)
            study_data = study_resp.json()
            tags = study_data.get("MainDicomTags", {})

            # Get first instance for detailed tag analysis
            instances_resp = await client.get(
                f"{orthanc_url}/studies/{orthanc_id}/instances", auth=auth
            )
            instance_list = instances_resp.json()

            if instance_list:
                first_instance = instance_list[0]["ID"]
                inst_tags_resp = await client.get(
                    f"{orthanc_url}/instances/{first_instance}/simplified-tags", auth=auth
                )
                inst_tags = inst_tags_resp.json()

                # === Rule-based analysis ===

                # 1. Character Set check
                charset = inst_tags.get("SpecificCharacterSet", "")
                if not charset:
                    issues.append({
                        "tag": "SpecificCharacterSet (0008,0005)",
                        "field": "SpecificCharacterSet",
                        "risk_level": "safe",
                        "description": "SpecificCharacterSet 태그 누락 — 한글 표시 오류 가능",
                        "current_value": "(없음)",
                        "suggested_value": "ISO_IR 192",
                        "algorithm": "charset_utf8",
                        "auto_fixable": True,
                    })
                elif "ISO_IR 192" not in charset and "ISO 2022" not in charset:
                    issues.append({
                        "tag": "SpecificCharacterSet (0008,0005)",
                        "field": "SpecificCharacterSet",
                        "risk_level": "safe",
                        "description": f"비표준 문자셋: {charset} — UTF-8 변환 권장",
                        "current_value": charset,
                        "suggested_value": "ISO_IR 192",
                        "algorithm": "charset_utf8",
                        "auto_fixable": True,
                    })

                # 2. Patient Name encoding
                patient_name = inst_tags.get("PatientName", "")
                if patient_name and any(ord(c) > 127 for c in patient_name):
                    # Check for garbled Korean
                    try:
                        patient_name.encode("utf-8")
                    except UnicodeEncodeError:
                        issues.append({
                            "tag": "PatientName (0010,0010)",
                            "field": "PatientName",
                            "risk_level": "safe",
                            "description": "환자명 인코딩 오류 — 깨진 한글 감지",
                            "current_value": patient_name[:50],
                            "suggested_value": "(UTF-8 변환)",
                            "algorithm": "patient_name_kr",
                            "auto_fixable": True,
                        })

                # 3. Date format check
                for date_tag in ["StudyDate", "SeriesDate", "ContentDate", "PatientBirthDate"]:
                    date_val = inst_tags.get(date_tag, "")
                    if date_val and (len(date_val) != 8 or not date_val.isdigit()):
                        issues.append({
                            "tag": f"{date_tag}",
                            "field": date_tag,
                            "risk_level": "safe",
                            "description": f"비표준 날짜 형식: {date_val}",
                            "current_value": date_val,
                            "suggested_value": date_val.replace("-", "").replace("/", "").replace(".", "")[:8],
                            "algorithm": "date_format",
                            "auto_fixable": True,
                        })

                # 4. Pixel Spacing check
                pixel_spacing = inst_tags.get("PixelSpacing", "")
                imager_pixel_spacing = inst_tags.get("ImagerPixelSpacing", "")
                if pixel_spacing and imager_pixel_spacing:
                    if pixel_spacing != imager_pixel_spacing:
                        issues.append({
                            "tag": "PixelSpacing (0028,0030) vs ImagerPixelSpacing (0018,1164)",
                            "field": "PixelSpacing",
                            "risk_level": "risky",
                            "description": "PixelSpacing과 ImagerPixelSpacing 불일치 — 측정값 오류 가능",
                            "current_value": f"PS={pixel_spacing}, IPS={imager_pixel_spacing}",
                            "suggested_value": f"통일: {imager_pixel_spacing}",
                            "algorithm": "pixel_spacing",
                            "auto_fixable": False,
                        })

                # 5. Window Center/Width
                wc = inst_tags.get("WindowCenter", "")
                ww = inst_tags.get("WindowWidth", "")
                if wc and ww:
                    try:
                        wc_val = float(str(wc).split("\\")[0]) if wc else 0
                        ww_val = float(str(ww).split("\\")[0]) if ww else 0
                        if ww_val <= 0 or ww_val > 65535:
                            issues.append({
                                "tag": "WindowWidth (0028,1051)",
                                "field": "WindowWidth",
                                "risk_level": "safe",
                                "description": f"비정상 Window Width 값: {ww_val}",
                                "current_value": str(ww_val),
                                "suggested_value": "(모달리티별 기본값)",
                                "algorithm": "window_level",
                                "auto_fixable": True,
                            })
                    except (ValueError, TypeError):
                        pass

                # 6. Transfer Syntax check
                transfer_syntax = inst_tags.get("TransferSyntaxUID", "")
                known_ts = [
                    "1.2.840.10008.1.2",      # Implicit VR Little Endian
                    "1.2.840.10008.1.2.1",    # Explicit VR Little Endian
                    "1.2.840.10008.1.2.2",    # Explicit VR Big Endian
                    "1.2.840.10008.1.2.4.50", # JPEG Baseline
                    "1.2.840.10008.1.2.4.51", # JPEG Extended
                    "1.2.840.10008.1.2.4.57", # JPEG Lossless
                    "1.2.840.10008.1.2.4.70", # JPEG Lossless SV1
                    "1.2.840.10008.1.2.4.80", # JPEG-LS Lossless
                    "1.2.840.10008.1.2.4.81", # JPEG-LS Lossy
                    "1.2.840.10008.1.2.4.90", # JPEG 2000 Lossless
                    "1.2.840.10008.1.2.4.91", # JPEG 2000
                    "1.2.840.10008.1.2.5",    # RLE Lossless
                ]
                if transfer_syntax and transfer_syntax not in known_ts:
                    issues.append({
                        "tag": "TransferSyntaxUID (0002,0010)",
                        "field": "TransferSyntaxUID",
                        "risk_level": "medium",
                        "description": f"비표준 Transfer Syntax: {transfer_syntax}",
                        "current_value": transfer_syntax,
                        "suggested_value": "1.2.840.10008.1.2.1 (Explicit VR Little Endian)",
                        "algorithm": "transfer_syntax",
                        "auto_fixable": False,
                    })

                # 7. UID validation
                for uid_tag in ["StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID"]:
                    uid_val = inst_tags.get(uid_tag, "")
                    if uid_val and not uid_val.startswith(("1.2.", "1.3.", "2.16.")):
                        issues.append({
                            "tag": uid_tag,
                            "field": uid_tag,
                            "risk_level": "medium",
                            "description": f"비표준 UID 접두사: {uid_val[:30]}...",
                            "current_value": uid_val[:50],
                            "suggested_value": "(OID root 준수 UID)",
                            "algorithm": "uid_normalize",
                            "auto_fixable": False,
                        })

                # === 8. JPEG Density Manipulation Detection ===
                # (CLAUDE.md: "비표준 DICOM 검증이 매우 중요한 이유")
                # JFIF 헤더의 Xdensity/Ydensity vs DICOM Pixel Spacing 교차 검증
                try:
                    # Get raw DICOM bytes for JPEG header analysis
                    raw_resp = await client.get(
                        f"{orthanc_url}/instances/{first_instance}/file", auth=auth
                    )
                    if raw_resp.status_code == 200:
                        dicom_bytes = raw_resp.content
                        jpeg_issues = _analyze_jpeg_density(dicom_bytes, inst_tags)
                        issues.extend(jpeg_issues)
                except Exception as je:
                    logger.debug("JPEG density check skipped: %s", je)

                # === 9. Manufacturer-specific known non-standard patterns ===
                manufacturer = inst_tags.get("Manufacturer", "").upper()
                model = inst_tags.get("ManufacturerModelName", "")
                software = inst_tags.get("SoftwareVersions", "")
                mfr_issues = _check_manufacturer_patterns(
                    manufacturer, model, software, inst_tags
                )
                issues.extend(mfr_issues)

                # === 10. Missing mandatory tags check ===
                mandatory_issues = _check_mandatory_tags(inst_tags)
                issues.extend(mandatory_issues)

            # === MedGemma AI analysis (hybrid) ===
            ai_issues = await _medgemma_analyze(
                inst_tags if instance_list else tags,
                issues,
                study_uid,
            )
            issues.extend(ai_issues)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI analysis failed for %s: %s", study_uid, str(e))
        raise HTTPException(500, f"분석 실패: {str(e)}")

    duration_ms = int((time.time() - start) * 1000)

    # Deduplicate by tag+algorithm
    seen = set()
    unique_issues = []
    for issue in issues:
        key = (issue.get("tag", ""), issue.get("algorithm", ""))
        if key not in seen:
            seen.add(key)
            unique_issues.append(issue)

    return {
        "study_instance_uid": study_uid,
        "total_issues": len(unique_issues),
        "issues": unique_issues,
        "duration_ms": duration_ms,
        "analysis_type": "hybrid",
        "models": ["pydicom-rules-v2", "jpeg-density-analyzer", "manufacturer-patterns", "medgemma-4b"],
    }


# ─── JPEG Density Manipulation Detection ───

def _analyze_jpeg_density(dicom_bytes: bytes, inst_tags: dict) -> list:
    """Analyze JPEG compressed DICOM for density manipulation.

    Checks JFIF APP0 marker for Xdensity/Ydensity values and compares
    with DICOM PixelSpacing tag.
    """
    issues = []

    # Find JPEG SOI + APP0 marker (FFD8 FFE0)
    jpeg_start = dicom_bytes.find(b'\xff\xd8\xff\xe0')
    if jpeg_start == -1:
        return issues  # Not JPEG compressed

    try:
        offset = jpeg_start + 4
        app0_length = int.from_bytes(dicom_bytes[offset:offset+2], 'big')

        # Check JFIF signature
        if dicom_bytes[offset+2:offset+7] != b'JFIF\x00':
            return issues

        # JFIF version
        units = dicom_bytes[offset + 9]  # 0=no units, 1=DPI, 2=DPCM
        x_density = int.from_bytes(dicom_bytes[offset+10:offset+12], 'big')
        y_density = int.from_bytes(dicom_bytes[offset+12:offset+14], 'big')

        # Check for manipulated density
        if units == 0 and x_density == 1 and y_density == 1:
            # Normal: no density info
            pass
        elif units in (1, 2):
            # Has density info — cross-check with DICOM Pixel Spacing
            pixel_spacing = inst_tags.get("PixelSpacing", "")
            if pixel_spacing:
                try:
                    ps_parts = str(pixel_spacing).replace("\\", "/").split("/")
                    ps_x = float(ps_parts[0])
                    ps_y = float(ps_parts[1]) if len(ps_parts) > 1 else ps_x

                    # Convert JFIF density to mm/pixel
                    if units == 1:  # DPI
                        jfif_x_mm = 25.4 / x_density if x_density > 0 else 0
                        jfif_y_mm = 25.4 / y_density if y_density > 0 else 0
                    else:  # DPCM
                        jfif_x_mm = 10.0 / x_density if x_density > 0 else 0
                        jfif_y_mm = 10.0 / y_density if y_density > 0 else 0

                    # Compare with DICOM PixelSpacing (tolerance 10%)
                    if jfif_x_mm > 0 and ps_x > 0:
                        ratio = abs(jfif_x_mm - ps_x) / ps_x
                        if ratio > 0.1:  # >10% mismatch
                            issues.append({
                                "tag": "JFIF Density vs PixelSpacing",
                                "field": "JPEG_Density",
                                "risk_level": "risky",
                                "description": f"JPEG 밀도 조작 감지: JFIF {x_density}x{y_density} "
                                    f"({'DPI' if units==1 else 'DPCM'}) → {jfif_x_mm:.4f}mm vs "
                                    f"DICOM PixelSpacing {ps_x:.4f}mm ({ratio*100:.1f}% 불일치)",
                                "current_value": f"JFIF: {x_density}x{y_density}, PS: {pixel_spacing}",
                                "suggested_value": f"PixelSpacing 기준으로 JFIF 밀도 재설정",
                                "algorithm": "jpeg_density",
                                "auto_fixable": False,
                            })
                except (ValueError, IndexError):
                    pass

            # Suspicious non-standard density values
            if x_density != y_density and abs(x_density - y_density) > 10:
                issues.append({
                    "tag": "JFIF Density Asymmetry",
                    "field": "JPEG_Density",
                    "risk_level": "risky",
                    "description": f"JFIF 밀도 비대칭: X={x_density}, Y={y_density} — 비등방성 왜곡 가능",
                    "current_value": f"X={x_density}, Y={y_density}",
                    "suggested_value": "등방성 밀도로 수정 필요",
                    "algorithm": "jpeg_density",
                    "auto_fixable": False,
                })

        # Very high or very low density
        if x_density > 0 and (x_density > 10000 or (x_density < 10 and units in (1, 2))):
            issues.append({
                "tag": "JFIF Density Abnormal",
                "field": "JPEG_Density",
                "risk_level": "risky",
                "description": f"비정상 JFIF 밀도 값: {x_density}x{y_density} (units={units})",
                "current_value": f"{x_density}x{y_density}",
                "suggested_value": "장비 제조사 확인 필요",
                "algorithm": "jpeg_density",
                "auto_fixable": False,
            })

    except (IndexError, struct.error):
        pass

    return issues


# ─── Manufacturer-specific Pattern Detection ───

# Known non-standard patterns by manufacturer
_MANUFACTURER_PATTERNS = {
    "GE MEDICAL": [
        {"tag": "BurnedInAnnotation", "expected": "YES", "check": "missing",
         "desc": "GE 장비: BurnedInAnnotation 태그 누락 빈발", "risk": "safe"},
    ],
    "SIEMENS": [
        {"tag": "ImageType", "check": "contains_derived",
         "desc": "Siemens: DERIVED 이미지에 원본 PixelSpacing 유지 오류 빈발", "risk": "medium"},
    ],
    "FUJI": [
        {"tag": "PixelSpacing", "check": "fuji_cr_spacing",
         "desc": "Fuji CR: 스캔 밀도를 PixelSpacing에 잘못 기록하는 패턴", "risk": "risky"},
    ],
    "PHILIPS": [
        {"tag": "RescaleSlope", "check": "philips_rescale",
         "desc": "Philips: Private 태그에만 정확한 Rescale 값 저장 패턴", "risk": "medium"},
    ],
    "HOLOGIC": [
        {"tag": "WindowCenter", "check": "hologic_wl",
         "desc": "Hologic Mammography: 비표준 W/L 범위", "risk": "safe"},
    ],
    "SAMSUNG": [
        {"tag": "SpecificCharacterSet", "check": "samsung_charset",
         "desc": "Samsung: EUC-KR 인코딩 미선언 패턴", "risk": "safe"},
    ],
    "CARESTREAM": [
        {"tag": "PixelSpacing", "check": "carestream_spacing",
         "desc": "Carestream: NominalScannedPixelSpacing과 PixelSpacing 불일치 패턴", "risk": "risky"},
    ],
}

def _check_manufacturer_patterns(manufacturer: str, model: str, software: str, tags: dict) -> list:
    """Check for manufacturer-specific known non-standard patterns."""
    issues = []
    if not manufacturer:
        return issues

    for mfr_key, patterns in _MANUFACTURER_PATTERNS.items():
        if mfr_key in manufacturer:
            for p in patterns:
                tag_val = tags.get(p["tag"], "")
                matched = False

                if p["check"] == "missing" and not tag_val:
                    matched = True
                elif p["check"] == "contains_derived":
                    img_type = tags.get("ImageType", "")
                    ps = tags.get("PixelSpacing", "")
                    ips = tags.get("ImagerPixelSpacing", "")
                    if "DERIVED" in str(img_type) and ps and ips and ps != ips:
                        matched = True
                elif p["check"] == "fuji_cr_spacing":
                    ps = tags.get("PixelSpacing", "")
                    if ps:
                        try:
                            val = float(str(ps).split("\\")[0].split("/")[0])
                            if val < 0.01 or val > 5.0:  # abnormal range for CR
                                matched = True
                        except ValueError:
                            pass
                elif p["check"] == "philips_rescale":
                    rs = tags.get("RescaleSlope", "")
                    if rs and float(rs) == 1.0:
                        # Philips often stores real rescale in private tags
                        for k in tags:
                            if "2005" in k and "rescale" in k.lower():
                                matched = True
                                break
                elif p["check"] == "samsung_charset":
                    charset = tags.get("SpecificCharacterSet", "")
                    pn = tags.get("PatientName", "")
                    if not charset and pn and any(ord(c) > 127 for c in pn):
                        matched = True

                if matched:
                    issues.append({
                        "tag": f"{p['tag']} ({manufacturer})",
                        "field": p["tag"],
                        "risk_level": p["risk"],
                        "description": p["desc"],
                        "current_value": str(tag_val)[:50] if tag_val else "(없음)",
                        "suggested_value": "(제조사 패턴 기반 교정)",
                        "algorithm": "manufacturer_pattern",
                        "auto_fixable": p["risk"] == "safe",
                        "manufacturer": manufacturer,
                        "model": model,
                    })

    return issues


# ─── Mandatory DICOM Tags Check ───

_MANDATORY_TAGS = [
    ("PatientID", "환자 ID"),
    ("PatientName", "환자명"),
    ("StudyDate", "검사일"),
    ("Modality", "모달리티"),
    ("StudyInstanceUID", "Study UID"),
    ("SeriesInstanceUID", "Series UID"),
    ("SOPInstanceUID", "SOP Instance UID"),
    ("SOPClassUID", "SOP Class UID"),
    ("Rows", "행 수"),
    ("Columns", "열 수"),
    ("BitsAllocated", "비트 할당"),
    ("PhotometricInterpretation", "광도 해석"),
]

_RECOMMENDED_TAGS = [
    ("PatientBirthDate", "환자 생년월일"),
    ("PatientSex", "환자 성별"),
    ("StudyDescription", "검사 설명"),
    ("InstitutionName", "기관명"),
    ("ReferringPhysicianName", "의뢰 의사"),
    ("AccessionNumber", "접수번호"),
    ("BodyPartExamined", "검사 부위"),
]

def _check_mandatory_tags(tags: dict) -> list:
    """Check for missing mandatory and recommended DICOM tags."""
    issues = []
    for tag, label in _MANDATORY_TAGS:
        if not tags.get(tag):
            issues.append({
                "tag": tag,
                "field": tag,
                "risk_level": "medium",
                "description": f"필수 태그 누락: {label} ({tag})",
                "current_value": "(없음)",
                "suggested_value": "(값 필요)",
                "algorithm": "mandatory_tag_check",
                "auto_fixable": False,
            })

    for tag, label in _RECOMMENDED_TAGS:
        if not tags.get(tag):
            issues.append({
                "tag": tag,
                "field": tag,
                "risk_level": "safe",
                "description": f"권장 태그 누락: {label} ({tag})",
                "current_value": "(없음)",
                "suggested_value": "(입력 권장)",
                "algorithm": "recommended_tag_check",
                "auto_fixable": False,
            })

    return issues


# ─── MedGemma AI Analysis (Hybrid) ───

async def _medgemma_analyze(tags: dict, rule_issues: list, study_uid: str) -> list:
    """Use MedGemma to analyze DICOM metadata for additional non-standard patterns.

    Sends tag summary + rule-based findings to MedGemma for deeper analysis.
    Returns additional issues not caught by rules.
    """
    import httpx

    # 설정 외부화 — 소스 하드코딩 금지(기존 키는 노출되었으므로 운영자 회전 필요).
    AI_SERVER_URL = settings.ai_server_url
    AI_API_KEY = settings.ai_api_key

    # Build concise tag summary for AI
    tag_summary = {k: str(v)[:100] for k, v in tags.items()
                   if v and k not in ("PixelData", "OverlayData") and len(str(v)) < 200}

    rule_summary = [f"{i['tag']}: {i['description']}" for i in rule_issues[:10]]

    prompt = f"""You are a DICOM standards expert. Analyze these DICOM tags for non-standard issues.

DICOM Tags (key metadata):
Manufacturer: {tags.get('Manufacturer', 'unknown')}
Modality: {tags.get('Modality', 'unknown')}
TransferSyntaxUID: {tags.get('TransferSyntaxUID', '')}
PixelSpacing: {tags.get('PixelSpacing', '')}
ImagerPixelSpacing: {tags.get('ImagerPixelSpacing', '')}
SpecificCharacterSet: {tags.get('SpecificCharacterSet', '')}
BitsAllocated: {tags.get('BitsAllocated', '')}
BitsStored: {tags.get('BitsStored', '')}
PhotometricInterpretation: {tags.get('PhotometricInterpretation', '')}
WindowCenter: {tags.get('WindowCenter', '')}
WindowWidth: {tags.get('WindowWidth', '')}
RescaleSlope: {tags.get('RescaleSlope', '')}
RescaleIntercept: {tags.get('RescaleIntercept', '')}
ImageType: {tags.get('ImageType', '')}

Already detected issues:
{chr(10).join(rule_summary) if rule_summary else 'None'}

Find ADDITIONAL non-standard issues NOT already detected. Focus on:
1. Unusual BitsAllocated/BitsStored/HighBit combinations
2. PhotometricInterpretation mismatches with TransferSyntax
3. Suspicious Rescale values for the modality
4. Any other DICOM compliance issues

Respond in JSON array format only. Each item: {{"tag":"TagName","risk":"safe|medium|risky","description":"Korean description","suggestion":"fix suggestion"}}
If no additional issues found, respond with empty array: []"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{AI_SERVER_URL}/api/medical/analyze",
                headers={
                    "Authorization": f"Bearer {AI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "text": prompt,
                    "task": "dicom_compliance",
                    "study_uid": study_uid,
                },
            )

            if resp.status_code == 200:
                data = resp.json()
                ai_text = data.get("analysis", data.get("result", data.get("response", "")))
                if isinstance(ai_text, str):
                    # Extract JSON array from response
                    import json as json_mod
                    import re
                    json_match = re.search(r'\[.*\]', ai_text, re.DOTALL)
                    if json_match:
                        ai_items = json_mod.loads(json_match.group())
                        return [{
                            "tag": item.get("tag", "AI Detection"),
                            "field": item.get("tag", ""),
                            "risk_level": item.get("risk", "safe"),
                            "description": f"[AI] {item.get('description', '')}",
                            "current_value": "",
                            "suggested_value": item.get("suggestion", ""),
                            "algorithm": "medgemma_analysis",
                            "auto_fixable": False,
                        } for item in ai_items if isinstance(item, dict)]
                elif isinstance(ai_text, list):
                    return [{
                        "tag": item.get("tag", "AI Detection"),
                        "field": item.get("tag", ""),
                        "risk_level": item.get("risk", "safe"),
                        "description": f"[AI] {item.get('description', '')}",
                        "current_value": "",
                        "suggested_value": item.get("suggestion", ""),
                        "algorithm": "medgemma_analysis",
                        "auto_fixable": False,
                    } for item in ai_text if isinstance(item, dict)]
    except Exception as e:
        logger.debug("MedGemma analysis skipped: %s", e)

    return []
