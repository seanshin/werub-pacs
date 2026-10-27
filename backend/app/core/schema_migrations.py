"""Startup schema migration runner.

세션 중 핸들러/태스크에 흩어진 멱등 DDL(CREATE/ALTER IF NOT EXISTS)을 **부팅 시 1회**
실행해, per-request DDL이 첫 호출에서 ACCESS EXCLUSIVE 락 경합을 일으키던 문제를 제거한다.
기존 모듈의 DDL 상수를 재사용(중복 정의 drift 방지). 각 DDL은 독립 트랜잭션·실패 격리.
핸들러의 per-request 가드는 방어용으로 유지(startup 미실행 환경 대비).
"""
import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _collect_ddls() -> list[str]:
    ddls: list[str] = []
    try:
        from app.api.report_esign import _DDL_SIG, _DDL_CERT, _SIG_COLUMNS
        ddls.append(_DDL_SIG)
        ddls.append(_DDL_CERT)
        ddls += [f"ALTER TABLE report_esignatures ADD COLUMN IF NOT EXISTS {c} {t}"
                 for c, t in _SIG_COLUMNS]
    except Exception as e:
        logger.warning(f"migration collect (esign) failed: {e}")
    try:
        from app.api.ai import _FEEDBACK_DDL
        ddls += list(_FEEDBACK_DDL)
    except Exception as e:
        logger.warning(f"migration collect (ai) failed: {e}")
    try:
        from app.services.governance_monitor import _SCHEMA_DDL
        ddls += list(_SCHEMA_DDL)
    except Exception as e:
        logger.warning(f"migration collect (governance) failed: {e}")
    try:
        from app.services.bi_report import _DDL as _BI_DDL
        ddls.append(_BI_DDL)
    except Exception as e:
        logger.warning(f"migration collect (bi) failed: {e}")
    # retake_requests (was per-request _ensure_table in api/retake_request.py)
    try:
        from app.api.retake_request import CREATE_TABLE_SQL as _RETAKE_TBL, CREATE_INDEX_SQL as _RETAKE_IDX
        ddls.append(_RETAKE_TBL)
        ddls += [s.strip() for s in _RETAKE_IDX.split(";") if s.strip()]
    except Exception as e:
        logger.warning(f"migration collect (retake) failed: {e}")
    # sla_escalation_log (was per-request _ensure_tables in api/sla_escalation.py).
    # SETUP_SQL is multi-statement (table + 2 indexes) — split so each runs alone.
    try:
        from app.api.sla_escalation import SETUP_SQL as _SLA_SQL
        ddls += [s.strip() for s in _SLA_SQL.split(";") if s.strip()]
    except Exception as e:
        logger.warning(f"migration collect (sla_escalation) failed: {e}")
    # teaching-file-library (teaching_cases/tags/collections/collection_items)
    try:
        from app.models.teaching import _DDL as _TEACHING_DDL
        ddls += list(_TEACHING_DDL)
    except Exception as e:
        logger.warning(f"migration collect (teaching) failed: {e}")
    # MPI/PIX + XDS-I submission (identity_domains/mpi_patients/patient_identifiers/xdsi_submissions)
    try:
        from app.models.mpi import _DDL as _MPI_DDL
        ddls += list(_MPI_DDL)
    except Exception as e:
        logger.warning(f"migration collect (mpi) failed: {e}")
    # patient_view_tokens — 환자 결과 열람 포털 토큰
    try:
        from app.models.patient_view import _DDL as _PVIEW_DDL
        ddls += list(_PVIEW_DDL)
    except Exception as e:
        logger.warning(f"migration collect (patient_view) failed: {e}")
    # study_comments (was process-local list — S12 persist)
    try:
        from app.api.study_comments import _DDL as _COMMENTS_DDL
        ddls += list(_COMMENTS_DDL)
    except Exception as e:
        logger.warning(f"migration collect (study_comments) failed: {e}")
    # 핸들러에 상수가 없는 단발 ALTER
    ddls.append("ALTER TABLE ai_screening_results ADD COLUMN IF NOT EXISTS ack_by TEXT")
    # vrt_metrics.preset_name — VR 프리셋 선택 텔레메트리 (C2 경량 튜닝)
    ddls.append("ALTER TABLE vrt_metrics ADD COLUMN IF NOT EXISTS preset_name VARCHAR(64)")
    # audit_logs.status (SUCCESS/FAILED) — persisted for the audit UI status filter
    ddls.append("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'SUCCESS'")
    # ai_models.checksum_sha256 — 로컬 모델 파일 무결성 검증 (INV-NET-02)
    ddls.append("ALTER TABLE ai_models ADD COLUMN IF NOT EXISTS checksum_sha256 VARCHAR(64)")
    # role_enum: SERVICE (외부 연동 read-only 서비스 계정 — R1/LIS)는 startup 마이그레이션에
    # 넣지 않는다. 이 러너는 백엔드 DB 유저(openpacs)로 도는데 role_enum 소유자는 hospital이라
    # ALTER TYPE 권한이 없고(InsufficientPrivilege), 라벨은 SQLAlchemy NAME 규약상 대문자여야 함.
    # 소유자 원샷(2026-07-13 적용):
    #   docker exec docker-postgres-1 psql -U hospital -d openpacs \
    #     -c "ALTER TYPE role_enum ADD VALUE IF NOT EXISTS 'SERVICE';"
    # shared key/value config table — was per-request CREATE in webhook_config /
    # sla_escalation / normalization_settings handlers (openpacs_config)
    ddls.append(
        "CREATE TABLE IF NOT EXISTS openpacs_config ("
        "key TEXT PRIMARY KEY, value JSONB NOT NULL DEFAULT '{}', "
        "updated_by TEXT, updated_at TIMESTAMPTZ DEFAULT NOW())"
    )
    # audit_logs append-only (arch-invariants INV-AUDIT-01): 감사 추적의 불변성을
    # DB 레벨에서 강제 — 앱에는 UPDATE/DELETE 경로가 원래 없음(2026-07-15 전수 확인).
    # 보존기간 경과분 정리 등 운영 작업이 필요하면 테이블 소유자(openpacs)로
    # 트리거를 잠시 DROP 후 수행하고 재생성한다(감사 로그에 사유 기록).
    ddls.append(
        "CREATE OR REPLACE FUNCTION audit_logs_block_mutation() RETURNS trigger AS $$ "
        "BEGIN RAISE EXCEPTION 'audit_logs is append-only (% blocked)', TG_OP; END; "
        "$$ LANGUAGE plpgsql"
    )
    ddls.append("DROP TRIGGER IF EXISTS trg_audit_logs_append_only ON audit_logs")
    ddls.append(
        "CREATE TRIGGER trg_audit_logs_append_only "
        "BEFORE UPDATE OR DELETE ON audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION audit_logs_block_mutation()"
    )
    return ddls


async def run_startup_migrations(engine) -> None:
    if engine is None:
        return
    ddls = _collect_ddls()
    ok = 0
    for ddl in ddls:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(ddl))
            ok += 1
        except Exception as e:
            logger.warning(f"startup migration skipped: {str(e)[:90]}")
    logger.info(f"startup schema migrations: {ok}/{len(ddls)} applied")
