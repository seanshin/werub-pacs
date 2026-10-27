"""디지털 병리 WSI 벌크 주석 생성 (DICOM Sup 222 — Microscopy Bulk Simple Annotations).

WSI(VL Whole Slide Microscopy, SM) 스터디에 대한 주석(폴리곤/포인트 등)을 표준 DICOM ANN
객체(SOPClass 1.2.840.10008.5.1.4.1.1.91.1)로 생성한다. WeRU.B 뷰어의
DicomMicroscopyANN 핸들러가 그대로 표시한다(생성 측 신설, v13.19 후속 G1).

계산병리 AI 출력(슬라이드당 대량 주석)·병리의 수기 마킹을 표준 형식으로 저장·교환하기 위함.
"""
from __future__ import annotations

import numpy as np
import highdicom as hd
import highdicom.ann as hdann
from pydicom.dataset import Dataset
from pydicom.sr.coding import Code

# 기본 주석 속성 코드(SNOMED CT) — 호출자가 재정의 가능
_DEFAULT_CATEGORY = Code("91723000", "SCT", "Anatomical Structure")
_DEFAULT_TYPE = Code("85756007", "SCT", "Tissue")

_GRAPHIC = {g.name: g for g in hdann.GraphicTypeValues}          # POLYGON/POINT/POLYLINE/ELLIPSE/RECTANGLE
_ALGO = {a.name: a for a in hdann.AnnotationGroupGenerationTypeValues}  # MANUAL/AUTOMATIC/SEMIAUTOMATIC


_COORD = {
    "2D": hdann.AnnotationCoordinateTypeValues.SCOORD,     # total pixel matrix 픽셀좌표 (col,row)
    "3D": hdann.AnnotationCoordinateTypeValues.SCOORD3D,   # 슬라이드 3D 좌표 (x,y,z mm, FoR 기준)
}


def _to_code(d: dict) -> Code:
    """{value,scheme,meaning} dict → pydicom Code. 키 이름이 달라(scheme vs
    scheme_designator) Code(**d)는 TypeError — 명시 번역만 허용."""
    scheme = d.get("scheme") or d.get("scheme_designator")
    if not (d.get("value") and scheme and d.get("meaning")):
        raise ValueError(f"category/type 코드는 {{value,scheme,meaning}} 필요: {d!r}")
    return Code(str(d["value"]), str(scheme), str(d["meaning"]))


def _clean_polygon(coords: "np.ndarray", graphic_type) -> "np.ndarray":
    """POLYGON은 닫힘점(첫==끝)이 있으면 highdicom가 거부 → 방어적으로 제거.

    뷰어에서 드로잉된 폴리곤은 닫힘점을 포함하는 경우가 많다(SCOORD/SCOORD3D 공통).
    """
    if graphic_type.name != "POLYGON" or len(coords) < 2:
        return coords
    if np.allclose(coords[0], coords[-1]):
        return coords[:-1]
    return coords


def build_bulk_annotations(
    source_image: Dataset,
    groups: list[dict],
    *,
    coordinate_type: str = "2D",
    content_description: str | None = "WeRU.B pathology annotations",
    content_creator_name: str | None = None,
) -> Dataset:
    """WSI SM 인스턴스와 주석 그룹으로 Microscopy Bulk Simple Annotations 객체를 만든다.

    groups[i] = {
      "label": str,
      "graphic_type": "POLYGON"|"POINT"|"POLYLINE"|"ELLIPSE"|"RECTANGLE",
      "coordinates": [[[x,y(,z)],...], ...]   # 주석마다 좌표 배열의 리스트
      "algorithm_type": "MANUAL"|"AUTOMATIC"|"SEMIAUTOMATIC"  (기본 MANUAL)
      "category"/"type": {"value","scheme","meaning"} (선택, 기본 조직)
    }
    coordinate_type: "2D"(픽셀 col,row) | "3D"(슬라이드 x,y,z mm — 뷰어 드로잉 ROI의 네이티브).
      3D는 source WSI의 FrameOfReferenceUID를 요구(highdicom가 복사).
    """
    if source_image.get("Modality") != "SM":
        raise ValueError(f"source_image는 SM(WSI)이어야 함(실제 {source_image.get('Modality')})")
    if not groups:
        raise ValueError("주석 그룹이 비어있음")
    coord_val = _COORD.get(str(coordinate_type).upper())
    if coord_val is None:
        raise ValueError(f"coordinate_type 미지원: {coordinate_type} (2D|3D)")
    if coord_val is hdann.AnnotationCoordinateTypeValues.SCOORD3D and not source_image.get("FrameOfReferenceUID"):
        raise ValueError("3D 좌표는 source WSI에 FrameOfReferenceUID가 필요함")

    # highdicom는 소스에서 환자/검사 속성을 복사하며 일부는 존재를 요구 — 비표준 WSI 대비 방어.
    for tag in ("PatientBirthDate", "PatientSex", "PatientID", "PatientName",
                "StudyID", "AccessionNumber", "StudyDate", "StudyTime"):
        if tag not in source_image:
            setattr(source_image, tag, "")

    ann_groups: list[hdann.AnnotationGroup] = []
    for i, g in enumerate(groups, start=1):
        gt = _GRAPHIC.get(str(g.get("graphic_type", "POLYGON")).upper())
        if gt is None:
            raise ValueError(f"graphic_type 미지원: {g.get('graphic_type')}")
        algo = _ALGO.get(str(g.get("algorithm_type", "MANUAL")).upper(), _ALGO["MANUAL"])
        graphic_data = []
        for c in g["coordinates"]:
            arr = np.asarray(c, dtype=np.float32)
            if arr.size == 0 or not np.isfinite(arr).all():
                raise ValueError(f"그룹 '{g.get('label')}' 좌표에 빈 배열 또는 NaN/Inf 포함")
            graphic_data.append(_clean_polygon(arr, gt))
        if not graphic_data:
            raise ValueError(f"그룹 '{g.get('label')}' 좌표 없음")
        cat = g.get("category")
        typ = g.get("type")
        ann_groups.append(hdann.AnnotationGroup(
            number=i,
            uid=hd.UID(),
            label=str(g.get("label", f"group-{i}")),
            annotated_property_category=_to_code(cat) if cat else _DEFAULT_CATEGORY,
            annotated_property_type=_to_code(typ) if typ else _DEFAULT_TYPE,
            graphic_type=gt,
            graphic_data=graphic_data,
            algorithm_type=algo,
        ))

    return hdann.MicroscopyBulkSimpleAnnotations(
        source_images=[source_image],
        annotation_coordinate_type=coord_val,
        annotation_groups=ann_groups,
        series_instance_uid=hd.UID(),
        series_number=201,
        sop_instance_uid=hd.UID(),
        instance_number=1,
        manufacturer="OpenPACS",
        manufacturer_model_name="WeRU.B PACS",
        software_versions="v13.19",
        device_serial_number="OPENPACS",
        content_description=content_description,
        content_creator_name=content_creator_name,
    )
