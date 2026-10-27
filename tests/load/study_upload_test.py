"""
Study Upload Throughput Test
=============================
Simulates daily 1,000 study uploads via Orthanc REST API.
Measures upload speed, DB indexing time, and search performance under load.

Usage:
    python tests/load/study_upload_test.py
    python tests/load/study_upload_test.py --studies 100 --concurrent 5

Requires: pip install pydicom numpy
"""

import argparse
import asyncio
import io
import os
import random
import ssl
import statistics
import struct
import time
from dataclasses import dataclass, field

try:
    import pydicom
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    from pydicom.sequence import Sequence
except ImportError:
    print("Install pydicom: pip install pydicom")
    exit(1)

try:
    import httpx
except ImportError:
    print("Install httpx: pip install httpx")
    exit(1)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ORTHANC_URL = os.getenv("ORTHANC_URL", "https://his.example.org/pacs")
ORTHANC_USER = os.getenv("ORTHANC_USER", "admin")
ORTHANC_PASS = os.getenv("ORTHANC_PASS", "CHANGE_ME")
DICOMWEB_URL = os.getenv("DICOMWEB_URL", "https://his.example.org/dicom-web")

MODALITIES = ["CR", "CT", "DX", "MR", "US"]
BODY_PARTS = ["CHEST", "ABDOMEN", "HEAD", "SPINE", "PELVIS"]


@dataclass
class UploadResult:
    total_studies: int = 0
    successful: int = 0
    failed: int = 0
    upload_times: list = field(default_factory=list)
    search_times_before: list = field(default_factory=list)
    search_times_after: list = field(default_factory=list)
    errors: list = field(default_factory=list)


result = UploadResult()


def generate_dicom_file(
    study_uid: str,
    series_uid: str,
    sop_uid: str,
    patient_id: str = "PT-LOAD-0001",
    patient_name: str = "LOAD^TEST",
    modality: str = "CR",
) -> bytes:
    """Generate a minimal valid DICOM file in memory."""
    ds = Dataset()

    # Patient
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.PatientBirthDate = "19800101"
    ds.PatientSex = "O"

    # Study
    ds.StudyInstanceUID = study_uid
    ds.StudyDate = "20260520"
    ds.StudyTime = "120000"
    ds.StudyDescription = f"Load Test {modality}"
    ds.AccessionNumber = f"LOAD-{random.randint(10000,99999)}"
    ds.ReferringPhysicianName = "LOAD^DOCTOR"
    ds.StudyID = "LOAD"

    # Series
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = 1
    ds.Modality = modality
    ds.BodyPartExamined = random.choice(BODY_PARTS)
    ds.SeriesDescription = f"{modality} Series"

    # Instance
    ds.SOPInstanceUID = sop_uid
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.1"  # CR Image Storage
    ds.InstanceNumber = 1

    # Pixel data (64x64 minimal)
    ds.Rows = 64
    ds.Columns = 64
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    pixels = struct.pack(f"<{64*64}H", *[random.randint(0, 4095) for _ in range(64 * 64)])
    ds.PixelData = pixels

    ds.is_little_endian = True
    ds.is_implicit_VR = False

    # Write to buffer
    buf = io.BytesIO()
    file_ds = FileDataset(
        filename_or_obj=buf,
        dataset=ds,
        file_meta=pydicom.Dataset(),
        preamble=b"\x00" * 128,
    )
    file_ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    file_ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    file_ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_ds.file_meta.FileMetaInformationGroupLength = 0
    file_ds.file_meta.FileMetaInformationVersion = b"\x00\x01"
    file_ds.file_meta.ImplementationClassUID = "1.2.826.0.1.3680043.8.498.1"

    file_ds.save_as(buf)
    return buf.getvalue()


