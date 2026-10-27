"""DICOM Issue auto-fix logic — cascade fix, fix history, rollback, backup."""
import json
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import AuditLogger
from app.core.database import get_db
from app.core.security import RequireRole, get_current_user
from app.models.dicom_issue import DicomFixHistory
from app.models.user import Role, User
from app.models.validation import ValidationResult

logger = logging.getLogger(__name__)

fix_router = APIRouter()

# Rule resolution info: auto_fix capability, method, and guidance
RULE_RESOLUTION = {
    # ── Auto-fixable ──
    "MISSING_RECOMMENDED_TAG": {
        "auto_fixable": True,
        "fix_method": "기본값 삽입 (PatientBirthDate→00000000, PatientSex→O 등)",
        "guidance": "DICOM 표준 기본값을 삽입합니다. 실제 환자 정보는 HIS에서 확인 후 수동 수정하세요.",
        "risk": "safe",
    },
    "EMPTY_MANDATORY_TAG": {
        "auto_fixable": True,
        "fix_method": "안전한 기본값 삽입",
        "guidance": "빈 필수 태그에 표준 기본값을 채웁니다.",
        "risk": "safe",
    },
    "INVALID_DATE_FORMAT": {
        "auto_fixable": True,
        "fix_method": "날짜 형식을 YYYYMMDD로 변환",
        "guidance": "비표준 날짜 형식(예: 2005-11-30)을 DICOM 표준 YYYYMMDD(20051130)로 변환합니다.",
        "risk": "safe",
    },
    "INVALID_IS_VALUE": {
        "auto_fixable": True,
        "fix_method": "숫자 추출 후 정수 변환",
        "guidance": "문자열에서 숫자만 추출하여 정수값으로 변환합니다.",
        "risk": "safe",
    },
    "MISSING_CHARACTER_SET": {
        "auto_fixable": True,
        "fix_method": "Specific Character Set → ISO_IR 192 (UTF-8) 추가",
        "guidance": "비ASCII 문자(한글 등)가 있으나 문자셋 태그가 없어 UTF-8로 지정합니다.",
        "risk": "safe",
    },
    "UNKNOWN_CHARACTER_SET": {
        "auto_fixable": True,
        "fix_method": "Specific Character Set → ISO_IR 192 (UTF-8) 변경",
        "guidance": "알 수 없는 문자셋을 표준 UTF-8로 변경합니다.",
        "risk": "medium",
    },
    "JPEG_DENSITY_MISMATCH": {
        "auto_fixable": True,
        "fix_method": "JFIF 밀도에서 Pixel Spacing 재계산 (25.4/DPI)",
        "guidance": "JPEG 헤더의 DPI 값으로 정확한 Pixel Spacing을 계산하여 교정합니다. 측정값 정확도가 향상됩니다.",
        "risk": "safe",
    },
    "JPEG_DENSITY_NO_PIXEL_SPACING": {
        "auto_fixable": True,
        "fix_method": "JFIF 밀도에서 Pixel Spacing 계산 후 추가",
        "guidance": "JPEG 헤더에 밀도 정보가 있으므로 이를 기반으로 Pixel Spacing을 추가합니다.",
        "risk": "safe",
    },
    "MISSING_TRANSFER_SYNTAX": {
        "auto_fixable": True,
        "fix_method": "File Meta에 Transfer Syntax UID 추가 (Explicit VR Little Endian)",
        "guidance": "누락된 Transfer Syntax를 DICOM 기본값(1.2.840.10008.1.2.1)으로 추가합니다.",
        "risk": "safe",
    },
    "MISSING_FILE_META": {
        "auto_fixable": True,
        "fix_method": "File Meta Information 생성",
        "guidance": "누락된 File Meta Information을 DICOM 표준에 맞게 생성합니다.",
        "risk": "safe",
    },
    "PRIVATE_TAGS_PRESENT": {
        "auto_fixable": True,
        "fix_method": "사설 태그 제거 (remove_private_tags)",
        "guidance": "제조사 사설 태그를 제거합니다. 주의: 일부 장비의 보정 데이터가 손실될 수 있으나, 대부분의 경우 안전합니다.",
        "risk": "medium",
    },
    "UID_INVALID_CHARS": {
        "auto_fixable": True,
        "fix_method": "비표준 UID를 새 표준 UID로 교체",
        "guidance": "비표준 문자가 포함된 UID를 pydicom으로 새 표준 UID를 생성하여 교체합니다.",
        "risk": "medium",
    },
    "UID_TOO_LONG": {
        "auto_fixable": True,
        "fix_method": "UID를 새 표준 UID로 교체 (64자 이내)",
        "guidance": "64자를 초과하는 UID를 새로 생성합니다.",
        "risk": "medium",
    },
    # ── Not auto-fixable ──
    "PARSE_FAILURE": {
        "auto_fixable": False,
        "fix_method": None,
        "guidance": "DICOM 파일이 손상되어 파싱 불가합니다. 원본 장비에서 재전송하거나 파일을 교체해야 합니다.",
        "risk": "critical",
    },
    "MISSING_MANDATORY_TAG": {
        "auto_fixable": False,
        "fix_method": None,
        "guidance": "필수 태그(SOPInstanceUID, PatientID 등)가 완전히 누락되어 있습니다. 원본 장비에서 재전송해야 합니다.",
        "risk": "critical",
    },
    "JPEG_DEFAULT_DENSITY": {
        "auto_fixable": False,
        "fix_method": None,
        "guidance": "JPEG가 기본 1×1 DPI 밀도를 사용 중입니다. 정보성 이슈로, 측정 기능 사용 시 Pixel Spacing을 별도 확인하세요.",
        "risk": "info",
    },
    "JPEG_NONSQUARE_ASPECT": {
        "auto_fixable": False,
        "fix_method": None,
        "guidance": "JPEG 종횡비가 비정방형입니다. 의도된 설정인지 촬영 장비 담당자에게 확인하세요.",
        "risk": "info",
    },
    "UNKNOWN_PHOTOMETRIC": {
        "auto_fixable": False,
        "fix_method": None,
        "guidance": "알 수 없는 Photometric Interpretation입니다. 영상 표시에 문제가 있을 수 있으며, 장비 제조사에 문의하세요.",
        "risk": "warning",
    },
    "BITS_STORED_GT_ALLOCATED": {
        "auto_fixable": False,
        "fix_method": None,
        "guidance": "BitsStored가 BitsAllocated보다 큽니다. 하드웨어 레벨 문제로, 촬영 장비 설정을 점검하세요.",
        "risk": "error",
    },
    "MISSING_IMAGE_DIMENSIONS": {
        "auto_fixable": False,
        "fix_method": None,
        "guidance": "픽셀 데이터가 있으나 이미지 크기(Rows/Columns) 태그가 없습니다. 파일이 불완전하므로 재전송이 필요합니다.",
        "risk": "error",
    },
    "NON_RENDERABLE_ONLY": {
        "auto_fixable": False,
        "fix_method": None,
        "guidance": "이 스터디에는 렌더링 가능한 영상 시리즈가 없습니다(SR/PR만 존재). 원본 영상이 별도로 전송되었는지 확인하세요.",
        "risk": "warning",
    },
    "RETIRED_SOP_CLASS": {
        "auto_fixable": True,
        "fix_method": "Retired SOP Class UID를 현행 UID로 변환",
        "guidance": "폐기(Retired)된 SOP Class를 사용 중입니다. 현행 표준 UID로 변환하면 뷰어에서 정상 표시됩니다.",
        "risk": "safe",
    },
    "RETIRED_TRANSFER_SYNTAX": {
        "auto_fixable": True,
        "fix_method": "Retired Transfer Syntax를 Explicit VR Little Endian으로 변환",
        "guidance": "폐기(Retired)된 Transfer Syntax를 사용 중입니다. 현행 표준으로 변환하면 뷰어 호환성이 향상됩니다.",
        "risk": "safe",
    },
    "INVALID_STUDY_UID": {
        "auto_fixable": False,
        "fix_method": None,
        "guidance": "Study UID 형식이 DICOM 표준이 아닙니다. 뷰어에서 표시 불가하며, UID 정규화 또는 재전송이 필요합니다.",
        "risk": "error",
    },
}


