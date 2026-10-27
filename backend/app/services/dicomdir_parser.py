"""DICOMDIR parser for CD/DVD import.

Parses DICOMDIR file to extract patient/study/series/instance hierarchy
from medical imaging CDs.
"""
import io
import logging
from pathlib import Path
from typing import Optional

import pydicom

logger = logging.getLogger(__name__)


class DicomdirParser:
    """Parse DICOMDIR file from CD/DVD media."""

    def parse(self, dicomdir_bytes: bytes) -> dict:
        """Parse DICOMDIR and return structured patient/study tree.

        Returns:
            {
                "patients": [
                    {
                        "patient_id": "...",
                        "patient_name": "...",
                        "studies": [
                            {
                                "study_instance_uid": "...",
                                "study_date": "...",
                                "study_description": "...",
                                "modalities": ["CT", "MR"],
                                "series": [
                                    {
                                        "series_instance_uid": "...",
                                        "modality": "CT",
                                        "series_description": "...",
                                        "instance_count": 120,
                                        "file_paths": ["DICOM/CT001/IMG001", ...]
                                    }
                                ]
                            }
                        ]
                    }
                ],
                "total_instances": 450,
                "total_studies": 3,
                "total_patients": 1
            }
        """
        try:
            ds = pydicom.dcmread(io.BytesIO(dicomdir_bytes), force=True)
        except Exception as e:
            logger.error(f"Failed to parse DICOMDIR: {e}")
            return {"patients": [], "total_instances": 0, "total_studies": 0, "total_patients": 0, "error": str(e)}

        if not hasattr(ds, "DirectoryRecordSequence"):
            return {"patients": [], "total_instances": 0, "total_studies": 0, "total_patients": 0, "error": "No DirectoryRecordSequence found"}

        patients = []
        current_patient = None
        current_study = None
        current_series = None
        total_instances = 0

        for record in ds.DirectoryRecordSequence:
            record_type = getattr(record, "DirectoryRecordType", "").strip()

            if record_type == "PATIENT":
                current_patient = {
                    "patient_id": getattr(record, "PatientID", ""),
                    "patient_name": str(getattr(record, "PatientName", "")),
                    "patient_birth_date": getattr(record, "PatientBirthDate", ""),
                    "patient_sex": getattr(record, "PatientSex", ""),
                    "studies": [],
                }
                patients.append(current_patient)

            elif record_type == "STUDY" and current_patient:
                current_study = {
                    "study_instance_uid": getattr(record, "StudyInstanceUID", ""),
                    "study_date": getattr(record, "StudyDate", ""),
                    "study_time": getattr(record, "StudyTime", ""),
                    "study_description": getattr(record, "StudyDescription", ""),
                    "accession_number": getattr(record, "AccessionNumber", ""),
                    "modalities": set(),
                    "series": [],
                }
                current_patient["studies"].append(current_study)

            elif record_type == "SERIES" and current_study:
                modality = getattr(record, "Modality", "OT")
                current_series = {
                    "series_instance_uid": getattr(record, "SeriesInstanceUID", ""),
                    "series_number": getattr(record, "SeriesNumber", ""),
                    "modality": modality,
                    "series_description": getattr(record, "SeriesDescription", ""),
                    "instance_count": 0,
                    "file_paths": [],
                }
                current_study["series"].append(current_series)
                current_study["modalities"].add(modality)

            elif record_type == "IMAGE" and current_series:
                file_id = getattr(record, "ReferencedFileID", None)
                if file_id:
                    if isinstance(file_id, pydicom.multival.MultiValue):
                        file_path = "/".join(str(p) for p in file_id)
                    else:
                        file_path = str(file_id)
                    current_series["file_paths"].append(file_path)
                current_series["instance_count"] += 1
                total_instances += 1

        # Convert sets to lists for JSON serialization
        for patient in patients:
            for study in patient["studies"]:
                study["modalities"] = sorted(study["modalities"])

        return {
            "patients": patients,
            "total_instances": total_instances,
            "total_studies": sum(len(p["studies"]) for p in patients),
            "total_patients": len(patients),
        }

    def find_dicomdir(self, file_list: list[str]) -> Optional[str]:
        """Find DICOMDIR file in a list of filenames."""
        for f in file_list:
            name = Path(f).name.upper()
            if name == "DICOMDIR":
                return f
        return None
