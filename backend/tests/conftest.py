"""Pytest configuration and fixtures for OpenPACS tests."""
import io
import struct
import os
import json
import uuid
import asyncio
import logging
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pydicom
import pydicom.encaps
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, ImplicitVRLittleEndian
import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Configure logging for tests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# pydicom < 3.0 exported JPEGBaseline; 3.x renamed it to JPEGBaseline8Bit
try:
    from pydicom.uid import JPEGBaseline
except ImportError:
    from pydicom.uid import JPEGBaseline8Bit as JPEGBaseline

# pydicom 3.x uses FileMetaDataset for file_meta; fall back to Dataset for older versions
try:
    from pydicom.dataset import FileMetaDataset
except ImportError:
    FileMetaDataset = Dataset  # type: ignore[assignment,misc]


def _ds_to_bytes(ds: FileDataset) -> bytes:
    """Serialize a FileDataset to raw DICOM bytes (compatible with pydicom 2.x and 3.x)."""
    buf = io.BytesIO()
    try:
        # pydicom 3.x
        pydicom.dcmwrite(buf, ds)
    except AttributeError:
        # pydicom 2.x fallback
        ds.save_as(buf, write_like_original=False)
    return buf.getvalue()


def _make_file_meta(sop_class_uid: str, sop_instance_uid: str, transfer_syntax=None):
    """Create a FileMetaDataset (or plain Dataset) compatible with current pydicom."""
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = sop_class_uid
    file_meta.MediaStorageSOPInstanceUID = sop_instance_uid
    file_meta.TransferSyntaxUID = transfer_syntax or ExplicitVRLittleEndian
    return file_meta


def _make_file_dataset(filename: str, file_meta, is_implicit_VR: bool = False) -> FileDataset:
    """Create a FileDataset with compatibility for pydicom 2.x (filename keyword) and 3.x (positional)."""
    try:
        # pydicom 3.x: first arg is positional (filename_or_obj)
        return FileDataset(
            filename,
            dataset={},
            file_meta=file_meta,
            preamble=b"\0" * 128,
            is_implicit_VR=is_implicit_VR,
            is_little_endian=True,
        )
    except TypeError:
        # pydicom 2.x: keyword arg 'filename'
        return FileDataset(  # type: ignore[call-arg]
            filename=filename,
            dataset={},
            file_meta=file_meta,
            preamble=b"\0" * 128,
            is_implicit_VR=is_implicit_VR,
            is_little_endian=True,
        )


@pytest.fixture
def minimal_dicom():
    """Create a minimal valid DICOM file with required tags."""
    file_meta = _make_file_meta(
        "1.2.840.10008.5.1.4.1.1.2",  # CT Image Storage
        "1.2.3.4.5.6.7.8.9",
    )
    ds = _make_file_dataset("test.dcm", file_meta)

    # Add mandatory tags
    ds.PatientName = "Test^Patient"
    ds.PatientID = "12345"
    ds.Modality = "CT"
    ds.SeriesInstanceUID = "1.2.3.4.5.6"
    ds.StudyInstanceUID = "1.2.3.4.5"
    ds.SOPInstanceUID = "1.2.3.4.5.6.7.8.9"
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.StudyDate = datetime.now().strftime("%Y%m%d")

    # Add pixel data (minimal)
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows = 512
    ds.Columns = 512
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.PixelData = b"\0" * 512 * 512 * 2

    return _ds_to_bytes(ds)


@pytest.fixture
def dicom_with_pixel_spacing():
    """Create DICOM with Pixel Spacing (for JPEG density validation)."""
    file_meta = _make_file_meta(
        "1.2.840.10008.5.1.4.1.1.66.3",  # CR Image Storage
        "1.2.3.4.5.6.7.8.9.1",
    )
    ds = _make_file_dataset("test_cr.dcm", file_meta)

    ds.PatientName = "Chest^XRay"
    ds.PatientID = "CXR001"
    ds.Modality = "CR"
    ds.SeriesInstanceUID = "1.2.3.4.5.6.7"
    ds.StudyInstanceUID = "1.2.3.4.5.6"
    ds.SOPInstanceUID = "1.2.3.4.5.6.7.8.9.1"
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.66.3"
    ds.StudyDate = datetime.now().strftime("%Y%m%d")

    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows = 2048
    ds.Columns = 2048
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0

    # Key: Pixel Spacing for JPEG density check
    # 0.0847 mm = 300 DPI (25.4 / 300 ≈ 0.0847)
    ds.PixelSpacing = [0.0847, 0.0847]

    # Minimal pixel data
    ds.PixelData = b"\x80" * 2048 * 2048

    return _ds_to_bytes(ds)