def _apply_supplier_normalizer(ds, norm_result) -> str | None:
    """Detect manufacturer and apply supplier-specific normalizer.

    Bridges pydicom Dataset → dict-based SupplierNormalizer → apply changes back.
    Returns supplier name or None.
    """
    manufacturer = str(getattr(ds, "Manufacturer", "")).upper()
    if not manufacturer:
        return None

    from app.services.supplier_normalizer import (
        SiemensNormalizer, GENormalizer, PhilipsNormalizer, NormalizationChange,
    )
    from app.models.batch_job import NormalizationConfig

    # Detect supplier
    supplier = None
    if "SIEMENS" in manufacturer:
        supplier = "siemens"
    elif "GE" in manufacturer or "GENERAL ELECTRIC" in manufacturer or "G.E." in manufacturer:
        supplier = "ge"
    elif "PHILIPS" in manufacturer:
        supplier = "philips"

    if not supplier:
        return None

    # Build minimal config with all algorithms enabled
    config = NormalizationConfig(
        modality=str(getattr(ds, "Modality", "OT")),
        algorithms={"pixel_spacing": True, "photometric": True, "missing_tags": True},
        risk_tiers={"safe": "auto", "medium": "auto"},
    )

    # Create supplier normalizer
    normalizer_map = {
        "siemens": SiemensNormalizer,
        "ge": GENormalizer,
        "philips": PhilipsNormalizer,
    }
    SupNorm = normalizer_map[supplier]
    sup_norm = SupNorm(config, supplier)

    # Convert pydicom Dataset → dict for supplier normalizer
    file_data = {}
    for elem in ds:
        tag_str = f"{elem.tag.group:04X},{elem.tag.element:04X}".lower()
        try:
            file_data[tag_str] = elem.value
        except Exception:
            pass
    # Add file meta tags
    if hasattr(ds, "file_meta") and ds.file_meta:
        for elem in ds.file_meta:
            tag_str = f"{elem.tag.group:04X},{elem.tag.element:04X}".lower()
            try:
                file_data[tag_str] = elem.value
            except Exception:
                pass

    # Run supplier normalizer
    try:
        sup_changes = sup_norm.normalize(file_data)
    except Exception as e:
        logger.warning(f"Supplier normalizer ({supplier}) failed: {e}")
        return supplier

    if not sup_changes:
        return supplier

    # Apply changes back to Dataset
    from app.services.dicom_normalizer import ChangeSummary
    for change in sup_changes:
        if change.risk_level == "safe":
            # Parse tag "0028,0030" → (0x0028, 0x0030)
            try:
                parts = change.tag.split(",")
                group = int(parts[0], 16)
                element = int(parts[1], 16)
                tag = (group, element)
                if tag in ds:
                    ds[tag].value = change.corrected
                else:
                    # Need VR to add new tag — use pydicom's data dictionary
                    from pydicom.datadict import keyword_for_tag, dictionary_VR
                    vr = dictionary_VR((group, element)) if (group, element) in ds else "LO"
                    ds.add_new(tag, vr, change.corrected)
            except Exception as e:
                logger.debug(f"Supplier fix apply failed for {change.tag}: {e}")
                continue

            norm_result.modified = True
            norm_result.changes.append(ChangeSummary(
                tag_keyword=change.tag,
                original_value=str(change.original) if change.original else None,
                corrected_value=str(change.corrected),
                rationale=change.rationale,
                risk_level=change.risk_level,
                category="supplier",
            ))

    return supplier


