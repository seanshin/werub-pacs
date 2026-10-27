"""Pathology (SM) WSI arrival watcher — LIS 연계 보완 (v13.34).

역할 분담(2026-07-19 3자 합의): WSI 도착 감지·통지는 PACS 담당. WSI 스캐너는
통상 MPPS를 보내지 않아 SM 워크리스트가 영상 도착 후에도 SCHEDULED로 남는다
(모니터의 "48h+ SCHEDULED" 오탐 원인이자 §4.2 감지 공백). 이 beat 태스크가 정합:

  SCHEDULED SM worklist → Orthanc AccessionNumber 조회 → 도착 시
  ① worklist COMPLETED 전이 + StudyInstanceUID 기록 (MPPS 미보고 스캐너 대체)
  ② admin 알림 생성 — action_url이 accession 런처(SM→microscopy 자동 라우팅)

늦은 취소 가드(hl7_listener: 비-SCHEDULED는 CA 무시)와 정합 — 영상이 이미 온
검사의 취소는 상태를 덮지 않는다. MPPS를 보내는 장비면 MPPS가 먼저 전이시키므로
이 태스크는 no-op이 된다(SCHEDULED만 스캔).
"""
import logging
import uuid

import httpx
from sqlalchemy import text

from app.core.config import settings
from app.services.ai_worker import celery_app, _get_db_session

logger = logging.getLogger(__name__)


def _find_study_uid(client: httpx.Client, accession: str) -> str | None:
    """Orthanc에서 accession 정확 매칭 study의 StudyInstanceUID (없으면 None)."""
    resp = client.post(
        "/tools/find",
        json={"Level": "Study", "Query": {"AccessionNumber": accession},
              "Expand": True, "Limit": 2},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"orthanc find {resp.status_code}")
    studies = resp.json()
    for s in studies if isinstance(studies, list) else []:
        uid = (s.get("MainDicomTags") or {}).get("StudyInstanceUID")
        if uid:
            return uid
    return None


def _notify_arrival(db, *, accession: str, patient_id: str, patient_name: str,
                    study_uid: str) -> None:
    launch = f"/pacs-api/api/v1/viewer/launch?AccessionNumber={accession}"
    db.execute(text("""
        INSERT INTO notifications (id, type, title, message, urgency, target_role,
            study_instance_uid, patient_id, action_url, is_read, acknowledged, created_at)
        VALUES (:id, 'pathology_arrival', :title, :msg, 'urgent', 'admin',
                :suid, :pid, :url, false, false, NOW())
    """), {
        "id": str(uuid.uuid4()),
        "title": "병리 WSI 도착",
        "msg": f"{accession} ({patient_name}) 병리 영상이 도착했습니다 — "
               f"워크리스트 COMPLETED 전이. 열람 확인 후 LIS에 통지하세요.",
        "suid": study_uid, "pid": patient_id, "url": launch,
    })


@celery_app.task(bind=True, max_retries=0)
def check_pathology_arrivals(self):
    """SCHEDULED SM 워크리스트 ↔ Orthanc 도착 정합 (beat 5분)."""
    db = _get_db_session()
    if not db:
        logger.error("pathology_arrival: DB unavailable")
        return {"status": "db_unavailable"}
    arrived, pending, errors = [], 0, 0
    try:
        rows = db.execute(text("""
            SELECT accession_number, patient_id, patient_name
            FROM worklist_items
            WHERE status::text = 'SCHEDULED' AND modality = 'SM'
            ORDER BY created_at
            LIMIT 200
        """)).fetchall()
        if not rows:
            return {"status": "ok", "pending": 0, "arrived": 0}

        with httpx.Client(
            base_url=settings.orthanc_url,
            auth=(settings.orthanc_username, settings.orthanc_password),
            timeout=15.0,
        ) as client:
            for acc, pid, pname in rows:
                try:
                    uid = _find_study_uid(client, acc)
                except Exception as e:
                    logger.warning("pathology_arrival: %s lookup failed: %s", acc, e)
                    errors += 1
                    continue
                if uid is None:
                    pending += 1
                    continue
                # 도착 — SCHEDULED에서만 전이(레이스 시 MPPS/취소 우선 존중)
                updated = db.execute(text("""
                    UPDATE worklist_items
                    SET status = 'COMPLETED', study_instance_uid = :uid, updated_at = NOW()
                    WHERE accession_number = :acc AND status::text = 'SCHEDULED'
                """), {"uid": uid, "acc": acc})
                if updated.rowcount:
                    _notify_arrival(db, accession=acc, patient_id=pid,
                                    patient_name=pname, study_uid=uid)
                    arrived.append(acc)
                    logger.info("pathology_arrival: %s -> COMPLETED (study %s)", acc, uid)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("pathology_arrival failed: %s", e)
        return {"status": f"error: {e}"}
    finally:
        db.close()
    return {"status": "ok", "pending": pending, "arrived": arrived, "errors": errors}