@pytest.fixture
def jfif_dicom_300dpi(dicom_with_pixel_spacing):
    """Create DICOM with JFIF header embedding 300 DPI (exact match)."""
    ds = pydicom.dcmread(io.BytesIO(dicom_with_pixel_spacing), force=True)

    # Set JPEGBaseline transfer syntax so _check_jpeg_density executes
    ds.file_meta.TransferSyntaxUID = JPEGBaseline

    # Build JFIF header: FF D8 FF E0 [len] JFIF\0 [version] [unit] [Xdensity] [Ydensity]
    jfif_header = bytearray()
    jfif_header.extend(b"\xFF\xD8")  # SOI
    jfif_header.extend(b"\xFF\xE0")  # APP0
    jfif_header.extend(struct.pack(">H", 16))  # Length (16 bytes for APP0)
    jfif_header.extend(b"JFIF\x00")  # Identifier
    jfif_header.extend(b"\x01\x01")  # Version 1.1
    jfif_header.extend(b"\x01")  # Unit: DPI
    jfif_header.extend(struct.pack(">HH", 300, 300))  # X and Y density

    # Wrap pixel data in minimal JPEG structure
    jpeg_frame = bytes(jfif_header) + b"\xFF\xD9"  # EOI

    # pydicom 3.x requires encapsulated pixel data for compressed transfer syntaxes
    ds.PixelData = pydicom.encaps.encapsulate([jpeg_frame])
    ds["PixelData"].is_undefined_length = True
    return _ds_to_bytes(ds)


@pytest.fixture
def jfif_dicom_315dpi(dicom_with_pixel_spacing):
    """Create DICOM with JFIF 320 DPI (6.7% mismatch vs 300 DPI spacing = WARNING tier 5-20%).

    PixelSpacing 0.0847 mm corresponds to ~300 DPI (25.4/300 = 0.08467 mm).
    320 DPI = 0.07938 mm → |0.0847 - 0.07938| / 0.0847 * 100 ≈ 6.3% (WARNING range 5-20%).
    """
    ds = pydicom.dcmread(io.BytesIO(dicom_with_pixel_spacing), force=True)

    # Set JPEGBaseline transfer syntax so _check_jpeg_density executes
    ds.file_meta.TransferSyntaxUID = JPEGBaseline

    jfif_header = bytearray()
    jfif_header.extend(b"\xFF\xD8\xFF\xE0")
    jfif_header.extend(struct.pack(">H", 16))
    jfif_header.extend(b"JFIF\x00\x01\x01\x01")  # Unit: DPI
    jfif_header.extend(struct.pack(">HH", 320, 320))  # X and Y density (6.3% mismatch = WARNING)

    jpeg_frame = bytes(jfif_header) + b"\xFF\xD9"
    ds.PixelData = pydicom.encaps.encapsulate([jpeg_frame])
    ds["PixelData"].is_undefined_length = True
    return _ds_to_bytes(ds)


@pytest.fixture
def jfif_dicom_375dpi(dicom_with_pixel_spacing):
    """Create DICOM with JFIF 375 DPI (25% mismatch = ERROR)."""
    ds = pydicom.dcmread(io.BytesIO(dicom_with_pixel_spacing), force=True)

    # Set JPEGBaseline transfer syntax so _check_jpeg_density executes
    ds.file_meta.TransferSyntaxUID = JPEGBaseline

    jfif_header = bytearray()
    jfif_header.extend(b"\xFF\xD8\xFF\xE0")
    jfif_header.extend(struct.pack(">H", 16))
    jfif_header.extend(b"JFIF\x00\x01\x01\x01")  # Unit: DPI
    jfif_header.extend(struct.pack(">HH", 375, 375))  # X and Y density (high mismatch)

    jpeg_frame = bytes(jfif_header) + b"\xFF\xD9"
    ds.PixelData = pydicom.encaps.encapsulate([jpeg_frame])
    ds["PixelData"].is_undefined_length = True
    return _ds_to_bytes(ds)


@pytest.fixture
def dicom_missing_patient_id():
    """Create DICOM without mandatory PatientID tag."""
    file_meta = _make_file_meta(
        "1.2.840.10008.5.1.4.1.1.2",
        "1.2.3.4.5.6.7.8.9.2",
    )
    ds = _make_file_dataset("test_missing_pid.dcm", file_meta)

    ds.PatientName = "Missing^ID"
    # Note: PatientID is NOT set
    ds.Modality = "CT"
    ds.SeriesInstanceUID = "1.2.3.4.5.6.8"
    ds.StudyInstanceUID = "1.2.3.4.5.7"
    ds.SOPInstanceUID = "1.2.3.4.5.6.7.8.9.2"
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.StudyDate = datetime.now().strftime("%Y%m%d")

    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows = 256
    ds.Columns = 256
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.PixelData = b"\0" * 256 * 256 * 2

    return _ds_to_bytes(ds)