def _apply_extra_fixes(ds, rule_code: str, report) -> list[tuple[str, str | None, str, str]]:
    """Apply additional fixes not covered by DicomNormalizer. Returns [(tag, orig, fixed, rationale)]."""
    import re
    changes = []

    if rule_code == "PRIVATE_TAGS_PRESENT":
        # Count private groups before removal
        private_groups = set()
        for elem in ds:
            if elem.tag.group % 2 == 1 and elem.tag.group > 0x0008:
                private_groups.add(f"({elem.tag.group:04X},xxxx)")
        if private_groups:
            ds.remove_private_tags()
            changes.append(("PrivateTags", f"{len(private_groups)} groups", "removed", "사설 태그 제거 완료"))

    elif rule_code == "INVALID_DATE_FORMAT":
        date_tags = [(0x0008, 0x0020, "StudyDate"), (0x0008, 0x0021, "SeriesDate")]
        for group, elem, name in date_tags:
            tag = (group, elem)
            if tag in ds and ds[tag].value:
                val = str(ds[tag].value)
                if len(val) != 8 or not val.isdigit():
                    # Try to parse common formats
                    cleaned = re.sub(r'[^0-9]', '', val)
                    if len(cleaned) >= 8:
                        fixed = cleaned[:8]
                        ds[tag].value = fixed
                        changes.append((name, val, fixed, f"날짜 형식 {val} → {fixed} 변환"))

    elif rule_code == "INVALID_IS_VALUE":
        is_tags = [(0x0020, 0x0013, "InstanceNumber"), (0x0020, 0x0011, "SeriesNumber")]
        for group, elem, name in is_tags:
            tag = (group, elem)
            if tag in ds and ds[tag].value:
                val = str(ds[tag].value).strip()
                try:
                    int(val)
                except ValueError:
                    digits = re.sub(r'[^0-9\\-]', '', val)
                    fixed = digits if digits else "1"
                    ds[tag].value = fixed
                    changes.append((name, val, fixed, f"정수 아닌 값 '{val}' → '{fixed}' 변환"))

    elif rule_code in ("UID_INVALID_CHARS", "UID_TOO_LONG"):
        from pydicom.uid import generate_uid
        uid_tags = [
            ((0x0008, 0x0018), "SOPInstanceUID"),
            ((0x0020, 0x000D), "StudyInstanceUID"),
            ((0x0020, 0x000E), "SeriesInstanceUID"),
        ]
        for tag, name in uid_tags:
            if tag in ds:
                uid = str(ds[tag].value)
                bad = (len(uid) > 64) or not all(c in "0123456789." for c in uid)
                if bad:
                    new_uid = generate_uid()
                    ds[tag].value = new_uid
                    changes.append((name, uid[:40] + "...", str(new_uid), f"비표준 UID → 새 표준 UID 생성"))

    elif rule_code == "RETIRED_SOP_CLASS":
        from app.services.dicom_validator import DicomValidator as DV
        sop = str(getattr(ds, "SOPClassUID", ""))
        if sop in DV.RETIRED_SOP_MAP:
            new_sop = DV.RETIRED_SOP_MAP[sop]
            ds.SOPClassUID = new_sop
            # Also update MediaStorageSOPClassUID in file meta
            if hasattr(ds, "file_meta") and ds.file_meta:
                ds.file_meta.MediaStorageSOPClassUID = new_sop
            changes.append(("SOPClassUID", sop, new_sop, f"Retired → Current SOP Class 변환"))

    elif rule_code == "RETIRED_TRANSFER_SYNTAX":
        if hasattr(ds, "file_meta") and ds.file_meta:
            ts = str(getattr(ds.file_meta, "TransferSyntaxUID", ""))
            from pydicom.uid import ExplicitVRLittleEndian
            if ts in ("1.2.840.10008.1.2.2", "1.2.840.10008.1.2.1.99"):
                ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                ds.is_little_endian = True
                ds.is_implicit_VR = False
                changes.append(("TransferSyntaxUID", ts, str(ExplicitVRLittleEndian),
                                f"Retired TS → Explicit VR Little Endian 변환"))

    elif rule_code == "MISSING_CHARACTER_SET":
        if (0x0008, 0x0005) not in ds:
            ds.add_new((0x0008, 0x0005), "CS", "ISO_IR 192")
            changes.append(("SpecificCharacterSet", None, "ISO_IR 192", "UTF-8 문자셋 추가"))

    elif rule_code == "UNKNOWN_CHARACTER_SET":
        ds[0x0008, 0x0005].value = "ISO_IR 192"
        changes.append(("SpecificCharacterSet", str(ds[0x0008, 0x0005].value), "ISO_IR 192", "문자셋을 UTF-8로 변경"))

    elif rule_code == "MISSING_FILE_META":
        if not hasattr(ds, 'file_meta') or ds.file_meta is None:
            from pydicom.dataset import FileMetaDataset
            from pydicom.uid import ExplicitVRLittleEndian, generate_uid
            ds.file_meta = FileMetaDataset()
            ds.file_meta.MediaStorageSOPClassUID = getattr(ds, 'SOPClassUID', '1.2.840.10008.5.1.4.1.1.2')
            ds.file_meta.MediaStorageSOPInstanceUID = getattr(ds, 'SOPInstanceUID', generate_uid())
            ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
            ds.is_little_endian = True
            ds.is_implicit_VR = False
            changes.append(("FileMetaInformation", None, "created", "File Meta Information 생성"))

    elif rule_code == "MISSING_TRANSFER_SYNTAX":
        if hasattr(ds, 'file_meta') and ds.file_meta is not None:
            from pydicom.uid import ExplicitVRLittleEndian
            if not hasattr(ds.file_meta, 'TransferSyntaxUID') or not ds.file_meta.TransferSyntaxUID:
                ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                changes.append(("TransferSyntaxUID", None, "1.2.840.10008.1.2.1", "Explicit VR Little Endian 추가"))

    return changes


