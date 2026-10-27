"""정규화 검토 "승인=적용"(v2 Step C) — 캐논 change를 SOP 인스턴스에 in-place 적용.

★서버는 `dicom_issues`를 단일파일로, repo는 패키지로 운영하는 구조 드리프트가 있어(메모리 참조),
이 어댑터는 그 드리프트와 무관한 **신규 공유 모듈**에 둔다(양쪽 동일 배포). dicom_issues fix.py 패턴을
재사용하되 의존하지 않는다.

원본 바이트를 `DicomFixHistory.original_data`에 보존하므로(K1 선례) 기존 dicom_issues rollback이
그대로 되돌릴 수 있다(롤백은 DicomFixHistory 행 단위라 단일파일/패키지 무관).
SOPInstanceUID는 유지(report/prior 참조 불변). changes는 is_applicable_change=True인 것만 받는다.
"""
import hashlib
import io
import logging

from app.models.dicom_issue import DicomFixHistory

logger = logging.getLogger(__name__)

_MAX_BACKUP = 64 * 1024 * 1024  # 64MB — 원본 바이트 보존 상한(초과 시 hash만, 롤백 제한)


async def _find_orthanc_instance(client, sop_uid: str) -> str | None:
    try:
        resp = await client.post("/tools/find", json={
            "Level": "Instance", "Query": {"SOPInstanceUID": sop_uid},
        })
        ids = resp.json() if resp.status_code == 200 else []
        return ids[0] if ids else None
    except Exception:
        return None


async def apply_canonical_changes(db, client, sop_uid: str, changes: list[dict], actor_id=None) -> dict:
    """캐논 change(tag="GGGG,EEEE"/corrected)를 SOP에 in-place 적용 + 원본 백업.

    반환: {"applied":[...], "fixed_orthanc_id":..., "history_id":...} 또는 {"error": "..."}.
    """
    import pydicom
    from pydicom.datadict import dictionary_VR
    from pydicom.tag import Tag

    orthanc_id = await _find_orthanc_instance(client, sop_uid)
    if not orthanc_id:
        return {"error": "Orthanc 인스턴스를 찾을 수 없습니다(삭제/이동).", "sop": sop_uid}

    file_resp = await client.get(f"/instances/{orthanc_id}/file")
    if file_resp.status_code != 200:
        return {"error": f"원본 조회 실패: {file_resp.status_code}"}
    raw_data = file_resp.content
    original_hash = hashlib.sha256(raw_data).hexdigest()
    ds = pydicom.dcmread(io.BytesIO(raw_data), force=True)

    applied: list[dict] = []
    for c in changes:
        parts = str(c.get("tag", "")).split(",")
        if len(parts) != 2:
            continue
        try:
            tag = Tag(int(parts[0], 16), int(parts[1], 16))
        except ValueError:
            continue
        try:
            vr = dictionary_VR(tag)
        except Exception:
            vr = "LO"
        try:
            ds.add_new(tag, vr, c.get("corrected"))   # 기존 element 덮어쓰기 또는 추가
            applied.append({"tag": str(c.get("tag")), "corrected": c.get("corrected"), "vr": vr})
        except Exception as ex:
            logger.warning(f"normalization apply {c.get('tag')} failed for {sop_uid}: {ex}")

    if not applied:
        return {"error": "적용 가능한 변경이 없습니다."}

    # delete old + re-upload — Orthanc는 동일 SOP UID를 덮어쓰지 않으므로 삭제 후 재업로드(UID 유지).
    try:
        await client.delete(f"/instances/{orthanc_id}")
    except Exception:
        pass
    output = io.BytesIO()
    ds.save_as(output, write_like_original=True)
    output.seek(0)
    up = await client.post("/instances", content=output.read(), headers={"Content-Type": "application/dicom"})
    if up.status_code not in (200, 409):
        # 재업로드 실패 — 원본 즉시 복원(소실 방지).
        try:
            await client.post("/instances", content=raw_data, headers={"Content-Type": "application/dicom"})
            logger.error(f"normalization re-upload failed ({up.status_code}); restored original {sop_uid}")
        except Exception as e:
            logger.error(f"CRITICAL: normalization re-upload AND restore failed for {sop_uid}: {e}")
        return {"error": f"재업로드 실패: {up.status_code} (원본 복원 시도됨)"}
    fixed_oid = None
    try:
        fixed_oid = up.json().get("ID")
    except Exception:
        pass

    study_uid = str(getattr(ds, "StudyInstanceUID", "") or sop_uid)
    hist = DicomFixHistory(
        study_instance_uid=study_uid,
        sop_instance_uid=sop_uid,
        rule_codes=["NORMALIZATION_REVIEW"],
        changes=applied,
        original_hash=original_hash,
        backup_orthanc_id=orthanc_id,
        original_data=(raw_data if len(raw_data) <= _MAX_BACKUP else None),
        fixed_orthanc_id=fixed_oid,
        fix_status="applied",
        post_validation={"source": "normalization_review"},
        fixed_by=actor_id,
    )
    db.add(hist)
    await db.flush()
    return {"applied": applied, "fixed_orthanc_id": fixed_oid, "history_id": str(hist.id)}
