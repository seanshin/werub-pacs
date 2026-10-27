"""Patient ID mapping between HIS (HospitalRun) and PACS (DICOM)."""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class PatientMapping(Base, UUIDMixin, TimestampMixin):
    """Maps HIS MRN to DICOM PatientID.

    Flow:
    1. HospitalRun creates order with his_mrn (e.g., HR-20260506-0328)
    2. OpenPACS creates worklist with his_mrn as DICOM PatientID
    3. Modality picks up worklist → uses PatientID in DICOM header
    4. PACS receives image → PatientID matches his_mrn
    5. Patient lookup: his_mrn → DICOM studies
    """

    __tablename__ = "patient_mappings"

    # HIS (HospitalRun) side
    his_mrn: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    his_patient_name: Mapped[str | None] = mapped_column(String(256))
    his_patient_id: Mapped[str | None] = mapped_column(String(128))  # HospitalRun internal UUID

    # DICOM side (may differ from HIS MRN if legacy data)
    dicom_patient_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    dicom_patient_name: Mapped[str | None] = mapped_column(String(256))

    # Source
    source: Mapped[str] = mapped_column(String(32), default="worklist")  # worklist, manual, migration

    # dicom_patient_id already indexed via mapped_column(index=True)