# ============================================================================
# Phase 6 E2E Testing Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def docker_stack():
    """
    Session-scoped fixture to manage Docker Compose stack.
    Starts all containers (Postgres, Redis, Orthanc, FastAPI).
    Waits for health checks before yielding.
    Stops and cleans up on teardown.
    """
    docker_compose_path = Path(__file__).parent.parent.parent / "docker-compose.yml"

    if not docker_compose_path.exists():
        pytest.skip(f"docker-compose.yml not found at {docker_compose_path}")

    logger.info(f"Starting Docker Compose from {docker_compose_path}")

    try:
        # Start containers
        subprocess.run(
            ["docker-compose", "up", "-d"],
            cwd=docker_compose_path.parent,
            check=True,
            capture_output=True,
        )

        # Wait for FastAPI health endpoint
        health_url = "http://localhost:8001/health"
        max_retries = 30
        for attempt in range(max_retries):
            try:
                resp = httpx.get(health_url, timeout=5)
                if resp.status_code == 200:
                    logger.info("FastAPI health check passed")
                    break
            except (httpx.ConnectError, httpx.TimeoutException):
                if attempt == max_retries - 1:
                    raise RuntimeError(f"FastAPI not healthy after {max_retries} attempts")
                time.sleep(1)

        # Wait for PostgreSQL
        max_retries = 30
        for attempt in range(max_retries):
            try:
                engine = create_async_engine(
                    "postgresql+asyncpg://openpacs:OpenPACS2026@localhost:5432/openpacs",
                    echo=False,
                )
                async def check_db():
                    async with engine.begin() as conn:
                        await conn.execute(text("SELECT 1"))
                asyncio.run(check_db())
                logger.info("PostgreSQL health check passed")
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    raise RuntimeError(f"PostgreSQL not healthy after {max_retries} attempts: {e}")
                time.sleep(1)

        yield {
            "docker_compose_path": docker_compose_path,
            "containers": ["postgres", "redis", "orthanc", "backend"],
        }

    finally:
        logger.info("Stopping Docker Compose")
        subprocess.run(
            ["docker-compose", "down"],
            cwd=docker_compose_path.parent,
            capture_output=True,
        )


@pytest.fixture
def database_snapshot():
    """Create and restore database snapshots for test isolation."""
    snapshot_dir = Path("/tmp/openpacs_test_snapshots")
    snapshot_dir.mkdir(exist_ok=True)

    async def backup_db():
        """Backup current database state."""
        snapshot_id = str(uuid.uuid4())
        engine = create_async_engine(
            "postgresql+asyncpg://openpacs:OpenPACS2026@localhost:5432/openpacs",
            echo=False,
        )

        async with engine.begin() as conn:
            # Export schema + data (simple approach: dump key tables)
            result = await conn.execute(
                text("""
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'public'
                """)
            )
            tables = [row[0] for row in result]

            snapshot_data = {}
            for table in tables:
                result = await conn.execute(text(f"SELECT * FROM {table}"))
                snapshot_data[table] = [dict(row._mapping) for row in result]

        snapshot_file = snapshot_dir / f"{snapshot_id}.json"
        with open(snapshot_file, "w") as f:
            json.dump(snapshot_data, f, default=str)

        await engine.dispose()
        return snapshot_id

    async def restore_db(snapshot_id):
        """Restore database to snapshot state."""
        snapshot_file = snapshot_dir / f"{snapshot_id}.json"
        if not snapshot_file.exists():
            raise FileNotFoundError(f"Snapshot {snapshot_id} not found")

        engine = create_async_engine(
            "postgresql+asyncpg://openpacs:OpenPACS2026@localhost:5432/openpacs",
            echo=False,
        )

        with open(snapshot_file) as f:
            snapshot_data = json.load(f)

        async with engine.begin() as conn:
            # Clear tables (in reverse order to avoid FK constraints)
            tables = list(snapshot_data.keys())
            for table in reversed(tables):
                await conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))

            # Restore data
            for table, rows in snapshot_data.items():
                if not rows:
                    continue
                columns = list(rows[0].keys())
                col_list = ", ".join(columns)
                for row in rows:
                    values = ", ".join([f"'{v}'" if v else "NULL" for v in row.values()])
                    await conn.execute(
                        text(f"INSERT INTO {table} ({col_list}) VALUES ({values})")
                    )

        await engine.dispose()

    return {
        "backup": backup_db,
        "restore": restore_db,
    }


@pytest.fixture
def reset_db(database_snapshot, docker_stack):
    """
    Reset database before/after E2E tests.
    NOT autouse — only used by E2E tests that explicitly request it.
    """
    # Backup database before test
    async def _backup():
        return await database_snapshot["backup"]()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    snapshot_id = loop.run_until_complete(_backup())

    yield

    # Restore database after test
    async def _restore():
        await database_snapshot["restore"](snapshot_id)

    loop.run_until_complete(_restore())


