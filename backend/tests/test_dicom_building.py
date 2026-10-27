"""Tests for standards-compliant DICOM AI result building (SR + SEG).

Validates the highdicom-based builders in app.services.dicom_ai_standard:
- SR is a Comprehensive SR following TID 1500 with an evidence sequence
- SEG is a valid Segmentation linked to its source image

These tests assert real DICOM standard properties (SOP Class, TID, modality,
evidence linkage) — unlike the previous stub tests, which passed against a
hand-rolled, non-conformant dataset.
"""
import io

import numpy as np
import pytest
from pydicom import dcmread
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from app.services.dicom_ai_standard import build_ai_sr, build_ai_seg

CT_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.2"
COMPREHENSIVE_SR_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.88.33"
SEG_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.66.4"


def _make_source(rows=64, cols=64) -> bytes:
    """Build a minimal but valid CT source instance as DICOM bytes."""
    fm = Dataset()
    sop = generate_uid()
    fm.MediaStorageSOPClassUID = CT_SOP_CLASS
    fm.MediaStorageSOPInstanceUID = sop
    fm.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset("src.dcm", {}, file_meta=fm, preamble=b"\0" * 128)
    ds.PatientName = "Hong^Gildong"
    ds.PatientID = "P001"
    ds.PatientBirthDate = "19800101"
    ds.PatientSex = "M"
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = sop
    ds.SOPClassUID = CT_SOP_CLASS
    ds.Modality = "CT"
    ds.Rows = rows
    ds.Columns = cols
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.ImagePositionPatient = [0, 0, 0]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.PixelSpacing = [1, 1]
    ds.SliceThickness = 1.0
    ds.FrameOfReferenceUID = generate_uid()
    ds.SeriesNumber = 1
    ds.InstanceNumber = 1
    ds.PixelData = np.zeros((rows, cols), np.uint16).tobytes()
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    buf = io.BytesIO()
    ds.save_as(buf)
    return buf.getvalue()


@pytest.fixture
def source_bytes():
    return _make_source()


@pytest.fixture
def findings():
    return [
        {"description": "Possible nodule right upper lobe", "confidence": 0.91, "severity": "warning"},
        {"description": "No acute abnormality", "confidence": 0.97, "severity": "normal"},
    ]


class TestStandardSR:
    def test_sr_is_comprehensive_sr(self, source_bytes, findings):
        sr = dcmread(io.BytesIO(build_ai_sr([source_bytes], "chest-xray-ai", "1.0.0", findings)))
        assert sr.Modality == "SR"
        assert sr.SOPClassUID == COMPREHENSIVE_SR_SOP_CLASS

    def test_sr_follows_tid1500(self, source_bytes, findings):
        sr = dcmread(io.BytesIO(build_ai_sr([source_bytes], "m", "1.0", findings)))
        assert sr.ContentTemplateSequence[0].TemplateIdentifier == "1500"

    def test_sr_has_evidence_sequence(self, source_bytes, findings):
        """Standard requires linkage back to the analyzed images."""
        sr = dcmread(io.BytesIO(build_ai_sr([source_bytes], "m", "1.0", findings)))
        assert "CurrentRequestedProcedureEvidenceSequence" in sr

    def test_sr_copies_patient_identity_from_evidence(self, source_bytes, findings):
        src = dcmread(io.BytesIO(source_bytes))
        sr = dcmread(io.BytesIO(build_ai_sr([source_bytes], "m", "1.0", findings)))
        assert str(sr.PatientName) == str(src.PatientName)
        assert sr.PatientID == src.PatientID
        assert sr.StudyInstanceUID == src.StudyInstanceUID

    def test_sr_requires_source(self, findings):
        with pytest.raises(ValueError):
            build_ai_sr([], "m", "1.0", findings)

    def test_sr_handles_empty_findings(self, source_bytes):
        sr = dcmread(io.BytesIO(build_ai_sr([source_bytes], "m", "1.0", [])))
        assert sr.Modality == "SR"

    def test_sr_accepts_dataset_input(self, source_bytes, findings):
        src_ds = dcmread(io.BytesIO(source_bytes))
        sr = dcmread(io.BytesIO(build_ai_sr([src_ds], "m", "1.0", findings)))
        assert sr.SOPClassUID == COMPREHENSIVE_SR_SOP_CLASS


class TestStandardSEG:
    def test_seg_is_segmentation(self, source_bytes):
        mask = np.zeros((64, 64), np.uint8)
        mask[20:40, 25:45] = 1
        seg = dcmread(io.BytesIO(build_ai_seg([source_bytes], mask, "ai", "1.0", segment_label="Nodule")))
        assert seg.Modality == "SEG"
        assert seg.SOPClassUID == SEG_SOP_CLASS
        assert seg.SegmentationType == "BINARY"

    def test_seg_links_source_series(self, source_bytes):
        mask = np.zeros((64, 64), np.uint8)
        mask[10:20, 10:20] = 1
        seg = dcmread(io.BytesIO(build_ai_seg([source_bytes], mask, "ai", "1.0")))
        assert "ReferencedSeriesSequence" in seg

    def test_seg_has_segment_descriptor(self, source_bytes):
        mask = np.zeros((64, 64), np.uint8)
        mask[5:15, 5:15] = 1
        seg = dcmread(io.BytesIO(build_ai_seg([source_bytes], mask, "ai", "1.0", segment_label="Lesion")))
        assert len(seg.SegmentSequence) == 1
        assert seg.SegmentSequence[0].SegmentLabel == "Lesion"

    def test_seg_requires_source(self):
        with pytest.raises(ValueError):
            build_ai_seg([], np.zeros((8, 8), np.uint8), "ai", "1.0")
