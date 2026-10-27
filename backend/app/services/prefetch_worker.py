"""Predictive prefetch worker (3d-ai-performance Track A).

Warms the nginx frame cache ahead of reading: when a radiologist opens a study,
predict what they will open next (next worklist assignments + most recent prior
of the current patient) and replay the exact WADO-RS frame requests the viewer
will make, **through nginx**, so the viewer's real requests become cache hits.

Predictions are rule-based for now; the `Predictor` interface is the seam where
a learned model (trained on prefetch_history + audit logs) plugs in later.
"""
import json
import logging
import time
import uuid
from dataclasses import dataclass

import httpx
import redis as sync_redis
from sqlalchemy import text

from app.core.config import settings
from app.services.ai_worker import celery_app, _get_db_session

logger = logging.getLogger(__name__)

# Must produce the same nginx cache bucket as the viewer's requests.
# The viewer is pinned to J2K (requestTransferSyntaxUID in werub-app-config.js);
# nginx keys the cache on the transfer-syntax UID extracted from Accept, so only
# the UID below has to match — not the full header string.
VIEWER_TRANSFER_SYNTAX = "1.2.840.10008.1.2.4.90"
FRAME_ACCEPT = (
    'multipart/related; type="application/octet-stream"; '
    f"transfer-syntax={VIEWER_TRANSFER_SYNTAX}"
)

CONFIG_KEY = "pacs:prefetch:config"
LOCK_PREFIX = "pacs:prefetch:lock:"
LOCK_TTL_SEC = 600

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = sync_redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def get_prefetch_config() -> dict:
    """Runtime config: Redis overrides on top of env defaults."""
    cfg = {
        "enabled": settings.prefetch_enabled,
        "next_n": settings.prefetch_next_n,
        "prior_n": settings.prefetch_prior_n,
        "max_frames_per_study": settings.prefetch_max_frames_per_study,
    }
    try:
        raw = _get_redis().get(CONFIG_KEY)
        if raw:
            cfg.update({k: v for k, v in json.loads(raw).items() if k in cfg})
    except Exception as e:
        logger.warning(f"prefetch config read failed, using defaults: {e}")
    return cfg


@dataclass
class Candidate:
    study_uid: str
    reason: str  # next_in_worklist | prior


class RuleBasedPredictor:
    """Phase 1 heuristics. Phase 2 swaps this class for a learned model
    keeping predict()'s signature."""

    def __init__(self, db, orthanc: httpx.Client):
        self.db = db
        self.orthanc = orthanc

    def predict(self, username: str, current_study_uid: str, next_n: int, prior_n: int) -> list[Candidate]:
        out: list[Candidate] = []
        out += self._next_assignments(username, current_study_uid, next_n)
        if prior_n > 0:
            out += self._recent_priors(current_study_uid, prior_n)
        # de-dup, keep first reason
        seen, uniq = set(), []
        for c in out:
            if c.study_uid not in seen and c.study_uid != current_study_uid:
                seen.add(c.study_uid)
                uniq.append(c)
        return uniq

    def _next_assignments(self, username: str, current_uid: str, n: int) -> list[Candidate]:
        if not self.db or n <= 0:
            return []
        rows = self.db.execute(text("""
            SELECT study_instance_uid FROM reading_assignments
            WHERE assigned_to_username = :u AND is_current = true
              AND status != 'completed' AND study_instance_uid != :cur
            ORDER BY assigned_at ASC LIMIT :n
        """), {"u": username, "cur": current_uid, "n": n}).all()
        return [Candidate(r[0], "next_in_worklist") for r in rows]

    def _recent_priors(self, study_uid: str, n: int) -> list[Candidate]:
        try:
            resp = self.orthanc.post("/tools/find", json={
                "Level": "Study", "Query": {"StudyInstanceUID": study_uid}, "Expand": True,
            })
            if resp.status_code != 200 or not resp.json():
                return []
            patient_id = resp.json()[0].get("PatientMainDicomTags", {}).get("PatientID", "")
            if not patient_id:
                return []
            resp = self.orthanc.post("/tools/find", json={
                "Level": "Study", "Query": {"PatientID": patient_id}, "Expand": True,
            })
            if resp.status_code != 200:
                return []
            studies = [
                (s.get("MainDicomTags", {}).get("StudyDate", ""),
                 s.get("MainDicomTags", {}).get("StudyInstanceUID", ""))
                for s in resp.json()
                if s.get("MainDicomTags", {}).get("StudyInstanceUID", "") != study_uid
            ]
            studies.sort(reverse=True)
            return [Candidate(uid, "prior") for _, uid in studies[:n] if uid]
        except Exception as e:
            logger.warning(f"prior lookup failed for {study_uid}: {e}")
            return []


def _orthanc_client() -> httpx.Client:
    return httpx.Client(
        base_url=settings.orthanc_url,
        auth=(settings.orthanc_username, settings.orthanc_password),
        timeout=30.0,
    )


def _qido(warm: httpx.Client, path: str) -> list[dict]:
    resp = warm.get(f"/dicom-web{path}", headers={"Accept": "application/dicom+json"})
    if resp.status_code != 200:
        return []
    try:
        return resp.json()
    except Exception:
        return []


def _tag(item: dict, tag: str, default=""):
    v = item.get(tag, {}).get("Value")
    return v[0] if v else default