async def _cascade_fix_sop(
    sop_uid: str, orthanc_id: str, client, db: AsyncSession, user, rule_codes: list[str] | None = None,
) -> dict:
    """Core cascade fix: fix ALL issues for a SOP instance in one pass.

    1. Fetch DICOM  2. Backup original hash  3. Apply all fixable rules
    4. Re-upload  5. Re-validate  6. Record fix_history  7. Delete resolved / mark remaining
    """
    import hashlib
    import io
    import pydicom
    from app.services.dicom_validator import DicomValidator
    from app.services.dicom_normalizer import DicomNormalizer, ChangeSummary

    validator = DicomValidator()
    normalizer = DicomNormalizer()

    # 1. Fetch
    file_resp = await client.get(f"/instances/{orthanc_id}/file")
    if file_resp.status_code != 200:
        return {"error": f"Orthanc fetch failed: {file_resp.status_code}"}

    raw_data = file_resp.content
    original_hash = hashlib.sha256(raw_data).hexdigest()

    # 2. Validate
    report = validator.validate(raw_data)
    ds = pydicom.dcmread(io.BytesIO(raw_data), force=True)

    # 3. Apply DicomNormalizer
    norm_result = await normalizer.normalize(ds, report, raw_data)

    # 3a. Apply supplier-specific normalizer (Siemens/GE/Philips)
    supplier_name = _apply_supplier_normalizer(ds, norm_result)

    # 3b. Apply extra fixes for ALL fixable rule_codes (cascade)
    target_rules = rule_codes or [f.rule_code for f in report.findings]
    for rc in target_rules:
        if RULE_RESOLUTION.get(rc, {}).get("auto_fixable", False):
            extras = _apply_extra_fixes(ds, rc, report)
            if extras:
                norm_result.modified = True
                for tag, orig, fixed, rationale in extras:
                    norm_result.changes.append(ChangeSummary(
                        tag_keyword=tag, original_value=orig, corrected_value=fixed,
                        rationale=rationale, risk_level="safe", category="tag",
                    ))

    if not norm_result.modified:
        return {"fixed": False, "reason": "자동수정 대상 없음", "changes": []}

    # K2: TransferSyntax/VR/endian을 바꾼 경우 write_like_original=True는 본문을 새 인코딩으로
    # 재직렬화하지 않아 메타-본문 불일치(손상). 해당 시 False로 pydicom이 file_meta 기준 재직렬화.
    _ts_changed = any(c.tag_keyword == "TransferSyntaxUID" for c in norm_result.changes)
    _wlo = not _ts_changed

    # 4. Delete old instance + Re-upload (Orthanc won't overwrite same SOP UID)
    try:
        await client.delete(f"/instances/{orthanc_id}")
    except Exception:
        pass  # May fail if already deleted, that's OK

    output = io.BytesIO()
    ds.save_as(output, write_like_original=_wlo)
    output.seek(0)
    upload_resp = await client.post("/instances", content=output.read(),
                                    headers={"Content-Type": "application/dicom"})
    if upload_resp.status_code not in (200, 409):
        # 재업로드 실패 — 원본은 이미 삭제됨. 원본 바이트(raw_data)로 즉시 복원(소실 방지).
        try:
            await client.post("/instances", content=raw_data,
                              headers={"Content-Type": "application/dicom"})
            logger.error(f"Re-upload failed ({upload_resp.status_code}); restored original {sop_uid}")
        except Exception as e:
            logger.error(f"CRITICAL: re-upload AND original-restore failed for {sop_uid}: {e}")
        return {"error": f"Re-upload failed: {upload_resp.status_code} (원본 복원 시도됨)"}

    # 수정본 instance ID 캡처(롤백 시 삭제용 — UID 재작성 시 backup_orthanc_id와 다름)
    fixed_orthanc_id = None
    try:
        fixed_orthanc_id = upload_resp.json().get("ID")
    except Exception:
        pass

    # 5. Re-validate
    output2 = io.BytesIO()
    ds.save_as(output2, write_like_original=_wlo)
    output2.seek(0)
    post_report = validator.validate(output2.read())
    post_rules = {f.rule_code for f in post_report.findings}
    pre_rules = {f.rule_code for f in report.findings}
    resolved_rules = pre_rules - post_rules

    changes_summary = [
        {"tag": c.tag_keyword, "original": c.original_value, "corrected": c.corrected_value,
         "rationale": c.rationale, "risk_level": c.risk_level}
        for c in norm_result.changes
    ]

    # 6. Record fix_history
    study_uid = report.study_instance_uid or sop_uid
    # 원본 바이트 보존(롤백 신뢰 소스) — 단일 인스턴스 상한 64MB 내에서만. 초과 시 hash만.
    _MAX_BACKUP = 64 * 1024 * 1024
    backup_bytes = raw_data if len(raw_data) <= _MAX_BACKUP else None
    if backup_bytes is None:
        logger.warning(f"original_data not stored ({len(raw_data)}B > cap) for {sop_uid} — rollback limited")
    db.add(DicomFixHistory(
        study_instance_uid=study_uid,
        sop_instance_uid=sop_uid,
        rule_codes=list(resolved_rules | (pre_rules - resolved_rules)),
        changes=changes_summary,
        original_hash=original_hash,
        backup_orthanc_id=orthanc_id,
        original_data=backup_bytes,
        fixed_orthanc_id=fixed_orthanc_id,
        fix_status="applied",
        post_validation={"resolved": list(resolved_rules), "remaining": list(post_rules)},
        manufacturer=report.manufacturer or None,
        supplier_normalizer=supplier_name,
        fixed_by=user.id,
    ))

    # 7. Delete resolved issues, mark remaining
    from sqlalchemy import delete as sa_delete
    if resolved_rules:
        await db.execute(
            sa_delete(ValidationResult).where(
                ValidationResult.sop_instance_uid == sop_uid,
                ValidationResult.rule_code.in_(resolved_rules),
            )
        )
    if post_rules:
        await db.execute(
            update(ValidationResult).where(
                ValidationResult.sop_instance_uid == sop_uid,
                ValidationResult.issue_status == "unreviewed",
                ValidationResult.rule_code.in_(post_rules),
            ).values(
                issue_status="auto_fixed", auto_fixed=True,
                fix_description=f"수정 적용됨, 이슈 잔존: {', '.join(post_rules)}",
                reviewer_id=user.id, reviewed_at=datetime.now(timezone.utc),
            )
        )

    await db.commit()

    # Alert on auto-fix completion
    if resolved_rules:
        try:
            from app.services.alert_service import alert_dicom_auto_fix
            import asyncio
            asyncio.create_task(alert_dicom_auto_fix(
                study_uid=study_uid, fixed_count=len(changes_summary), resolved_count=len(resolved_rules),
            ))
        except Exception:
            pass

    return {
        "fixed": True,
        "resolved": list(resolved_rules),
        "remaining": list(post_rules),
        "changes": changes_summary,
        "elapsed_ms": norm_result.elapsed_ms,
    }


