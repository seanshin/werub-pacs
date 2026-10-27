"""MPI / cross-institution patient identity + XDS-I submission models (v2.0 트랙 A).

IHE PIX/MPI (I002 갭) 및 XDS-I.b Phase 1(ITI-41 제출)의 데이터 계층.

- `identity_domains`   : 식별자 발급기관(assigning authority) — HL7 CX.4 (namespace^^^&OID&ISO)
- `mpi_patients`       : 엔터프라이즈 환자(교차참조 앵커)
- `patient_identifiers`: 도메인별 환자 식별자 → mpi_patients 교차참조
- `xdsi_submissions`   : ITI-41 제출 이력(감사·재시도)

기존 `patient_mappings`(HIS↔DICOM 단일도메인)는 유지 — MPI는 그 위 계층. 로컬 도메인
식별자로 기존 DICOM PatientID를 흡수(백필 엔드포인트).

테이블은 `_DDL`을 `core/schema_migrations._collect_ddls()`가 부팅 시 1회 생성한다
(teaching/retake 선례 — scp 배포 안전). ORM은 쿼리 명료성용. status 등 리터럴은 대문자
(enum NAME 함정 회피 — raw SQL 조회 정합).

설계: `docs/02-design/xds-i-pix-mpi-phase1.design.md`
"""
from __future__ import annotations

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin

# 로컬 도메인의 고정 namespace_id — 백필/제출이 참조하는 앵커
LOCAL_NAMESPACE_ID = "OPENPACS"


class IdentityDomain(Base, UUIDMixin, TimestampMixin):
    """식별자 발급기관(assigning authority). HL7 CX.4 = namespace_id^^^&universal_id&type."""

    __tablename__ = "identity_domains"

    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    namespace_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)  # CX.4.1
    universal_id: Mapped[str | None] = mapped_column(String(128), unique=True)          # CX.4.2 (OID)
    universal_type: Mapped[str] = mapped_column(String(16), default="ISO")              # CX.4.3
    is_local: Mapped[bool] = mapped_column(Boolean, default=False)      # 우리 도메인
    is_affinity: Mapped[bool] = mapped_column(Boolean, default=False)   # 제출 시 patientId 도메인


class MpiPatient(Base, UUIDMixin, TimestampMixin):
    """엔터프라이즈 환자(교차참조 앵커). id = 내부 enterprise identifier."""

    __tablename__ = "mpi_patients"

    created_from: Mapped[str] = mapped_column(String(16), default="local")  # local|pix_query|feed
    # 대조검증 최소 인구통계(PHI 최소화): {"name":..,"sex":..,"birth_date":..}
    demographics: Mapped[dict | None] = mapped_column(JSONB)


class PatientIdentifier(Base, UUIDMixin, TimestampMixin):
    """도메인별 환자 식별자 → mpi_patients 교차참조. UNIQUE(domain_id, identifier)."""

    __tablename__ = "patient_identifiers"

    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mpi_patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_domains.id", ondelete="CASCADE"), nullable=False, index=True
    )
    identifier: Mapped[str] = mapped_column(String(128), nullable=False, index=True)


class XdsiSubmission(Base, UUIDMixin, TimestampMixin):
    """ITI-41 Provide & Register 제출 이력. status는 대문자 리터럴."""

    __tablename__ = "xdsi_submissions"

    study_instance_uid: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target_endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    affinity_domain_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    affinity_patient_id: Mapped[str | None] = mapped_column(String(256))  # CX in affinity domain
    submission_set_uid: Mapped[str | None] = mapped_column(String(128))
    kos_sop_uid: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")  # PENDING|SUBMITTED|FAILED
    registry_response: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by_name: Mapped[str | None] = mapped_column(String(128))
    submitted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


# ── 부팅 마이그레이션 DDL (schema_migrations 수집) ──
_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS identity_domains (
        id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        name           VARCHAR(128) NOT NULL UNIQUE,
        namespace_id   VARCHAR(64)  NOT NULL UNIQUE,
        universal_id   VARCHAR(128) UNIQUE,
        universal_type VARCHAR(16)  NOT NULL DEFAULT 'ISO',
        is_local       BOOLEAN NOT NULL DEFAULT FALSE,
        is_affinity    BOOLEAN NOT NULL DEFAULT FALSE,
        created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS mpi_patients (
        id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        created_from VARCHAR(16) NOT NULL DEFAULT 'local',
        demographics JSONB,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS patient_identifiers (
        id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        enterprise_id UUID NOT NULL REFERENCES mpi_patients(id) ON DELETE CASCADE,
        domain_id     UUID NOT NULL REFERENCES identity_domains(id) ON DELETE CASCADE,
        identifier    VARCHAR(128) NOT NULL,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(domain_id, identifier)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_pid_enterprise ON patient_identifiers(enterprise_id)",
    "CREATE INDEX IF NOT EXISTS idx_pid_identifier ON patient_identifiers(identifier)",
    """CREATE TABLE IF NOT EXISTS xdsi_submissions (
        id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        study_instance_uid  VARCHAR(128) NOT NULL,
        target_endpoint     VARCHAR(512) NOT NULL,
        affinity_domain_id  UUID,
        affinity_patient_id VARCHAR(256),
        submission_set_uid  VARCHAR(128),
        kos_sop_uid         VARCHAR(128),
        status              VARCHAR(16) NOT NULL DEFAULT 'PENDING',
        registry_response   TEXT,
        created_by_id       UUID,
        created_by_name     VARCHAR(128),
        submitted_at        TIMESTAMPTZ,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_xdsi_study ON xdsi_submissions(study_instance_uid)",
    # 로컬 도메인 시드(멱등) — 백필/제출 앵커. 타깃 미지정 ON CONFLICT: 다중 워커 부팅 경합에서
    # name/namespace_id 어느 unique로 충돌하든 no-op(단일 타깃이면 다른 제약 충돌 시 예외).
    "INSERT INTO identity_domains (name, namespace_id, universal_type, is_local) "
    "VALUES ('OpenPACS-Local', 'OPENPACS', 'ISO', TRUE) ON CONFLICT DO NOTHING",
]
