"""Integration tests for Phase 4 DICOM batch normalization."""
import pytest
import io
import pydicom
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.base import Base
from app.models.batch_job import (
    BatchJob, BatchJobFile, NormalizationConfig,
    NormalizationReview, SupplierRule
)
from app.models.user import User
from app.services.batch_job_service import BatchJobService
from app.services.config_service import ConfigService
from app.services.supplier_normalizer import (
    get_normalizer_for_supplier, SiemensNormalizer,
    GENormalizer, PhilipsNormalizer, DefaultNormalizer,
    _extract_private_tags,
)
from app.services.normalizer_engine import NormalizerEngine


# Test database
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def test_db():
    """Create test database session."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    AsyncTestingSession = sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with AsyncTestingSession() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def test_user(test_db: AsyncSession) -> User:
    """Create test user."""
    user = User(
        id=str(uuid4()),
        username="testuser",
        password_hash="hashed_password",
        is_admin=False,
    )
    test_db.add(user)
    await test_db.commit()
    return user


@pytest.fixture
async def test_admin(test_db: AsyncSession) -> User:
    """Create test admin user."""
    admin = User(
        id=str(uuid4()),
        username="admin",
        password_hash="hashed_password",
        is_admin=True,
    )
    test_db.add(admin)
    await test_db.commit()
    return admin


class TestBatchJobService:
    """Test BatchJobService functionality."""

    @pytest.mark.asyncio
    async def test_create_batch_job(self, test_db: AsyncSession, test_user: User):
        """Test creating a batch job."""
        batch = await BatchJobService.create_batch_job(
            test_db,
            user_id=str(test_user.id),
            total_files=10,
            supplier="siemens",
        )

        assert batch.user_id == str(test_user.id)
        assert batch.total_files == 10
        assert batch.supplier == "siemens"
        assert batch.status == "queued"
        assert batch.processed_files == 0

    @pytest.mark.asyncio
    async def test_add_batch_file(self, test_db: AsyncSession, test_user: User):
        """Test adding files to batch."""
        batch = await BatchJobService.create_batch_job(
            test_db,
            user_id=str(test_user.id),
            total_files=2,
        )
        await test_db.commit()

        file = await BatchJobService.add_batch_file(
            test_db,
            batch_id=str(batch.id),
            filename="test.dcm",
            sequence_number=1,
            modality="CT",
        )

        assert file.filename == "test.dcm"
        assert file.modality == "CT"
        assert file.status == "validated"

    @pytest.mark.asyncio
    async def test_update_batch_status(self, test_db: AsyncSession, test_user: User):
        """Test updating batch status."""
        batch = await BatchJobService.create_batch_job(
            test_db,
            user_id=str(test_user.id),
            total_files=1,
        )
        await test_db.commit()

        updated = await BatchJobService.update_batch_job_status(
            test_db,
            str(batch.id),
            "processing",
        )

        assert updated.status == "processing"
        assert updated.started_at is not None

    @pytest.mark.asyncio
    async def test_increment_counters(self, test_db: AsyncSession, test_user: User):
        """Test incrementing batch counters."""
        batch = await BatchJobService.create_batch_job(
            test_db,
            user_id=str(test_user.id),
            total_files=5,
        )
        await test_db.commit()

        updated = await BatchJobService.increment_batch_counters(
            test_db,
            str(batch.id),
            processed=5,
            succeeded=4,
            failed=1,
        )

        assert updated.processed_files == 5
        assert updated.succeeded_files == 4
        assert updated.failed_files == 1

    @pytest.mark.asyncio
    async def test_get_batch_statistics(self, test_db: AsyncSession, test_user: User):
        """Test getting batch statistics."""
        batch = await BatchJobService.create_batch_job(
            test_db,
            user_id=str(test_user.id),
            total_files=10,
        )
        await test_db.commit()

        # Add some files
        for i in range(10):
            await BatchJobService.add_batch_file(
                test_db,
                batch_id=str(batch.id),
                filename=f"file_{i}.dcm",
                sequence_number=i + 1,
            )
        await test_db.commit()

        stats = await BatchJobService.get_batch_statistics(test_db, str(batch.id))

        assert stats["total_files"] == 10
        assert stats["processed"] == 0
        assert stats["progress_percent"] == 0


class TestSupplierNormalizers:
    """Test supplier-specific normalizers."""

    @pytest.fixture
    async def default_config(self, test_db: AsyncSession) -> NormalizationConfig:
        """Create default config."""
        config = NormalizationConfig(
            modality="CT",
            algorithms={
                "pixel_spacing": True,
                "missing_tags": True,
                "photometric": False,
                "charset": True,
            },
            risk_tiers={
                "safe": "auto",
                "medium": "manual",
                "risky": "reject",
            },
        )
        test_db.add(config)
        await test_db.commit()
        return config

    def test_siemens_normalizer(self, default_config: NormalizationConfig):
        """Test Siemens normalizer."""
        normalizer = SiemensNormalizer(default_config, "siemens")

        file_data = {
            "0008,0070": "SIEMENS",  # Manufacturer
            "0008,0020": "20260501",  # StudyDate
            "0008,0030": "120000",     # StudyTime
        }

        changes = normalizer.normalize(file_data)

        # Should detect Siemens and add missing dates
        assert len(changes) > 0
        assert any(c.tag == "0008,0012" for c in changes)  # InstanceCreationDate

    def test_ge_normalizer(self, default_config: NormalizationConfig):
        """Test GE normalizer."""
        normalizer = GENormalizer(default_config, "ge")

        file_data = {
            "0008,0070": "GE",
            "0008,0020": "20260501",  # StudyDate
        }

        changes = normalizer.normalize(file_data)

        # Should detect GE and add SeriesDate
        assert len(changes) > 0

    def test_philips_normalizer(self, default_config: NormalizationConfig):
        """Test Philips normalizer."""
        normalizer = PhilipsNormalizer(default_config, "philips")

        file_data = {
            "0008,0070": "PHILIPS",
            "0008,0020": "20260501",
            "0008,0030": "120000",
        }

        changes = normalizer.normalize(file_data)

        # Should detect Philips and add ContentDate/Time
        assert len(changes) > 0

    def test_default_normalizer(self, default_config: NormalizationConfig):
        """Test default fallback normalizer."""
        normalizer = DefaultNormalizer(default_config, "default")

        file_data = {
            "0008,0020": "20260501",
            "0008,0030": "120000",
        }

        changes = normalizer.normalize(file_data)

        # Should add standard mandatory fields
        assert any(c.tag == "0010,0030" for c in changes)  # PatientBirthDate
        assert any(c.tag == "0010,0040" for c in changes)  # PatientSex

    def test_normalizer_factory(self, default_config: NormalizationConfig):
        """Test normalizer factory."""
        siemens_norm = get_normalizer_for_supplier("siemens", default_config)
        assert isinstance(siemens_norm, SiemensNormalizer)

        ge_norm = get_normalizer_for_supplier("ge", default_config)
        assert isinstance(ge_norm, GENormalizer)

        default_norm = get_normalizer_for_supplier("unknown", default_config)
        assert isinstance(default_norm, DefaultNormalizer)


class TestConfigService:
    """Test configuration service."""

    @pytest.mark.asyncio
    async def test_update_modality_config(self, test_db: AsyncSession, test_admin: User):
        """Test creating/updating modality configuration."""
        config = await ConfigService.update_modality_config(
            test_db,
            modality="CT",
            algorithms={"pixel_spacing": True, "missing_tags": True},
            risk_tiers={"safe": "auto", "medium": "manual"},
            updated_by=str(test_admin.id),
        )

        assert config.modality == "CT"
        assert config.algorithms["pixel_spacing"] is True

    @pytest.mark.asyncio
    async def test_create_supplier_rule(self, test_db: AsyncSession, test_admin: User):
        """Test creating supplier rule."""
        rule = await ConfigService.create_supplier_rule(
            test_db,
            supplier_name="siemens",
            rule_version="1.0",
            rule_config={"missing_dates": True},
            managed_by=str(test_admin.id),
            description="Siemens rule v1",
        )

        assert rule.supplier_name == "siemens"
        assert rule.rule_version == "1.0"
        assert rule.is_active is True

    @pytest.mark.asyncio
    async def test_deactivate_supplier_rule(self, test_db: AsyncSession, test_admin: User):
        """Test deactivating supplier rule."""
        rule = await ConfigService.create_supplier_rule(
            test_db,
            supplier_name="siemens",
            rule_version="1.0",
            rule_config={},
            managed_by=str(test_admin.id),
        )
        await test_db.commit()

        deactivated = await ConfigService.deactivate_supplier_rule(test_db, str(rule.id))

        assert deactivated.is_active is False


class TestNormalizerEngine:
    """Test DICOM normalization engine."""

    @pytest.fixture
    async def engine(self, test_db: AsyncSession) -> NormalizerEngine:
        """Create normalizer engine."""
        return NormalizerEngine(test_db)

    def create_minimal_dicom(self) -> bytes:
        """Create minimal valid DICOM file for testing."""
        file_meta = pydicom.dataset.FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = '1.2.840.10008.5.1.4.1.1.2'
        file_meta.MediaStorageSOPInstanceUID = '1.2.3.4.5'
        file_meta.ImplementationClassUID = '1.2.3.4'

        ds = pydicom.dataset.FileDataset(
            "test.dcm",
            {},
            file_meta=file_meta,
            preamble=b"\0" * 128,
        )

        ds.PatientName = "Test^Patient"
        ds.PatientID = "12345"
        ds.Modality = "CT"
        ds.StudyDate = "20260501"
        ds.StudyTime = "120000"
        ds.SeriesInstanceUID = "1.2.3.4.5.6"
        ds.StudyInstanceUID = "1.2.3.4.5"
        ds.SOPInstanceUID = "1.2.3.4.5.6.7"
        ds.SOPClassUID = '1.2.840.10008.5.1.4.1.1.2'
        ds.Manufacturer = "SIEMENS"

        output = io.BytesIO()
        ds.save_as(output, write_like_original=False)
        return output.getvalue()

    @pytest.mark.asyncio
    async def test_normalize_siemens_dicom(self, engine: NormalizerEngine):
        """Test normalizing Siemens DICOM."""
        dicom_bytes = self.create_minimal_dicom()

        result = await engine.normalize_dicom(
            file_id="test_file_1",
            filename="test.dcm",
            dicom_bytes=dicom_bytes,
            modality="CT",
            auto_normalize=False,
        )

        assert result.file_id == "test_file_1"
        assert result.detected_supplier == "siemens"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_invalid_dicom_handling(self, engine: NormalizerEngine):
        """Test handling of invalid DICOM files."""
        invalid_bytes = b"NOT A DICOM FILE"

        result = await engine.normalize_dicom(
            file_id="test_file_invalid",
            filename="invalid.dcm",
            dicom_bytes=invalid_bytes,
            modality="CT",
            auto_normalize=False,
        )

        assert result.file_id == "test_file_invalid"
        assert result.error is not None
        assert result.applied is False


class TestVendorPrivateTags:
    """Test vendor-specific private tag extraction (Design Section 5.3)."""

    @pytest.fixture
    def photometric_config(self) -> NormalizationConfig:
        """Config with photometric algorithm enabled."""
        config = NormalizationConfig(
            modality="CT",
            algorithms={
                "pixel_spacing": True,
                "missing_tags": True,
                "photometric": True,
                "charset": True,
            },
            risk_tiers={
                "safe": "auto",
                "medium": "auto",  # auto-apply for test simplicity
                "risky": "reject",
            },
        )
        return config

    @pytest.fixture
    def default_config(self) -> NormalizationConfig:
        """Config with pixel_spacing and missing_tags enabled."""
        config = NormalizationConfig(
            modality="CT",
            algorithms={
                "pixel_spacing": True,
                "missing_tags": True,
                "photometric": False,
                "charset": True,
            },
            risk_tiers={
                "safe": "auto",
                "medium": "manual",
                "risky": "reject",
            },
        )
        return config

    def test_extract_private_tags_helper(self):
        """Test _extract_private_tags helper filters by group correctly."""
        file_data = {
            "0008,0020": "20260501",
            "0019,1008": "0.5\\0.5",
            "0019,1010": "MONO",
            "0028,0030": None,
        }
        result = _extract_private_tags(file_data, 0x0019)
        assert "0019,1008" in result
        assert "0019,1010" in result
        assert "0008,0020" not in result

    def test_siemens_private_tag_pixel_spacing(self, default_config: NormalizationConfig):
        """Test Siemens private tag (0019,1008) fills missing PixelSpacing."""
        normalizer = SiemensNormalizer(default_config, "siemens")
        file_data = {
            "0008,0070": "SIEMENS",
            "0008,0020": "20260501",
            "0008,0030": "120000",
            "0019,1008": "0.5\\0.5",   # Siemens private PixelSpacing
            # 0028,0030 deliberately absent
        }

        changes = normalizer.normalize(file_data)

        pixel_changes = [c for c in changes if c.tag == "0028,0030"]
        assert len(pixel_changes) == 1
        assert "0019,1008" in pixel_changes[0].rationale
        assert pixel_changes[0].risk_level == "safe"
        assert file_data["0028,0030"] == "0.5\\0.5"

    def test_siemens_private_tag_photometric(self, photometric_config: NormalizationConfig):
        """Test Siemens private tag (0019,1010) infers PhotometricInterpretation."""
        normalizer = SiemensNormalizer(photometric_config, "siemens")
        file_data = {
            "0008,0070": "SIEMENS",
            "0008,0020": "20260501",
            "0008,0030": "120000",
            "0019,1010": "MONO",  # Siemens photometric hint
            # 0028,0004 deliberately absent
        }

        changes = normalizer.normalize(file_data)

        photo_changes = [c for c in changes if c.tag == "0028,0004"]
        assert len(photo_changes) == 1
        assert photo_changes[0].corrected == "MONOCHROME2"
        assert photo_changes[0].risk_level == "medium"

    def test_siemens_photometric_rgb_mapping(self, photometric_config: NormalizationConfig):
        """Test Siemens private photometric hint maps RGB correctly."""
        normalizer = SiemensNormalizer(photometric_config, "siemens")
        file_data = {
            "0008,0070": "SIEMENS",
            "0019,1010": "RGB",
        }
        changes = normalizer.normalize(file_data)
        photo_changes = [c for c in changes if c.tag == "0028,0004"]
        assert photo_changes[0].corrected == "RGB"

    def test_siemens_no_private_tags_no_pixel_change(self, default_config: NormalizationConfig):
        """Test Siemens normalizer does not add PixelSpacing if private tag absent."""
        normalizer = SiemensNormalizer(default_config, "siemens")
        file_data = {
            "0008,0070": "SIEMENS",
            "0008,0020": "20260501",
            # No 0019,1008 private tag, no 0028,0030
        }
        changes = normalizer.normalize(file_data)
        pixel_changes = [c for c in changes if c.tag == "0028,0030"]
        assert len(pixel_changes) == 0  # no private tag -> no change

    def test_ge_private_tag_pixel_spacing(self, default_config: NormalizationConfig):
        """Test GE private tag fills missing PixelSpacing."""
        normalizer = GENormalizer(default_config, "ge")
        file_data = {
            "0008,0070": "GE MEDICAL SYSTEMS",
            "0008,0020": "20260501",
            "0019,1004": "0.625\\0.625",  # GE private PixelSpacing
            # 0028,0030 deliberately absent
        }

        changes = normalizer.normalize(file_data)

        pixel_changes = [c for c in changes if c.tag == "0028,0030"]
        assert len(pixel_changes) == 1
        assert pixel_changes[0].risk_level == "safe"
        assert file_data["0028,0030"] == "0.625\\0.625"

    def test_ge_jpeg_sof_monochrome_inference(self, photometric_config: NormalizationConfig):
        """Test GE JPEG SOF marker inspection correctly infers MONOCHROME2."""
        # Minimal JPEG data with SOF0 marker for 1 component
        # FF D8 (SOI) + FF C0 (SOF0) + length(2) + precision(1) + height(2) + width(2) + components(1)
        jpeg_sof0 = (
            b"\xFF\xD8"          # SOI
            b"\xFF\xC0"          # SOF0 marker
            b"\x00\x0B"          # length = 11
            b"\x08"              # precision = 8-bit
            b"\x01\x00"          # height = 256
            b"\x01\x00"          # width = 256
            b"\x01"              # num_components = 1 -> MONOCHROME2
        )

        normalizer = GENormalizer(photometric_config, "ge")
        file_data = {
            "0008,0070": "GE",
            "0008,0020": "20260501",
            "7FE0,0010": jpeg_sof0,
        }

        changes = normalizer.normalize(file_data)
        photo_changes = [c for c in changes if c.tag == "0028,0004"]
        assert len(photo_changes) == 1
        assert photo_changes[0].corrected == "MONOCHROME2"

    def test_philips_private_tag_pixel_spacing(self, default_config: NormalizationConfig):
        """Test Philips private tag fills missing PixelSpacing."""
        normalizer = PhilipsNormalizer(default_config, "philips")
        file_data = {
            "0008,0070": "PHILIPS",
            "0008,0020": "20260501",
            "2001,1026": "0.9\\0.9",  # Philips private PixelSpacing
            # 0028,0030 deliberately absent
        }

        changes = normalizer.normalize(file_data)

        pixel_changes = [c for c in changes if c.tag == "0028,0030"]
        assert len(pixel_changes) == 1
        assert pixel_changes[0].risk_level == "safe"
        assert file_data["0028,0030"] == "0.9\\0.9"

    def test_philips_jpeg_artifact_detection(self, photometric_config: NormalizationConfig):
        """Test Philips JPEG artifact detection sets PhotometricInterpretation."""
        normalizer = PhilipsNormalizer(photometric_config, "philips")
        file_data = {
            "0008,0070": "PHILIPS",
            "0008,0020": "20260501",
            "0002,0010": "1.2.840.10008.1.2.4.50",  # JPEG Baseline transfer syntax
            "0028,0002": 1,   # SamplesPerPixel = 1
            # 0028,0004 deliberately absent
        }

        changes = normalizer.normalize(file_data)
        photo_changes = [c for c in changes if c.tag == "0028,0004"]
        assert len(photo_changes) == 1
        assert photo_changes[0].corrected == "MONOCHROME2"
        assert photo_changes[0].risk_level == "medium"

    def test_philips_no_jpeg_no_artifact(self, photometric_config: NormalizationConfig):
        """Test Philips normalizer does not set photometric when no JPEG transfer syntax."""
        normalizer = PhilipsNormalizer(photometric_config, "philips")
        file_data = {
            "0008,0070": "PHILIPS",
            "0008,0020": "20260501",
            # No transfer syntax tag (not JPEG)
            # 0028,0004 deliberately absent
        }

        changes = normalizer.normalize(file_data)
        photo_changes = [c for c in changes if c.tag == "0028,0004"]
        # Without JPEG artifact signal, no photometric change should be made
        assert len(photo_changes) == 0


class TestNormalizationReviewCreation:
    """Test medium-risk review record creation."""

    @pytest.mark.asyncio
    async def test_add_review_defer_decision(self, test_db: AsyncSession, test_user: User):
        """Test creating a deferred review record for medium-risk changes."""
        batch = await BatchJobService.create_batch_job(
            test_db,
            user_id=str(test_user.id),
            total_files=1,
        )
        await test_db.commit()

        file = await BatchJobService.add_batch_file(
            test_db,
            batch_id=str(batch.id),
            filename="medium_risk.dcm",
            sequence_number=1,
        )
        await test_db.commit()

        review = await BatchJobService.add_review(
            test_db,
            batch_id=str(batch.id),
            file_id=str(file.id),
            reviewer_id=str(test_user.id),
            decision="defer",
            comment="Auto-created: medium-risk changes require manual approval",
            reviewed_changes={"changes": [{"tag": "0028,0004", "risk_level": "medium"}]},
        )
        await test_db.commit()

        assert review.decision == "defer"
        assert review.batch_id == str(batch.id)
        assert review.file_id == str(file.id)

    @pytest.mark.asyncio
    async def test_batch_statistics_counts_pending_reviews(
        self, test_db: AsyncSession, test_user: User
    ):
        """Test that batch statistics correctly count pending (deferred) reviews."""
        batch = await BatchJobService.create_batch_job(
            test_db,
            user_id=str(test_user.id),
            total_files=2,
        )
        await test_db.commit()

        for i in range(2):
            f = await BatchJobService.add_batch_file(
                test_db,
                batch_id=str(batch.id),
                filename=f"file_{i}.dcm",
                sequence_number=i + 1,
            )
            await test_db.commit()

            await BatchJobService.add_review(
                test_db,
                batch_id=str(batch.id),
                file_id=str(f.id),
                reviewer_id=str(test_user.id),
                decision="defer",
            )
        await test_db.commit()

        stats = await BatchJobService.get_batch_statistics(test_db, str(batch.id))
        assert stats["pending_reviews"] == 2


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_batch_with_zero_files(self, test_db: AsyncSession, test_user: User):
        """Test batch with zero files."""
        batch = await BatchJobService.create_batch_job(
            test_db,
            user_id=str(test_user.id),
            total_files=0,
        )

        # Should still create batch
        assert batch.total_files == 0

    @pytest.mark.asyncio
    async def test_concurrent_file_processing(self, test_db: AsyncSession, test_user: User):
        """Test simulating concurrent file processing."""
        batch = await BatchJobService.create_batch_job(
            test_db,
            user_id=str(test_user.id),
            total_files=100,
        )
        await test_db.commit()

        # Simulate concurrent updates
        for i in range(100):
            await BatchJobService.increment_batch_counters(
                test_db,
                str(batch.id),
                processed=1,
                succeeded=1,
                failed=0,
            )

        batch = await BatchJobService.get_batch_job(test_db, str(batch.id))
        assert batch.processed_files == 100
        assert batch.succeeded_files == 100

    @pytest.mark.asyncio
    async def test_batch_with_errors(self, test_db: AsyncSession, test_user: User):
        """Test batch tracking errors correctly."""
        batch = await BatchJobService.create_batch_job(
            test_db,
            user_id=str(test_user.id),
            total_files=10,
        )
        await test_db.commit()

        # Add file with error
        file = await BatchJobService.add_batch_file(
            test_db,
            batch_id=str(batch.id),
            filename="error.dcm",
            sequence_number=1,
        )
        await test_db.commit()

        await BatchJobService.update_file_status(
            test_db,
            str(file.id),
            "failed",
            error_message="Invalid DICOM format",
        )
        await test_db.commit()

        stats = await BatchJobService.get_batch_statistics(test_db, str(batch.id))
        assert stats["status_distribution"]["failed"] == 1
