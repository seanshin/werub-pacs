"""Domain metrics for Prometheus (pacs-fundamentals 2축 — 운영 가시성).

instrumentator의 범용 HTTP 메트릭만 있던 /metrics에 PACS 도메인 게이지를 추가한다.
스크레이프 시점 부하를 피하려고 lifespan 백그라운드 태스크가 30초마다 갱신한다
(collect-time HTTP/DB 호출은 이벤트루프를 블로킹).
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

REFRESH_SEC = 30
CELERY_QUEUES = ["ai_inference", "default", "prefetch", "export"]

try:
    from prometheus_client import Gauge
    STUDIES = Gauge("pacs_orthanc_studies_total", "Orthanc study count")
    INSTANCES = Gauge("pacs_orthanc_instances_total", "Orthanc instance count")
    STORAGE_MB = Gauge("pacs_orthanc_storage_mb", "Orthanc storage size (MB)")
    VALIDATION_FAILS = Gauge(
        "pacs_validation_failures_24h",
        "DICOM validation findings in the last 24h", ["severity"],
    )
    QUEUE_LEN = Gauge("pacs_celery_queue_length", "Celery queue backlog", ["queue"])
    HOST_DISK_PCT = Gauge("pacs_host_disk_used_pct", "Host filesystem used percent")
    _AVAILABLE = True
except ImportError:  # prometheus_client 미설치 환경(테스트 등)
    _AVAILABLE = False


async def _refresh_once(app) -> None:
    # Orthanc 수신량
    try:
        resp = await app.state.http_client.get("/statistics")
        if resp.status_code == 200:
            st = resp.json()
            STUDIES.set(st.get("CountStudies", 0))
            INSTANCES.set(st.get("CountInstances", 0))
            STORAGE_MB.set(st.get("TotalDiskSizeMB", 0))
    except Exception as e:
        logger.debug(f"domain metrics orthanc: {e}")

    # 검증 실패 (최근 24h, severity별)
    try:
        from sqlalchemy import text
        from app.core.database import async_session
        if async_session:
            async with async_session() as db:
                rows = (await db.execute(text("""
                    SELECT severity::text AS sev, COUNT(*) AS c FROM validation_results
                    WHERE created_at > now() - interval '24 hours'
                    GROUP BY severity
                """))).all()
                seen = {r.sev: r.c for r in rows}
                for sev in ("CRITICAL", "ERROR", "WARNING", "INFO"):
                    VALIDATION_FAILS.labels(severity=sev).set(seen.get(sev, 0))
    except Exception as e:
        logger.debug(f"domain metrics validation: {e}")

    # Celery 큐 적체 (redis broker list 길이 — v11.5 미라우팅 큐 적체 교훈의 상시 계기판)
    try:
        for q in CELERY_QUEUES + ["celery"]:  # "celery" = 미라우팅 기본 큐(0이어야 정상)
            QUEUE_LEN.labels(queue=q).set(await app.state.redis.llen(q))
    except Exception as e:
        logger.debug(f"domain metrics queues: {e}")

    # 호스트 디스크 (storage_monitor와 동일 경로)
    try:
        from app.services.storage_monitor import read_host_disk
        hd = read_host_disk()
        if hd.get("used_pct") is not None:
            HOST_DISK_PCT.set(hd["used_pct"])
    except Exception as e:
        logger.debug(f"domain metrics disk: {e}")


async def domain_metrics_loop(app) -> None:
    if not _AVAILABLE:
        logger.warning("prometheus_client unavailable — domain metrics disabled")
        return
    while True:
        try:
            await _refresh_once(app)
        except Exception as e:
            logger.warning(f"domain metrics refresh failed: {e}")
        await asyncio.sleep(REFRESH_SEC)