async def _find_orthanc_id(client, sop_uid: str) -> str | None:
    """Find Orthanc instance ID by SOP Instance UID."""
    try:
        resp = await client.post("/tools/find", json={
            "Level": "Instance", "Query": {"SOPInstanceUID": sop_uid},
        })
        ids = resp.json() if resp.status_code == 200 else []
        return ids[0] if ids else None
    except Exception:
        return None


@fix_router.post("/auto-fix/{issue_id}")
async def auto_fix_issue(
    issue_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Auto-fix a single issue (cascades to fix all issues for same SOP)."""
    result = await db.execute(select(ValidationResult).where(ValidationResult.id == issue_id))
    issue = result.scalar_one_or_none()
    if not issue:
        return {"error": "Issue not found"}

    rule_info = RULE_RESOLUTION.get(issue.rule_code, {})
    if not rule_info.get("auto_fixable", False):
        return {"ok": True, "fixed": False, "auto_fixable": False,
                "reason": rule_info.get("guidance", "자동수정 대상이 아닙니다."), "changes": []}

    client = request.app.state.http_client
    orthanc_id = issue.orthanc_id or await _find_orthanc_id(client, issue.sop_instance_uid)
    if not orthanc_id:
        return {"error": "Instance not found in Orthanc"}

    try:
        fix_result = await _cascade_fix_sop(issue.sop_instance_uid, orthanc_id, client, db, user)
        if fix_result.get("error"):
            return fix_result
        return {
            "ok": True, **fix_result,
            "resolved": len(fix_result.get("resolved", [])) > 0 and issue.rule_code in fix_result.get("resolved", []),
            "message": f"수정 완료: {len(fix_result.get('resolved',[]))}건 해소, {len(fix_result.get('remaining',[]))}건 잔존",
        }
    except Exception as e:
        logger.error(f"Auto-fix failed for {issue_id}: {e}")
        try: await db.rollback()
        except Exception: pass
        return {"error": f"Auto-fix failed: {str(e)}"}


@fix_router.post("/auto-fix-all")
async def auto_fix_all(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    severity: str = Query("warning,error,info", description="Target severities"),
    limit: int = Query(50, ge=1, le=200),
):
    """Batch cascade auto-fix: group by SOP, fix all at once."""
    sevs = [s.strip() for s in severity.split(",")]
    result = await db.execute(
        select(ValidationResult).where(
            ValidationResult.issue_status == "unreviewed", ValidationResult.severity.in_(sevs),
        ).order_by(ValidationResult.created_at).limit(limit)
    )
    issues = result.scalars().all()
    if not issues:
        return {"ok": True, "processed": 0, "fixed": 0, "skipped": 0, "resolved_total": 0}

    client = request.app.state.http_client
    seen_sop = set()
    processed = 0; fixed = 0; skipped = 0; resolved_total = 0

    for issue in issues:
        if issue.sop_instance_uid in seen_sop:
            continue
        seen_sop.add(issue.sop_instance_uid)

        # Collect all rule_codes for this SOP
        sop_rules = [i.rule_code for i in issues if i.sop_instance_uid == issue.sop_instance_uid]
        fixable_rules = [r for r in sop_rules if RULE_RESOLUTION.get(r, {}).get("auto_fixable", False)]
        if not fixable_rules:
            skipped += 1
            continue

        orthanc_id = issue.orthanc_id or await _find_orthanc_id(client, issue.sop_instance_uid)
        if not orthanc_id:
            skipped += 1
            continue

        try:
            fix_result = await _cascade_fix_sop(issue.sop_instance_uid, orthanc_id, client, db, user, fixable_rules)
            processed += 1
            if fix_result.get("fixed"):
                fixed += 1
                resolved_total += len(fix_result.get("resolved", []))
            else:
                skipped += 1
        except Exception as e:
            logger.warning(f"Auto-fix failed for {issue.sop_instance_uid}: {e}")
            try: await db.rollback()
            except Exception: pass
            skipped += 1

    return {"ok": True, "processed": processed, "fixed": fixed, "skipped": skipped, "resolved_total": resolved_total}


# ─── AI-Assisted Fix Suggestion ──────────────────────────────────────────────

@fix_router.post("/ai-suggest/{issue_id}")
async def ai_suggest_fix(
    issue_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """AI suggests a fix for issues that can't be auto-fixed.

    Uses WeRU.B AI to analyze the DICOM instance and propose corrections.
    For MISSING_MANDATORY_TAG: tries to infer values from other instances in same study.
    For UNKNOWN_PHOTOMETRIC: analyzes pixel data to determine correct value.
    For BITS_STORED_GT_ALLOCATED: inspects actual bit range.
    """
    result = await db.execute(select(ValidationResult).where(ValidationResult.id == issue_id))
    issue = result.scalar_one_or_none()
    if not issue:
        return {"error": "Issue not found"}

    client = request.app.state.http_client
    suggestions = []

    # Strategy 1: Infer from sibling instances in same study
    if issue.rule_code == "MISSING_MANDATORY_TAG":
        tag_name = issue.details.get("name", "") if issue.details else ""
        tag_hex = issue.details.get("tag", "") if issue.details else ""

        # Search other instances in same study for the missing tag
        try:
            find_resp = await client.post("/tools/find", json={
                "Level": "Instance",
                "Query": {"StudyInstanceUID": issue.study_instance_uid},
            })
            inst_ids = find_resp.json() if find_resp.status_code == 200 else []

            for inst_id in inst_ids[:10]:
                tags_resp = await client.get(f"/instances/{inst_id}/simplified-tags")
                if tags_resp.status_code == 200:
                    tags = tags_resp.json()
                    val = tags.get(tag_name)
                    if val:
                        suggestions.append({
                            "method": "sibling_inference",
                            "source": f"Same study, instance {inst_id[:8]}",
                            "tag": tag_name,
                            "suggested_value": str(val),
                            "confidence": "high",
                            "rationale": f"같은 Study의 다른 인스턴스에서 {tag_name}={val}을 발견했습니다.",
                        })
                        break
        except Exception:
            pass

        # If no sibling found, suggest defaults
        if not suggestions:
            defaults = {
                "PatientID": f"AUTO_{issue.study_instance_uid[-8:]}",
                "SOPInstanceUID": None,  # Must generate
                "SOPClassUID": "1.2.840.10008.5.1.4.1.1.7",  # SC
                "StudyInstanceUID": None,
                "SeriesInstanceUID": None,
                "Modality": "OT",
            }
            if tag_name in defaults and defaults[tag_name]:
                suggestions.append({
                    "method": "default_value",
                    "tag": tag_name,
                    "suggested_value": defaults[tag_name],
                    "confidence": "low",
                    "rationale": f"기본값 {defaults[tag_name]}을 제안합니다. 실제 값은 수동 확인이 필요합니다.",
                })

    # Strategy 2: Analyze pixel data for photometric/bits issues
    elif issue.rule_code in ("UNKNOWN_PHOTOMETRIC", "BITS_STORED_GT_ALLOCATED", "MISSING_IMAGE_DIMENSIONS"):
        orthanc_id = issue.orthanc_id or await _find_orthanc_id(client, issue.sop_instance_uid)
        if orthanc_id:
            try:
                import io
                import pydicom
                file_resp = await client.get(f"/instances/{orthanc_id}/file")
                if file_resp.status_code == 200:
                    ds = pydicom.dcmread(io.BytesIO(file_resp.content), force=True)

                    if issue.rule_code == "UNKNOWN_PHOTOMETRIC":
                        spp = getattr(ds, "SamplesPerPixel", 1)
                        bits = getattr(ds, "BitsAllocated", 8)
                        suggested = "RGB" if spp == 3 else "MONOCHROME2" if bits > 1 else "MONOCHROME1"
                        suggestions.append({
                            "method": "pixel_analysis",
                            "tag": "PhotometricInterpretation",
                            "suggested_value": suggested,
                            "confidence": "medium",
                            "rationale": f"SamplesPerPixel={spp}, BitsAllocated={bits}로부터 {suggested} 추론",
                        })

                    elif issue.rule_code == "BITS_STORED_GT_ALLOCATED":
                        bits_stored = getattr(ds, "BitsStored", 0)
                        # Round up to next power of 2
                        import math
                        new_allocated = 2 ** math.ceil(math.log2(max(bits_stored, 1)))
                        suggestions.append({
                            "method": "bit_analysis",
                            "tag": "BitsAllocated",
                            "suggested_value": str(new_allocated),
                            "confidence": "high",
                            "rationale": f"BitsStored={bits_stored}이므로 BitsAllocated={new_allocated}으로 수정 제안",
                        })

                    elif issue.rule_code == "MISSING_IMAGE_DIMENSIONS":
                        if hasattr(ds, "PixelData") and ds.PixelData:
                            pixel_len = len(ds.PixelData)
                            bits = getattr(ds, "BitsAllocated", 16)
                            spp = getattr(ds, "SamplesPerPixel", 1)
                            bytes_per_pixel = (bits // 8) * spp
                            if bytes_per_pixel > 0:
                                total_pixels = pixel_len // bytes_per_pixel
                                import math
                                side = int(math.sqrt(total_pixels))
                                suggestions.append({
                                    "method": "pixel_size_inference",
                                    "tag": "Rows/Columns",
                                    "suggested_value": f"{side}x{side}",
                                    "confidence": "low",
                                    "rationale": f"PixelData={pixel_len}bytes, {bytes_per_pixel}bytes/pixel → {total_pixels}px → {side}x{side} 추정 (정방형 가정)",
                                })
            except Exception as e:
                logger.warning(f"AI suggest pixel analysis failed: {e}")

    # Strategy 3: AI text analysis for complex cases
    if not suggestions or all(s["confidence"] == "low" for s in suggestions):
        try:
            from app.core.config import settings
            import httpx as hx
            ai_prompt = f"""DICOM 파일에 다음 이슈가 있습니다:
- 규칙: {issue.rule_code}
- 메시지: {issue.message}
- 모달리티: {issue.modality or 'unknown'}
- 제조사: {issue.manufacturer or 'unknown'}
- 상세: {json.dumps(issue.details or {}, ensure_ascii=False)}

이 이슈를 해결하기 위한 구체적인 방법을 한국어로 제안해주세요.
1. 가장 가능성 높은 원인
2. 권장 수정 방법
3. 주의사항"""

            async with hx.AsyncClient(timeout=30) as ac:
                resp = await ac.post(
                    f"{settings.ai_server_url}/api/chat",
                    json={"model": "medgemma", "messages": [{"role": "user", "content": ai_prompt}], "stream": False},
                    headers={"Authorization": f"Bearer {settings.ai_api_key}"},
                )
                if resp.status_code == 200:
                    ai_data = resp.json()
                    ai_text = ai_data.get("message", {}).get("content", "") or ai_data.get("response", "")
                    if ai_text:
                        suggestions.append({
                            "method": "ai_analysis",
                            "tag": issue.rule_code,
                            "suggested_value": None,
                            "confidence": "ai",
                            "rationale": ai_text[:1000],
                        })
        except Exception as e:
            logger.debug(f"AI suggestion call failed: {e}")

    # Update issue with suggestion
    if suggestions:
        issue.reviewer_note = f"AI 제안: {suggestions[0].get('rationale', '')[:200]}"
        await db.commit()

    return {
        "ok": True,
        "issue_id": str(issue.id),
        "rule_code": issue.rule_code,
        "suggestions": suggestions,
        "total": len(suggestions),
    }


# ─── Fix History + Rollback ──────────────────────────────────────────────────

@fix_router.get("/fix-history")
async def list_fix_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List auto-fix history with rollback info."""
    q = select(DicomFixHistory).order_by(DicomFixHistory.fixed_at.desc())
    total_q = await db.execute(select(func.count()).select_from(DicomFixHistory))
    total = total_q.scalar() or 0
    result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    rows = result.scalars().all()

    return {
        "total": total, "page": page,
        "history": [
            {
                "id": str(h.id),
                "study_instance_uid": h.study_instance_uid,
                "sop_instance_uid": h.sop_instance_uid,
                "rule_codes": h.rule_codes,
                "changes": h.changes,
                "original_hash": h.original_hash,
                "fix_status": h.fix_status,
                "post_validation": h.post_validation,
                "manufacturer": h.manufacturer,
                "fixed_at": h.fixed_at.isoformat() if h.fixed_at else None,
                "rolled_back_at": h.rolled_back_at.isoformat() if h.rolled_back_at else None,
            }
            for h in rows
        ],
    }


@fix_router.post("/rollback/{fix_id}")
@AuditLogger.log("DICOM_FIX_ROLLBACK", "DicomFixHistory")
async def rollback_fix(
    fix_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Rollback an auto-fix by re-fetching original from Orthanc backup."""
    result = await db.execute(select(DicomFixHistory).where(DicomFixHistory.id == fix_id))
    history = result.scalar_one_or_none()
    if not history:
        return {"error": "Fix history not found"}
    if history.fix_status == "rolled_back":
        return {"error": "Already rolled back"}

    import hashlib
    client = request.app.state.http_client
    restored = False
    # K1: 실제 원본 복원 — original_data(DB 보존 바이트)가 신뢰 소스. Orthanc instance ID
    # 변화·UID 재작성에 무관. (구 backup_orthanc_id는 삭제/수정본을 가리켜 신뢰 불가.)
    if history.original_data:
        # 무결성 확인
        if history.original_hash and hashlib.sha256(history.original_data).hexdigest() != history.original_hash:
            return {"error": "백업 무결성 검증 실패(hash 불일치) — 롤백 중단"}
        # 1) 수정본 삭제(원본 SOP UID와 충돌 방지 + UID 재작성 잔재 제거)
        for oid in {history.fixed_orthanc_id, history.backup_orthanc_id}:
            if oid:
                try:
                    await client.delete(f"/instances/{oid}")
                except Exception:
                    pass
        # 2) 원본 바이트 재업로드 → 원본 인스턴스 실제 복원
        try:
            up = await client.post("/instances", content=history.original_data,
                                   headers={"Content-Type": "application/dicom"})
            if up.status_code not in (200, 409):
                return {"error": f"원본 재업로드 실패: {up.status_code}"}
            restored = True
            restored_oid = None
            try:
                restored_oid = up.json().get("ID")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"CRITICAL: rollback original restore failed for {history.sop_instance_uid}: {e}")
            return {"error": f"원본 복원 실패: {e}"}
        # 3) 복원된 원본 재검증 → 이슈 재생성(original_data로 직접, Orthanc 재조회 불요)
        try:
            from app.services.dicom_validator import DicomValidator
            report = DicomValidator().validate(history.original_data)
            for f in report.findings:
                db.add(ValidationResult(
                    sop_instance_uid=report.sop_instance_uid,
                    study_instance_uid=report.study_instance_uid,
                    series_instance_uid=report.series_instance_uid,
                    orthanc_id=restored_oid or history.backup_orthanc_id,
                    ae_title=(report.ae_title or "")[:16] or None,
                    modality=(report.modality or "")[:16] or None,
                    manufacturer=(report.manufacturer or "")[:64] or None,
                    severity=f.severity.value, category=f.category.value,
                    rule_code=f.rule_code, message=f.message[:2000] if f.message else "",
                    details=f.details, auto_fixed=False, issue_status="unreviewed",
                ))
        except Exception as e:
            logger.warning(f"Rollback re-validate failed: {e}")
    else:
        # 레거시(original_data 없는 구 기록) — 원본 바이트가 없어 실제 복원 불가.
        return {"error": "이 수정 기록에는 원본 백업이 없어 복원할 수 없습니다(구 기록). "
                         "원본 바이트 보존은 K1 수정 이후 생성된 기록만 가능."}

    history.fix_status = "rolled_back"
    history.rolled_back_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "fix_id": str(history.id), "status": "rolled_back", "restored": restored}