@celery_app.task(bind=True, max_retries=1, default_retry_delay=60)
def plan_prefetch(self, username: str, study_uid: str, trigger: str = "study_opened"):
    """Resolve candidates for `username` after opening `study_uid`, enqueue warms."""
    cfg = get_prefetch_config()
    if not cfg["enabled"]:
        return {"planned": 0, "reason": "disabled"}

    db = _get_db_session()
    orthanc = _orthanc_client()
    try:
        predictor = RuleBasedPredictor(db, orthanc)
        candidates = predictor.predict(username, study_uid, cfg["next_n"], cfg["prior_n"])
    finally:
        orthanc.close()
        if db:
            db.close()

    for c in candidates:
        warm_study.delay(c.study_uid, username, c.reason, trigger)
    logger.info(f"prefetch planned {len(candidates)} for {username} after {study_uid}")
    return {"planned": len(candidates), "studies": [c.study_uid for c in candidates]}


@celery_app.task(bind=True, max_retries=1, default_retry_delay=120)
def warm_study(self, study_uid: str, predicted_for: str, reason: str, trigger: str = "study_opened"):
    """Fetch every frame of `study_uid` through nginx to populate its cache.

    Series with the most instances first (those are the 3D/MPR targets), capped
    by max_frames_per_study to bound disk and Orthanc transcode CPU.
    """
    cfg = get_prefetch_config()
    if not cfg["enabled"]:
        return {"status": "skipped", "reason": "disabled"}

    # One warm per study per 10 min, across all triggers/users
    r = _get_redis()
    try:
        if not r.set(f"{LOCK_PREFIX}{study_uid}", predicted_for, nx=True, ex=LOCK_TTL_SEC):
            return {"status": "skipped", "reason": "recently_warmed"}
    except Exception as e:
        logger.warning(f"prefetch lock unavailable ({e}), warming without lock")

    started = time.monotonic()
    frames_warmed, bytes_warmed, status = 0, 0, "done"
    budget = int(cfg["max_frames_per_study"])

    # 공개판: 영상 경로는 토큰을 요구한다(사설 대역 우회 없음) — 워커도 서비스 토큰을 들고 부른다
    from app.core.security import create_access_token
    warm = httpx.Client(base_url=settings.prefetch_warm_base_url, timeout=60.0,
                        headers={"Authorization": f"Bearer {create_access_token('prefetch-worker', 'prefetch-worker', 'service')}"})
    try:
        series_list = _qido(warm, f"/studies/{study_uid}/series")
        # NumberOfSeriesRelatedInstances (00201209); largest series = 3D target
        series_list.sort(key=lambda s: int(_tag(s, "00201209", 0) or 0), reverse=True)

        for series in series_list:
            series_uid = _tag(series, "0020000E")
            if not series_uid:
                continue
            instances = _qido(
                warm,
                f"/studies/{study_uid}/series/{series_uid}/instances"
                f"?includefield=00280008",
            )
            series_dead = False  # first failure skips the series (e.g. J2K transcode 502 on OT/PALETTE)
            for inst in instances:
                sop_uid = _tag(inst, "00080018")
                if not sop_uid:
                    continue
                n_frames = int(_tag(inst, "00280008", 1) or 1)
                for frame in range(1, n_frames + 1):
                    if frames_warmed >= budget:
                        status = "partial"
                        break
                    url = (f"/dicom-web/studies/{study_uid}/series/{series_uid}"
                           f"/instances/{sop_uid}/frames/{frame}")
                    try:
                        resp = warm.get(url, headers={"Accept": FRAME_ACCEPT})
                        if resp.status_code == 200:
                            frames_warmed += 1
                            bytes_warmed += len(resp.content)
                        else:
                            logger.warning(
                                f"warm frame {resp.status_code} on series {series_uid}, skipping series"
                            )
                            series_dead = True
                            break
                    except Exception as e:
                        logger.warning(f"warm frame failed {url}: {e}")
                        series_dead = True
                        break
                if frames_warmed >= budget or series_dead:
                    break
            if frames_warmed >= budget:
                break
        if frames_warmed == 0 and status == "done":
            status = "failed"
    except Exception as e:
        logger.error(f"warm_study {study_uid} failed: {e}")
        status = "failed"
    finally:
        warm.close()

    duration_ms = int((time.monotonic() - started) * 1000)
    db = _get_db_session()
    if db:
        try:
            db.execute(text("""
                INSERT INTO prefetch_history
                    (id, study_instance_uid, predicted_for, trigger_type, reason,
                     frames_warmed, bytes_warmed, duration_ms, status)
                VALUES (:id, :s, :u, :t, :r, :f, :b, :d, :st)
            """), {
                "id": str(uuid.uuid4()), "s": study_uid, "u": predicted_for,
                "t": trigger, "r": reason, "f": frames_warmed, "b": bytes_warmed,
                "d": duration_ms, "st": status,
            })
            db.commit()
        except Exception as e:
            logger.error(f"prefetch_history insert failed: {e}")
        finally:
            db.close()

    logger.info(
        f"warm_study {study_uid}: {status}, frames={frames_warmed}, "
        f"bytes={bytes_warmed}, {duration_ms}ms"
    )
    return {"status": status, "frames": frames_warmed, "bytes": bytes_warmed,
            "duration_ms": duration_ms}