async def upload_study(client: httpx.AsyncClient, study_index: int):
    """Upload one study (1-3 series, 1-5 instances each) to Orthanc."""
    study_uid = generate_uid()
    modality = random.choice(MODALITIES)
    patient_id = f"PT-LOAD-{study_index:05d}"
    patient_name = f"LOAD^TEST^{study_index}"

    num_series = random.randint(1, 3)
    total_uploaded = 0
    start = time.time()

    for s in range(num_series):
        series_uid = generate_uid()
        num_instances = random.randint(1, 5)

        for i in range(num_instances):
            sop_uid = generate_uid()
            dcm_bytes = generate_dicom_file(
                study_uid=study_uid,
                series_uid=series_uid,
                sop_uid=sop_uid,
                patient_id=patient_id,
                patient_name=patient_name,
                modality=modality,
            )
            try:
                resp = await client.post(
                    f"{ORTHANC_URL}/instances",
                    content=dcm_bytes,
                    headers={"Content-Type": "application/dicom"},
                )
                if resp.status_code == 200:
                    total_uploaded += 1
                else:
                    result.errors.append(
                        f"Study {study_index}: HTTP {resp.status_code}"
                    )
            except Exception as e:
                result.errors.append(f"Study {study_index}: {type(e).__name__}")

    elapsed = time.time() - start
    result.upload_times.append(elapsed)

    if total_uploaded > 0:
        result.successful += 1
    else:
        result.failed += 1

    result.total_studies += 1
    return study_uid


async def measure_search(client: httpx.AsyncClient, label: str) -> float:
    """Measure DICOMweb search time."""
    start = time.time()
    try:
        resp = await client.get(f"{DICOMWEB_URL}/studies", params={"limit": 50})
        elapsed = (time.time() - start) * 1000
        return elapsed
    except Exception:
        return -1


async def run_test(num_studies: int, concurrent: int):
    """Run study upload throughput test."""
    print(f"Study Upload Test: {num_studies} studies, {concurrent} concurrent")
    print("-" * 60)

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    async with httpx.AsyncClient(
        auth=(ORTHANC_USER, ORTHANC_PASS),
        verify=False,
        timeout=60.0,
    ) as client:

        # Baseline search
        for _ in range(3):
            t = await measure_search(client, "before")
            if t > 0:
                result.search_times_before.append(t)

        # Upload studies in batches
        sem = asyncio.Semaphore(concurrent)

        async def throttled_upload(idx):
            async with sem:
                return await upload_study(client, idx)

        start_time = time.time()
        tasks = [throttled_upload(i) for i in range(num_studies)]
        await asyncio.gather(*tasks, return_exceptions=True)
        total_elapsed = time.time() - start_time

        # Post-upload search
        await asyncio.sleep(2)
        for _ in range(3):
            t = await measure_search(client, "after")
            if t > 0:
                result.search_times_after.append(t)

    # Report
    print("\n" + "=" * 60)
    print("Study Upload Test Results")
    print("=" * 60)
    print(f"Total studies:     {result.total_studies}")
    print(f"Successful:        {result.successful}")
    print(f"Failed:            {result.failed}")
    print(f"Total time:        {total_elapsed:.1f}s")

    throughput = result.successful / total_elapsed * 3600 if total_elapsed > 0 else 0
    print(f"Throughput:        {throughput:.0f} studies/hr (target: 42/hr)")

    if result.upload_times:
        print(f"Upload time avg:   {statistics.mean(result.upload_times):.2f}s")
        print(f"Upload time p95:   {sorted(result.upload_times)[int(len(result.upload_times)*0.95)]:.2f}s")

    if result.search_times_before:
        print(f"Search before:     {statistics.mean(result.search_times_before):.0f}ms")
    if result.search_times_after:
        print(f"Search after:      {statistics.mean(result.search_times_after):.0f}ms")
        if result.search_times_before:
            degradation = (
                statistics.mean(result.search_times_after)
                / max(statistics.mean(result.search_times_before), 1)
                - 1
            ) * 100
            print(f"Search degradation: {degradation:+.1f}%")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for err in result.errors[:10]:
            print(f"  - {err}")

    # Pass/Fail
    issues = []
    success_rate = result.successful / max(result.total_studies, 1)
    if success_rate < 0.95:
        issues.append(f"Success rate {success_rate*100:.1f}% < 95%")
    if throughput < 42:
        issues.append(f"Throughput {throughput:.0f}/hr < 42/hr target")
    if result.search_times_after and result.search_times_before:
        if statistics.mean(result.search_times_after) > statistics.mean(result.search_times_before) * 2:
            issues.append("Search time degraded > 2x after uploads")

    print("\n" + ("RESULT: FAIL - " + "; ".join(issues) if issues else "RESULT: PASS"))
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Study upload throughput test")
    parser.add_argument("--studies", type=int, default=50, help="Number of studies to upload")
    parser.add_argument("--concurrent", type=int, default=5, help="Concurrent uploads")
    args = parser.parse_args()

    asyncio.run(run_test(args.studies, args.concurrent))


if __name__ == "__main__":
    main()
