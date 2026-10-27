"""티칭파일 라이브러리 — 판독 교육용 케이스/태그/컬렉션.

라이브 study(StudyInstanceUID)를 **참조**만 한다(익명화 사본 없음). PHI는 RBAC로 보호하고,
케이스 컬럼엔 교육 맥락의 나이/성별만 저장(이름/MRN 미저장).

테이블은 `_DDL`을 `core/schema_migrations._collect_ddls()`가 수집해 부팅 시 1회 생성한다
(retake_request 선례 — scp 배포 안전). ORM은 쿼리/코드 명료성용.
"""
import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class TeachingCase(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "teaching_cases"

    study_instance_uid: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    orthanc_study_id: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    diagnosis: Mapped[str | None] = mapped_column(Text)          # 정답 진단(교육 핵심)
    modality: Mapped[str | None] = mapped_column(String(16))
    organ: Mapped[str | None] = mapped_column(String(64))
    # beginner | intermediate | advanced (앱에서 검증 — enum NAME 함정 회피)
    difficulty: Mapped[str] = mapped_column(
        String(16), default="intermediate", server_default="intermediate", nullable=False
    )
    patient_age: Mapped[str | None] = mapped_column(String(8))   # 교육 맥락(이름/MRN 미저장)
    patient_sex: Mapped[str | None] = mapped_column(String(8))
    report_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_name: Mapped[str | None] = mapped_column(String(128))
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    view_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    # 게시 승인 워크플로 — draft|pending|published|rejected (앱에서 검증, enum NAME 회피).
    # is_published는 (publish_status=='published')와 동기 유지(기존 필터/배지 호환).
    publish_status: Mapped[str] = mapped_column(
        String(16), default="draft", server_default="draft", nullable=False
    )
    submitted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128))
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)


class TeachingCaseTag(Base, UUIDMixin):
    __tablename__ = "teaching_case_tags"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teaching_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tag: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class TeachingCollection(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "teaching_collections"

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_name: Mapped[str | None] = mapped_column(String(128))
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)


class TeachingCollectionItem(Base, UUIDMixin):
    __tablename__ = "teaching_collection_items"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teaching_collections.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teaching_cases.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class TeachingQuizAttempt(Base, UUIDMixin, TimestampMixin):
    """퀴즈/언노운 모드 응답 — 학습자가 정답 가린 케이스에 자기 진단을 제출한 1회 시도.

    제출 시 정답이 공개되고(되돌리기 불가=정직), 이후 본인이 자가평가(correct/partial/incorrect)한다.
    진도 추적은 이 표를 모달리티/난이도별로 집계한 것이다(별도 진도 표 없음).
    self_assessment는 enum NAME 함정 회피 위해 문자열+앱 검증.
    """
    __tablename__ = "teaching_quiz_attempts"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teaching_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_name: Mapped[str | None] = mapped_column(String(128))
    submitted_answer: Mapped[str | None] = mapped_column(Text)
    self_assessment: Mapped[str | None] = mapped_column(String(16))  # correct|partial|incorrect (null=미평가)
    time_spent_ms: Mapped[int | None] = mapped_column(Integer)


# 부팅 시 schema_migrations가 수집하는 멱등 DDL(테이블 + 인덱스). 각 문은 독립 실행됨.
_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS teaching_cases (
        id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        study_instance_uid VARCHAR(128) NOT NULL,
        orthanc_study_id   VARCHAR(64),
        title              VARCHAR(256) NOT NULL,
        summary            TEXT,
        diagnosis          TEXT,
        modality           VARCHAR(16),
        organ              VARCHAR(64),
        difficulty         VARCHAR(16) NOT NULL DEFAULT 'intermediate',
        patient_age        VARCHAR(8),
        patient_sex        VARCHAR(8),
        report_id          UUID,
        created_by_id      UUID NOT NULL,
        created_by_name    VARCHAR(128),
        is_published       BOOLEAN NOT NULL DEFAULT FALSE,
        view_count         INTEGER NOT NULL DEFAULT 0,
        created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_tc_study ON teaching_cases(study_instance_uid)",
    "CREATE INDEX IF NOT EXISTS idx_tc_modality_diff ON teaching_cases(modality, difficulty)",
    "CREATE INDEX IF NOT EXISTS idx_tc_created ON teaching_cases(created_at DESC)",
    # 게시 승인 워크플로 컬럼(기존 teaching_cases에 ALTER 추가 — 신규 설치는 멱등 no-op).
    """ALTER TABLE teaching_cases
        ADD COLUMN IF NOT EXISTS publish_status   VARCHAR(16) NOT NULL DEFAULT 'draft',
        ADD COLUMN IF NOT EXISTS submitted_at     TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS reviewed_by_id   UUID,
        ADD COLUMN IF NOT EXISTS reviewed_by_name VARCHAR(128),
        ADD COLUMN IF NOT EXISTS reviewed_at      TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS review_comment   TEXT""",
    # 기존 게시본 백필(draft인데 is_published면 published로) — 멱등.
    "UPDATE teaching_cases SET publish_status='published' WHERE is_published=TRUE AND publish_status='draft'",
    "CREATE INDEX IF NOT EXISTS idx_tc_pubstatus ON teaching_cases(publish_status)",
    """CREATE TABLE IF NOT EXISTS teaching_case_tags (
        id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        case_id UUID NOT NULL REFERENCES teaching_cases(id) ON DELETE CASCADE,
        tag     VARCHAR(64) NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_tct_case ON teaching_case_tags(case_id)",
    "CREATE INDEX IF NOT EXISTS idx_tct_tag ON teaching_case_tags(tag)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_tct_case_tag ON teaching_case_tags(case_id, tag)",
    """CREATE TABLE IF NOT EXISTS teaching_collections (
        id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        title           VARCHAR(256) NOT NULL,
        description     TEXT,
        created_by_id   UUID NOT NULL,
        created_by_name VARCHAR(128),
        is_published    BOOLEAN NOT NULL DEFAULT FALSE,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS teaching_collection_items (
        id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        collection_id UUID NOT NULL REFERENCES teaching_collections(id) ON DELETE CASCADE,
        case_id       UUID NOT NULL REFERENCES teaching_cases(id) ON DELETE CASCADE,
        position      INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_tci ON teaching_collection_items(collection_id, case_id)",
    "CREATE INDEX IF NOT EXISTS idx_tci_coll ON teaching_collection_items(collection_id, position)",
    """CREATE TABLE IF NOT EXISTS teaching_quiz_attempts (
        id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        case_id          UUID NOT NULL REFERENCES teaching_cases(id) ON DELETE CASCADE,
        user_id          UUID NOT NULL,
        user_name        VARCHAR(128),
        submitted_answer TEXT,
        self_assessment  VARCHAR(16),
        time_spent_ms    INTEGER,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_tqa_case ON teaching_quiz_attempts(case_id)",
    "CREATE INDEX IF NOT EXISTS idx_tqa_user ON teaching_quiz_attempts(user_id, created_at DESC)",
]
