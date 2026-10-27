"""IHE XDS ebRIM metadata generation (xds-i-export feature).

Builds a minimal-conformant METADATA.XML (ebRIM 3.0 RegistryObjectList) for an
XDM package: one SubmissionSet, one DocumentEntry per study's KOS manifest, and
HasMember associations. Structural minimal conformance — NOT IHE Gazelle
certified. Uses stdlib ElementTree (no extra deps).
"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

RIM_NS = "urn:oasis:names:tc:ebxml-regrep:xsd:rim:3.0"

# IHE XDS classification scheme UUIDs (fixed)
SCHEME = {
    "ss_classCode": "urn:uuid:aa543740-bdda-424e-8c96-df4873be8500",
    "doc_classCode": "urn:uuid:41a5887f-8865-4c09-adf7-e362475b143a",
    "doc_confidentialityCode": "urn:uuid:f4f85eac-e6cb-4883-b524-f2705394840f",
    "doc_formatCode": "urn:uuid:a09d5840-386c-46f2-b5ad-9c3699a4309d",
    "doc_facilityCode": "urn:uuid:f33fb8ac-18af-42cc-ae0e-ed0b0bdb91e1",
    "doc_practiceCode": "urn:uuid:cccf5598-8b07-4b77-a05e-ae952c785ead",
    "doc_typeCode": "urn:uuid:f0306f51-975f-434e-a61c-c59651d33983",
    "ss_uniqueId": "urn:uuid:96fdda7c-d067-4183-912e-bf5ee74998a8",
    "ss_sourceId": "urn:uuid:554ac39e-e3fe-47fe-b233-965d2a147832",
    "ss_patientId": "urn:uuid:6b5aea1a-874d-4603-a4bc-96a0a7b38446",
    "doc_uniqueId": "urn:uuid:2e82c1f6-a085-4c72-9da3-8640a32e42ab",
    "doc_patientId": "urn:uuid:58a6f841-87b3-4a3e-92fd-a8ffeff98427",
}
ASSOC_HASMEMBER = "urn:oasis:names:tc:ebxml-regrep:AssociationType:HasMember"

# Default coded attributes (general values; overridable). format = code^display^scheme
DEFAULT_CODES = {
    "classCode": ("IMAGES", "Images", "1.3.6.1.4.1.21367.100.1"),
    "typeCode": ("18748-4", "Diagnostic imaging study", "LOINC"),
    "confidentialityCode": ("N", "Normal", "2.16.840.1.113883.5.25"),
    # KOS SOP Class — the XDS-I manifest format
    "formatCode": ("1.2.840.10008.5.1.4.1.1.88.59", "Key Object Selection Document", "1.2.840.10008.2.6.1"),
    "facilityCode": ("GENERAL", "General Hospital", "2.16.840.1.113883.5.11"),
    "practiceSettingCode": ("RADDX", "Radiology", "1.3.6.1.4.1.21367.100.1"),
}


@dataclass
class DocEntry:
    doc_id: str            # symbolic id, e.g. "Document01"
    file_ref: str          # path inside package, e.g. "DOC00001.dcm"
    unique_id: str         # KOS SOP Instance UID
    creation_time: str     # YYYYMMDDHHMMSS
    title: str = "Imaging Study Manifest (KOS)"


@dataclass
class Submission:
    submission_time: str
    patient_id: str        # affinity-domain patient id (sending domain ok)
    source_id: str
    unique_id: str
    codes: dict = field(default_factory=lambda: dict(DEFAULT_CODES))


def _slot(parent, name, *values):
    s = ET.SubElement(parent, f"{{{RIM_NS}}}Slot", {"name": name})
    vl = ET.SubElement(s, f"{{{RIM_NS}}}ValueList")
    for v in values:
        ET.SubElement(vl, f"{{{RIM_NS}}}Value").text = v
    return s


def _classification(parent, scheme, classified_obj, node_repr, code_triplet):
    code, display, scheme_name = code_triplet
    c = ET.SubElement(parent, f"{{{RIM_NS}}}Classification", {
        "classificationScheme": scheme,
        "classifiedObject": classified_obj,
        "nodeRepresentation": node_repr if node_repr else code,
    })
    name = ET.SubElement(c, f"{{{RIM_NS}}}Name")
    ET.SubElement(name, f"{{{RIM_NS}}}LocalizedString", {"value": display})
    _slot(c, "codingScheme", scheme_name)
    return c


def _external_id(parent, scheme, registry_obj, value, display):
    e = ET.SubElement(parent, f"{{{RIM_NS}}}ExternalIdentifier", {
        "identificationScheme": scheme,
        "registryObject": registry_obj,
        "value": value,
    })
    name = ET.SubElement(e, f"{{{RIM_NS}}}Name")
    ET.SubElement(name, f"{{{RIM_NS}}}LocalizedString", {"value": display})
    return e


def build_metadata_xml(sub: Submission, docs: list[DocEntry]) -> bytes:
    """Return METADATA.XML bytes for the XDM submission."""
    ET.register_namespace("rim", RIM_NS)
    root = ET.Element(f"{{{RIM_NS}}}RegistryObjectList")

    # ── DocumentEntries ──
    for d in docs:
        eo = ET.SubElement(root, f"{{{RIM_NS}}}ExtrinsicObject", {
            "id": d.doc_id,
            "mimeType": "application/dicom",
            "objectType": "urn:uuid:7edca82f-054d-47f2-a032-9b2a5b5186c1",  # StableDocumentEntry
        })
        name = ET.SubElement(eo, f"{{{RIM_NS}}}Name")
        ET.SubElement(name, f"{{{RIM_NS}}}LocalizedString", {"value": d.title})
        _slot(eo, "creationTime", d.creation_time)
        _slot(eo, "languageCode", "ko-KR")
        _slot(eo, "sourcePatientId", sub.patient_id)
        _classification(eo, SCHEME["doc_classCode"], d.doc_id, sub.codes["classCode"][0], sub.codes["classCode"])
        _classification(eo, SCHEME["doc_confidentialityCode"], d.doc_id, sub.codes["confidentialityCode"][0], sub.codes["confidentialityCode"])
        _classification(eo, SCHEME["doc_formatCode"], d.doc_id, sub.codes["formatCode"][0], sub.codes["formatCode"])
        _classification(eo, SCHEME["doc_facilityCode"], d.doc_id, sub.codes["facilityCode"][0], sub.codes["facilityCode"])
        _classification(eo, SCHEME["doc_practiceCode"], d.doc_id, sub.codes["practiceSettingCode"][0], sub.codes["practiceSettingCode"])
        _classification(eo, SCHEME["doc_typeCode"], d.doc_id, sub.codes["typeCode"][0], sub.codes["typeCode"])
        _external_id(eo, SCHEME["doc_patientId"], d.doc_id, sub.patient_id, "XDSDocumentEntry.patientId")
        _external_id(eo, SCHEME["doc_uniqueId"], d.doc_id, d.unique_id, "XDSDocumentEntry.uniqueId")

    # ── SubmissionSet ──
    ss = ET.SubElement(root, f"{{{RIM_NS}}}RegistryPackage", {"id": "SubmissionSet01"})
    _slot(ss, "submissionTime", sub.submission_time)
    ss_name = ET.SubElement(ss, f"{{{RIM_NS}}}Name")
    ET.SubElement(ss_name, f"{{{RIM_NS}}}LocalizedString", {"value": "OpenPACS Imaging SubmissionSet"})
    _classification(ss, SCHEME["ss_classCode"], "SubmissionSet01", "submissionset",
                    ("submissionset", "Submission Set", "1.3.6.1.4.1.21367.100.1"))
    _external_id(ss, SCHEME["ss_uniqueId"], "SubmissionSet01", sub.unique_id, "XDSSubmissionSet.uniqueId")
    _external_id(ss, SCHEME["ss_sourceId"], "SubmissionSet01", sub.source_id, "XDSSubmissionSet.sourceId")
    _external_id(ss, SCHEME["ss_patientId"], "SubmissionSet01", sub.patient_id, "XDSSubmissionSet.patientId")
    # Classify the SubmissionSet registry package as a SubmissionSet
    ET.SubElement(root, f"{{{RIM_NS}}}Classification", {
        "classificationNode": "urn:uuid:a54d6aa5-d40d-43f9-88c5-b4633d873bdd",
        "classifiedObject": "SubmissionSet01",
        "id": "cl-ss01",
    })

    # ── Associations: SubmissionSet HasMember each Document ──
    for i, d in enumerate(docs, 1):
        assoc = ET.SubElement(root, f"{{{RIM_NS}}}Association", {
            "associationType": ASSOC_HASMEMBER,
            "sourceObject": "SubmissionSet01",
            "targetObject": d.doc_id,
            "id": f"as-{i:02d}",
        })
        _slot(assoc, "SubmissionSetStatus", "Original")

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