@pytest.fixture
async def authenticated_client():
    """
    AsyncClient with Bearer JWT token (test user).
    Automatically authenticates and injects Authorization header.
    """
    # Login as test user
    login_payload = {
        "username": "testuser",
        "password": "TestPassword123!",
    }

    async with httpx.AsyncClient(base_url="http://localhost:8001") as client:
        # Try login (may fail if user doesn't exist yet)
        try:
            response = await client.post("/api/v1/auth/login", json=login_payload)
            if response.status_code == 200:
                token = response.json()["access_token"]
            else:
                # Create test user first (admin can do this)
                raise RuntimeError("Test user not found; setup required")
        except Exception as e:
            logger.warning(f"Could not authenticate test user: {e}")
            token = "mock-jwt-token-for-testing"

        # Create client with auth header
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(
            base_url="http://localhost:8001",
            headers=headers,
        ) as auth_client:
            yield auth_client


@pytest.fixture
def sample_dicom_file(minimal_dicom):
    """
    Return minimal valid DICOM CT file (pre-generated).
    Used for Phase 6 E2E workflow testing.
    """
    return minimal_dicom


@pytest.fixture
async def sample_model(authenticated_client):
    """
    Register and return a pre-configured ONNX model.
    Creates a minimal ONNX dummy model for testing.
    """
    # Create minimal ONNX model (using numpy/onnx)
    try:
        import numpy as np
        import onnx
        from onnx import helper, TensorProto
    except ImportError:
        pytest.skip("onnx package not installed")

    # Define simple model: input → output (identity)
    X = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 224, 224])
    Y = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 1])

    node = helper.make_node(
        "Identity",
        inputs=["input"],
        outputs=["output"],
    )

    graph = helper.make_graph(
        [node],
        "test_model",
        [X],
        [Y],
    )

    model = helper.make_model(graph, producer_name="test")
    onnx.checker.check_model(model)

    # Save to temp file
    model_path = Path("/tmp/test_model.onnx")
    onnx.save(model, str(model_path))

    # Register model via API
    model_name = f"test_model_{uuid.uuid4().hex[:8]}"
    register_payload = {
        "name": model_name,
        "version": "1.0",
        "modality": "CT",
        "description": "Test segmentation model",
    }

    with open(model_path, "rb") as f:
        files = {"file": ("model.onnx", f, "application/octet-stream")}
        response = await authenticated_client.post(
            "/api/v1/ai/models",
            data=register_payload,
            files=files,
        )

    if response.status_code != 201:
        raise RuntimeError(f"Failed to register model: {response.text}")

    model_data = response.json()
    model_id = model_data["id"]

    # Activate model
    response = await authenticated_client.put(
        f"/api/v1/ai/models/{model_id}",
        json={"status": "active"},
    )

    if response.status_code != 200:
        raise RuntimeError(f"Failed to activate model: {response.text}")

    # Cleanup
    model_path.unlink()

    return {
        "id": model_id,
        "name": model_name,
        "version": "1.0",
        "modality": "CT",
    }


@pytest.fixture
async def websocket_client():
    """
    WebSocket client with JWT authentication.
    Connects to /api/v1/ws/ai/{job_id}?token={jwt}
    """
    # This will be implemented in Day 2
    # For now, provide a placeholder factory
    async def connect_ws(job_id: str, token: str):
        """Connect to WebSocket endpoint with JWT."""
        from websockets.client import connect
        uri = f"ws://localhost:8001/api/v1/ws/ai/{job_id}?token={token}"
        return await connect(uri)

    return connect_ws


@pytest.fixture
def metrics_collector():
    """
    Metrics collector for latency, throughput, errors.
    Tracks: response times, error counts, job status.
    """
    class MetricsCollector:
        def __init__(self):
            self.latencies = []
            self.errors = []
            self.job_count = 0
            self.start_time = datetime.now()

        def record_latency(self, latency_ms: float):
            self.latencies.append(latency_ms)

        def record_error(self, error: str):
            self.errors.append(error)

        def increment_jobs(self):
            self.job_count += 1

        def get_stats(self):
            """Return latency percentiles (p50, p95, p99)."""
            if not self.latencies:
                return None

            sorted_lat = sorted(self.latencies)
            return {
                "count": len(sorted_lat),
                "p50": sorted_lat[int(len(sorted_lat) * 0.50)],
                "p95": sorted_lat[int(len(sorted_lat) * 0.95)],
                "p99": sorted_lat[int(len(sorted_lat) * 0.99)],
                "min": min(sorted_lat),
                "max": max(sorted_lat),
                "errors": len(self.errors),
                "error_rate": len(self.errors) / (self.job_count or 1) * 100,
                "duration_sec": (datetime.now() - self.start_time).total_seconds(),
            }

    return MetricsCollector()
