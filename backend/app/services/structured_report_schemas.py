"""Structured Report Schema Definitions.

Predefined schemas for standardized radiology reporting:
BI-RADS, K-TIRADS, LI-RADS with auto-category calculation.
"""

SCHEMAS = {
    "bi-rads": {
        "name": "BI-RADS (유방 영상 보고 데이터 시스템)",
        "modalities": ["MG", "US"],
        "body_part": "BREAST",
        "version": "5th Edition",
        "fields": [
            {"key": "side", "label": "측", "type": "select", "options": ["우측", "좌측", "양측"], "required": True},
            {"key": "mass_present", "label": "종괴 유무", "type": "select", "options": ["없음", "있음"]},
            {"key": "mass_shape", "label": "종괴 모양", "type": "select", "options": ["round", "oval", "irregular"],
             "depends_on": {"mass_present": "있음"}},
            {"key": "mass_margin", "label": "종괴 경계", "type": "select",
             "options": ["circumscribed", "obscured", "microlobulated", "indistinct", "spiculated"],
             "depends_on": {"mass_present": "있음"}},
            {"key": "mass_size_mm", "label": "종괴 크기 (mm)", "type": "number",
             "depends_on": {"mass_present": "있음"}},
            {"key": "calcification", "label": "석회화", "type": "select",
             "options": ["없음", "전형적 양성", "의심스러운 형태", "높은 의심"]},
            {"key": "architectural_distortion", "label": "구조 왜곡", "type": "select", "options": ["없음", "있음"]},
            {"key": "skin_change", "label": "피부 변화", "type": "select", "options": ["없음", "비후", "함몰"]},
            {"key": "axillary_ln", "label": "액와 림프절", "type": "select", "options": ["정상", "비대"]},
            {"key": "category", "label": "BI-RADS 카테고리", "type": "auto"},
            {"key": "recommendation", "label": "권고", "type": "auto"},
        ],
        "category_logic": """
            0: 불완전 평가 (추가 영상 필요)
            1: 음성 (정상)
            2: 양성 소견 (전형적 양성 석회화, 단순 낭종 등)
            3: 양성 추정 (6개월 단기 추적)
            4a: 낮은 의심 (생검 권고)
            4b: 중등도 의심
            4c: 높은 의심
            5: 높은 악성 의심 (생검 필수)
            6: 조직검사 확인된 악성
        """,
    },

    "k-tirads": {
        "name": "K-TIRADS (한국 갑상선 영상 보고 데이터 시스템)",
        "modalities": ["US"],
        "body_part": "THYROID",
        "version": "2021 개정판",
        "fields": [
            {"key": "side", "label": "측", "type": "select", "options": ["우엽", "좌엽", "협부"], "required": True},
            {"key": "nodule_size_mm", "label": "결절 크기 (mm)", "type": "number", "required": True},
            {"key": "composition", "label": "구성", "type": "select",
             "options": ["solid", "predominantly solid", "predominantly cystic", "cystic", "spongiform"]},
            {"key": "echogenicity", "label": "에코", "type": "select",
             "options": ["hyperechoic", "isoechoic", "hypoechoic", "markedly hypoechoic"]},
            {"key": "shape", "label": "모양", "type": "select",
             "options": ["wider-than-tall", "taller-than-wide"]},
            {"key": "margin", "label": "경계", "type": "select",
             "options": ["smooth", "ill-defined", "lobulated", "irregular", "extrathyroidal extension"]},
            {"key": "calcification", "label": "석회화", "type": "select",
             "options": ["없음", "eggshell", "coarse", "microcalcification"]},
            {"key": "cervical_ln", "label": "경부 림프절", "type": "select", "options": ["정상", "의심"]},
            {"key": "category", "label": "K-TIRADS", "type": "auto"},
            {"key": "fna_recommendation", "label": "FNA 권고", "type": "auto"},
        ],
        "category_logic": """
            1: 정상 (결절 없음)
            2: 양성 (단순 낭종, spongiform)
            3: 낮은 의심 (isoechoic/hyperechoic solid, wider-than-tall, smooth)
            4: 중등도 의심 (hypoechoic solid, 또는 1개 이상 의심 소견)
            5: 높은 의심 (2개 이상: hypoechoic + microcalcification + taller-than-wide + irregular margin)
            FNA 권고: K-TIRADS 3: ≥15mm, K-TIRADS 4: ≥10mm, K-TIRADS 5: ≥5mm
        """,
    },

    "li-rads": {
        "name": "LI-RADS (간 영상 보고 데이터 시스템)",
        "modalities": ["CT", "MR"],
        "body_part": "LIVER",
        "version": "v2018",
        "fields": [
            {"key": "observation_size_mm", "label": "병변 크기 (mm)", "type": "number", "required": True},
            {"key": "arterial_hyperenhancement", "label": "동맥기 과조영증강", "type": "select",
             "options": ["없음", "있음"], "required": True},
            {"key": "nonperipheral_washout", "label": "비변연부 씻김", "type": "select",
             "options": ["없음", "있음"]},
            {"key": "enhancing_capsule", "label": "조영증강 캡슐", "type": "select",
             "options": ["없음", "있음"]},
            {"key": "threshold_growth", "label": "크기 증가 (≥50% in ≤6mo)", "type": "select",
             "options": ["없음", "있음"]},
            {"key": "t2_hyperintensity", "label": "T2 고신호 (MR)", "type": "select",
             "options": ["해당없음", "경도", "현저"]},
            {"key": "hepatobiliary_hypointensity", "label": "간담도기 저신호 (MR-EOB)", "type": "select",
             "options": ["해당없음", "없음", "있음"]},
            {"key": "restricted_diffusion", "label": "확산제한", "type": "select",
             "options": ["해당없음", "없음", "있음"]},
            {"key": "category", "label": "LI-RADS", "type": "auto"},
            {"key": "management", "label": "관리 권고", "type": "auto"},
        ],
        "category_logic": """
            LR-1: 확실한 양성
            LR-2: 양성 추정
            LR-3: 중등도 HCC 확률 (동맥기 과조영+, major feature 0개)
            LR-4: HCC 가능성 높음 (동맥기 과조영+, major 1개, <20mm)
            LR-5: 확실한 HCC (동맥기 과조영+, major ≥1개, ≥20mm 또는 major ≥2개)
            LR-M: 악성, HCC 아닐 수 있음 (rim enhancement, 현저한 T2)
            LR-TIV: 종양혈전
            Major features: nonperipheral washout, enhancing capsule, threshold growth
        """,
    },
    "lung-rads": {
        "name": "Lung-RADS (폐 CT 선별검사 보고 시스템)",
        "modalities": ["CT"],
        "body_part": "CHEST",
        "version": "v1.1",
        "fields": [
            {"key": "nodule_type", "label": "결절 유형", "type": "select",
             "options": ["solid", "part-solid", "ground-glass"], "required": True},
            {"key": "nodule_size_mm", "label": "결절 크기 (mm)", "type": "number", "required": True},
            {"key": "solid_component_mm", "label": "고형 성분 크기 (mm)", "type": "number",
             "depends_on": {"nodule_type": "part-solid"}},
            {"key": "growth", "label": "성장 여부", "type": "select", "options": ["없음", "신규", "증가"]},
            {"key": "spiculation", "label": "침상 변연", "type": "select", "options": ["없음", "있음"]},
            {"key": "upper_lobe", "label": "상엽 위치", "type": "select", "options": ["아니오", "예"]},
            {"key": "additional_features", "label": "부가 소견", "type": "text"},
            {"key": "category", "label": "Lung-RADS 카테고리", "type": "auto"},
            {"key": "recommendation", "label": "권고", "type": "auto"},
        ],
        "category_logic": """
            1: 음성 — 결절 없음 또는 확실한 양성 결절
            2: 양성 추정 — solid <6mm, GGN <30mm, part-solid <6mm
            3: 양성 추정 낮은 의심 — solid 6-8mm, part-solid ≥6mm solid<6mm, GGN ≥30mm
            4A: 의심 — solid 8-15mm, part-solid solid≥6mm, 새로운 GGN
            4B: 매우 의심 — solid ≥15mm 또는 성장 확인
            S: 기타 임상적 유의 소견
        """,
    },

    "pi-rads": {
        "name": "PI-RADS (전립선 MRI 보고 데이터 시스템)",
        "modalities": ["MR"],
        "body_part": "PROSTATE",
        "version": "v2.1",
        "fields": [
            {"key": "zone", "label": "구역", "type": "select",
             "options": ["peripheral", "transition", "central"], "required": True},
            {"key": "t2_signal", "label": "T2WI 신호", "type": "select",
             "options": ["homogeneous_high", "heterogeneous", "focal_low", "markedly_low"], "required": True},
            {"key": "dwi_score", "label": "DWI 점수", "type": "select",
             "options": ["1", "2", "3", "4", "5"], "required": True},
            {"key": "dce", "label": "DCE 양성", "type": "select", "options": ["음성", "양성"]},
            {"key": "lesion_size_mm", "label": "병변 크기 (mm)", "type": "number"},
            {"key": "epe", "label": "전립선외 침범", "type": "select", "options": ["없음", "의심"]},
            {"key": "category", "label": "PI-RADS 카테고리", "type": "auto"},
            {"key": "recommendation", "label": "권고", "type": "auto"},
        ],
        "category_logic": """
            1: 임상적 유의한 암 가능성 매우 낮음
            2: 낮음
            3: 중등도 (모호)
            4: 높음
            5: 매우 높음
            PZ: DWI dominant, TZ: T2WI dominant
            DWI 3 + DCE(+) → PI-RADS 4 (PZ)
        """,
    },

    "o-rads": {
        "name": "O-RADS (난소 영상 보고 데이터 시스템)",
        "modalities": ["US", "MR"],
        "body_part": "OVARY",
        "version": "v2022",
        "fields": [
            {"key": "composition", "label": "구성", "type": "select",
             "options": ["simple_cyst", "hemorrhagic", "dermoid", "endometrioma",
                         "unilocular", "multilocular", "solid_smooth", "solid_irregular"],
             "required": True},
            {"key": "size_mm", "label": "크기 (mm)", "type": "number", "required": True},
            {"key": "wall_regularity", "label": "벽 규칙성", "type": "select",
             "options": ["smooth", "papillary_projection", "irregular"]},
            {"key": "septation", "label": "격벽", "type": "select",
             "options": ["없음", "thin(<3mm)", "thick(≥3mm)"]},
            {"key": "doppler", "label": "도플러 혈류", "type": "select",
             "options": ["없음", "mild", "moderate", "marked"]},
            {"key": "ascites", "label": "복수", "type": "select", "options": ["없음", "있음"]},
            {"key": "category", "label": "O-RADS 카테고리", "type": "auto"},
            {"key": "recommendation", "label": "권고", "type": "auto"},
        ],
        "category_logic": """
            0: 평가 불완전
            1: 정상 난소
            2: 거의 확실한 양성 (<1% 악성) — 단순 낭종, 출혈성 낭종 등
            3: 낮은 악성 위험 (1-10%) — 유두상 돌기 없는 다방성 낭종
            4: 중등도 악성 위험 (10-50%) — 고형 성분+혈류, 유두상 돌기
            5: 높은 악성 위험 (>50%) — 불규칙 고형, 복수 동반
        """,
    },

    "c-rads": {
        "name": "C-RADS (대장 CT 보고 데이터 시스템)",
        "modalities": ["CT"],
        "body_part": "COLON",
        "version": "v2005",
        "fields": [
            {"key": "largest_polyp_mm", "label": "최대 용종 크기 (mm)", "type": "number", "required": True},
            {"key": "polyp_count", "label": "용종 수", "type": "number", "required": True},
            {"key": "morphology", "label": "형태", "type": "select",
             "options": ["sessile", "pedunculated", "flat"]},
            {"key": "colon_mass", "label": "대장 종괴", "type": "select", "options": ["없음", "있음"]},
            {"key": "extracolonic_finding", "label": "대장외 소견", "type": "select",
             "options": ["없음", "E1_무의미", "E2_임상관련_양성", "E3_중요_추가검사", "E4_악성의심"]},
            {"key": "study_quality", "label": "검사 품질", "type": "select",
             "options": ["adequate", "inadequate"]},
            {"key": "category", "label": "C-RADS 카테고리", "type": "auto"},
            {"key": "recommendation", "label": "권고", "type": "auto"},
        ],
        "category_logic": """
            C0: 부적절 검사 — 재검 필요
            C1: 정상 또는 6mm 미만 용종 — 10년 후 추적 또는 5년
            C2: 중간 용종 6-9mm — 대장내시경 또는 3년 후 CT
            C3: 10mm 이상 용종 또는 3개 이상 6-9mm — 대장내시경 권고
            C4: 대장 종괴 의심 — 대장내시경 필수
        """,
    },

    "bosniak": {
        "name": "Bosniak (신장 낭성 병변 분류)",
        "modalities": ["CT", "MR"],
        "body_part": "KIDNEY",
        "version": "v2019",
        "fields": [
            {"key": "septation", "label": "격벽", "type": "select",
             "options": ["없음", "thin_few", "thin_many", "thick_enhancing"], "required": True},
            {"key": "wall", "label": "벽", "type": "select",
             "options": ["thin_smooth", "thick_or_irregular"], "required": True},
            {"key": "enhancement", "label": "조영증강", "type": "select",
             "options": ["없음", "격벽/벽_조영증강", "고형성분_조영증강"], "required": True},
            {"key": "calcification", "label": "석회화", "type": "select",
             "options": ["없음", "fine", "coarse"]},
            {"key": "size_mm", "label": "크기 (mm)", "type": "number"},
            {"key": "homogeneous_high_attenuation", "label": "균일 고밀도 (CT)", "type": "select",
             "options": ["아니오", "예"]},
            {"key": "category", "label": "Bosniak 카테고리", "type": "auto"},
            {"key": "recommendation", "label": "권고", "type": "auto"},
        ],
        "category_logic": """
            I: 단순 낭종 — 추적 불필요
            II: 미세 합병 낭종 (얇은 격벽, 미세 석회화, 고밀도 낭종 ≤3cm) — 추적 불필요
            IIF: 추적 필요 낭종 (다수 얇은 격벽, 최소 조영, 고밀도 >3cm) — 추적 관찰
            III: 불확실 (두꺼운 격벽/벽 조영증강) — 수술 또는 적극 감시
            IV: 명백한 악성 (고형 조영증강 성분) — 수술 권고
        """,
    },

    "spine-degeneration": {
        "name": "척추 퇴행성 변화 평가 (요추 MR)",
        "modalities": ["MR"],
        "body_part": "LSPINE",
        "version": "v1.0",
        "fields": [
            {"key": "level", "label": "디스크 레벨", "type": "select",
             "options": ["L3-L4", "L4-L5", "L5-S1"], "required": True},
            {"key": "pfirrmann_grade", "label": "Pfirrmann 등급", "type": "select",
             "options": ["I", "II", "III", "IV", "V"], "required": True},
            {"key": "herniation_type", "label": "추간판 탈출 유형", "type": "select",
             "options": ["없음", "bulging", "protrusion", "extrusion", "sequestration"]},
            {"key": "nerve_compression", "label": "신경근 압박", "type": "select",
             "options": ["없음", "contact", "displacement", "compression"]},
            {"key": "central_stenosis", "label": "중심관 협착", "type": "select",
             "options": ["없음", "mild", "moderate", "severe"]},
            {"key": "foraminal_stenosis", "label": "추간공 협착", "type": "select",
             "options": ["없음", "mild", "moderate", "severe"]},
            {"key": "endplate_change", "label": "종판 변화 (Modic)", "type": "select",
             "options": ["없음", "Type_I", "Type_II", "Type_III"]},
            {"key": "category", "label": "종합 등급", "type": "auto"},
            {"key": "recommendation", "label": "권고", "type": "auto"},
        ],
        "category_logic": """
            mild: Pfirrmann I-II, 탈출 없음/bulging, 협착 없음~mild
            moderate: Pfirrmann III-IV, protrusion, 협착 moderate, 신경 contact/displacement
            severe: Pfirrmann V, extrusion/sequestration, 협착 severe, 신경 compression
        """,
    },

    "bone-density": {
        "name": "골밀도 검사 (DXA)",
        "modalities": ["DX"],
        "body_part": "BONE",
        "version": "WHO/ISCD",
        "fields": [
            {"key": "site", "label": "측정 부위", "type": "select",
             "options": ["lumbar_spine", "femoral_neck", "total_hip"], "required": True},
            {"key": "t_score", "label": "T-score", "type": "number", "required": True},
            {"key": "z_score", "label": "Z-score", "type": "number"},
            {"key": "bmd_value", "label": "BMD (g/cm²)", "type": "number"},
            {"key": "prior_fracture", "label": "기왕 골절", "type": "select", "options": ["없음", "있음"]},
            {"key": "fracture_risk", "label": "FRAX 10년 주요 골절 위험도 (%)", "type": "number"},
            {"key": "category", "label": "진단", "type": "auto"},
            {"key": "recommendation", "label": "권고", "type": "auto"},
        ],
        "category_logic": """
            normal: T-score ≥ -1.0 — 정상
            osteopenia: -2.5 < T-score < -1.0 — 골감소증
            osteoporosis: T-score ≤ -2.5 — 골다공증
            severe_osteoporosis: T-score ≤ -2.5 + 기왕 골절 — 심한 골다공증
        """,
    },
}


def get_schema(schema_type: str) -> dict | None:
    """Get a structured report schema by type."""
    return SCHEMAS.get(schema_type)


def list_schemas() -> list[dict]:
    """List all available schemas with summary info."""
    return [
        {
            "type": key,
            "name": schema["name"],
            "modalities": schema["modalities"],
            "body_part": schema["body_part"],
            "version": schema["version"],
            "field_count": len(schema["fields"]),
        }
        for key, schema in SCHEMAS.items()
    ]


def calculate_category(schema_type: str, data: dict) -> dict:
    """Calculate category based on structured data fields.

    Returns {"category": "...", "recommendation": "..."}.
    """
    dispatch = {
        "bi-rads": _calculate_birads,
        "k-tirads": _calculate_ktirads,
        "li-rads": _calculate_lirads,
        "lung-rads": _calculate_lungrads,
        "pi-rads": _calculate_pirads,
        "o-rads": _calculate_orads,
        "c-rads": _calculate_crads,
        "bosniak": _calculate_bosniak,
        "spine-degeneration": _calculate_spine,
        "bone-density": _calculate_bmd,
    }
    fn = dispatch.get(schema_type)
    if fn:
        return fn(data)
    return {"category": "N/A", "recommendation": "스키마 없음"}


def _calculate_birads(data: dict) -> dict:
    mass = data.get("mass_present") == "있음"
    margin = data.get("mass_margin", "")
    calcification = data.get("calcification", "없음")
    distortion = data.get("architectural_distortion") == "있음"

    if not mass and calcification == "없음" and not distortion:
        return {"category": "1", "recommendation": "정기 검진"}
    if not mass and calcification == "전형적 양성":
        return {"category": "2", "recommendation": "정기 검진"}
    if mass and margin in ("circumscribed", "obscured") and calcification in ("없음", "전형적 양성"):
        return {"category": "3", "recommendation": "6개월 단기 추적"}
    if mass and margin == "spiculated":
        return {"category": "5", "recommendation": "조직 검사 필수"}
    if calcification == "높은 의심":
        return {"category": "4c", "recommendation": "조직 검사 권고"}
    if calcification == "의심스러운 형태" or distortion:
        return {"category": "4a", "recommendation": "조직 검사 고려"}
    if mass:
        return {"category": "4b", "recommendation": "조직 검사 권고"}
    return {"category": "0", "recommendation": "추가 영상 검사"}


def _calculate_ktirads(data: dict) -> dict:
    size = data.get("nodule_size_mm", 0)
    echo = data.get("echogenicity", "")
    shape = data.get("shape", "")
    margin = data.get("margin", "")
    calc = data.get("calcification", "없음")
    composition = data.get("composition", "")

    if composition in ("cystic", "spongiform"):
        return {"category": "2", "fna_recommendation": "FNA 불필요"}

    suspicious_count = 0
    if echo in ("hypoechoic", "markedly hypoechoic"):
        suspicious_count += 1
    if shape == "taller-than-wide":
        suspicious_count += 1
    if margin in ("irregular", "extrathyroidal extension"):
        suspicious_count += 1
    if calc == "microcalcification":
        suspicious_count += 1

    if suspicious_count >= 2:
        fna = "FNA 권고" if size >= 5 else "추적 관찰"
        return {"category": "5", "fna_recommendation": fna}
    if suspicious_count >= 1:
        fna = "FNA 권고" if size >= 10 else "추적 관찰"
        return {"category": "4", "fna_recommendation": fna}
    fna = "FNA 고려" if size >= 15 else "추적 관찰"
    return {"category": "3", "fna_recommendation": fna}


def _calculate_lirads(data: dict) -> dict:
    size = data.get("observation_size_mm", 0)
    aphe = data.get("arterial_hyperenhancement") == "있음"
    washout = data.get("nonperipheral_washout") == "있음"
    capsule = data.get("enhancing_capsule") == "있음"
    growth = data.get("threshold_growth") == "있음"
    t2 = data.get("t2_hyperintensity", "")

    if not aphe:
        if washout or capsule or growth:
            return {"category": "LR-M", "management": "다학제 논의"}
        return {"category": "LR-3", "management": "3~6개월 추적"}

    major_count = sum([washout, capsule, growth])

    if t2 == "현저":
        return {"category": "LR-M", "management": "다학제 논의, HCC 외 악성 감별"}

    if major_count == 0:
        return {"category": "LR-3", "management": "3~6개월 추적"}
    if major_count == 1 and size < 20:
        return {"category": "LR-4", "management": "다학제 논의 또는 추적"}
    if major_count >= 2 or (major_count >= 1 and size >= 20):
        return {"category": "LR-5", "management": "HCC 확진, 치료 계획"}

    return {"category": "LR-3", "management": "추적"}


def _calculate_lungrads(data: dict) -> dict:
    """Lung-RADS v1.1 카테고리 자동 계산."""
    ntype = data.get("nodule_type", "solid")
    size = data.get("nodule_size_mm", 0)
    solid_comp = data.get("solid_component_mm", 0)
    growth = data.get("growth", "없음")

    if growth == "증가":
        return {"category": "4B", "recommendation": "흉부 CT 3개월 추적 또는 PET/CT, 조직검사 고려"}
    if ntype == "solid":
        if size < 6:
            return {"category": "2", "recommendation": "12개월 저선량 CT"}
        if size <= 8:
            return {"category": "3", "recommendation": "6개월 저선량 CT"}
        if size <= 15:
            return {"category": "4A", "recommendation": "3개월 CT 추적, PET/CT 고려"}
        return {"category": "4B", "recommendation": "흉부 CT 또는 PET/CT, 조직검사 권고"}
    if ntype == "part-solid":
        if size < 6:
            return {"category": "2", "recommendation": "12개월 저선량 CT"}
        if solid_comp < 6:
            return {"category": "3", "recommendation": "6개월 저선량 CT"}
        return {"category": "4A", "recommendation": "3개월 CT 추적, PET/CT 고려"}
    # ground-glass
    if size < 30:
        return {"category": "2", "recommendation": "12개월 저선량 CT"}
    return {"category": "3", "recommendation": "6개월 저선량 CT"}


def _calculate_pirads(data: dict) -> dict:
    """PI-RADS v2.1 카테고리 자동 계산."""
    zone = data.get("zone", "peripheral")
    dwi = int(data.get("dwi_score", "1"))
    t2 = data.get("t2_signal", "")
    dce = data.get("dce") == "양성"
    size = data.get("lesion_size_mm", 0)

    if zone == "peripheral":
        score = dwi
        if score == 3 and dce:
            score = 4
    else:  # transition / central zone — T2 dominant
        t2_map = {"homogeneous_high": 1, "heterogeneous": 2, "focal_low": 3, "markedly_low": 5}
        score = t2_map.get(t2, 3)
        if score == 3 and dwi >= 4:
            score = 4

    if score >= 4 and size >= 15:
        score = 5
    rec_map = {1: "추가 검사 불필요", 2: "추적 불필요", 3: "MRI 추적 고려",
               4: "표적 생검 권고", 5: "표적 생검 강력 권고"}
    return {"category": str(score), "recommendation": rec_map.get(score, "임상 판단")}


def _calculate_orads(data: dict) -> dict:
    """O-RADS 카테고리 자동 계산."""
    comp = data.get("composition", "")
    wall = data.get("wall_regularity", "smooth")
    doppler = data.get("doppler", "없음")
    ascites = data.get("ascites") == "있음"
    septation = data.get("septation", "없음")

    if comp == "simple_cyst":
        return {"category": "2", "recommendation": "양성, 추적 불필요 (≤5cm 시)"}
    if comp in ("hemorrhagic", "dermoid", "endometrioma"):
        return {"category": "2", "recommendation": "전형적 양성 소견, 추적 관찰"}
    if wall == "irregular" or ascites:
        return {"category": "5", "recommendation": "높은 악성 위험, 부인종양 전문의 의뢰"}
    if comp == "solid_irregular" or doppler == "marked":
        return {"category": "5", "recommendation": "높은 악성 위험, 수술 고려"}
    if comp == "solid_smooth" or septation == "thick(≥3mm)":
        rec = "중등도 악성 위험, 추가 검사 또는 수술 고려"
        return {"category": "4", "recommendation": rec}
    if comp == "multilocular" or doppler in ("mild", "moderate"):
        return {"category": "3", "recommendation": "낮은 악성 위험, MRI 또는 추적"}
    return {"category": "2", "recommendation": "양성 추정, 추적 관찰"}


def _calculate_crads(data: dict) -> dict:
    """C-RADS 카테고리 자동 계산."""
    quality = data.get("study_quality", "adequate")
    polyp_size = data.get("largest_polyp_mm", 0)
    polyp_count = data.get("polyp_count", 0)
    mass = data.get("colon_mass") == "있음"

    if quality == "inadequate":
        return {"category": "C0", "recommendation": "검사 부적절, 재검 필요"}
    if mass:
        return {"category": "C4", "recommendation": "대장 종괴 의심, 대장내시경 필수"}
    if polyp_size >= 10 or (polyp_count >= 3 and polyp_size >= 6):
        return {"category": "C3", "recommendation": "대장내시경 권고"}
    if 6 <= polyp_size < 10:
        return {"category": "C2", "recommendation": "대장내시경 또는 3년 후 CT 추적"}
    return {"category": "C1", "recommendation": "정상 또는 임상 무의미 소견, 정기 검진"}


def _calculate_bosniak(data: dict) -> dict:
    """Bosniak 2019 카테고리 자동 계산."""
    septation = data.get("septation", "없음")
    wall = data.get("wall", "thin_smooth")
    enhancement = data.get("enhancement", "없음")
    high_attn = data.get("homogeneous_high_attenuation") == "예"
    size = data.get("size_mm", 0)

    if enhancement == "고형성분_조영증강":
        return {"category": "IV", "recommendation": "악성 가능성 높음, 수술 권고"}
    if wall == "thick_or_irregular" or septation == "thick_enhancing":
        return {"category": "III", "recommendation": "불확실 병변, 수술 또는 적극 감시"}
    if septation == "thin_many" or enhancement == "격벽/벽_조영증강":
        return {"category": "IIF", "recommendation": "추적 관찰 (6개월~1년 CT/MR)"}
    if septation == "thin_few" or high_attn:
        if high_attn and size > 30:
            return {"category": "IIF", "recommendation": "고밀도 낭종 >3cm, 추적 관찰"}
        return {"category": "II", "recommendation": "양성, 추적 불필요"}
    return {"category": "I", "recommendation": "단순 낭종, 추적 불필요"}


def _calculate_spine(data: dict) -> dict:
    """척추 퇴행성 변화 종합 등급 계산."""
    pfirrmann = data.get("pfirrmann_grade", "I")
    herniation = data.get("herniation_type", "없음")
    central = data.get("central_stenosis", "없음")
    nerve = data.get("nerve_compression", "없음")

    severe_criteria = (pfirrmann == "V" or herniation in ("extrusion", "sequestration")
                       or central == "severe" or nerve == "compression")
    if severe_criteria:
        return {"category": "severe", "recommendation": "통증 조절 불가 시 수술 고려, 신경외과 협진"}

    moderate_criteria = (pfirrmann in ("III", "IV") or herniation == "protrusion"
                         or central == "moderate" or nerve in ("contact", "displacement"))
    if moderate_criteria:
        return {"category": "moderate", "recommendation": "보존적 치료, 증상 지속 시 추적 MRI"}

    return {"category": "mild", "recommendation": "경미한 퇴행 변화, 보존적 치료 및 경과 관찰"}


def _calculate_bmd(data: dict) -> dict:
    """골밀도(DXA) T-score 기반 진단 카테고리 계산."""
    t_score = data.get("t_score", 0)
    fracture = data.get("prior_fracture") == "있음"
    frax = data.get("fracture_risk", 0)

    if t_score <= -2.5 and fracture:
        return {"category": "severe_osteoporosis",
                "recommendation": "심한 골다공증, 약물 치료 필수 및 골절 예방 관리"}
    if t_score <= -2.5:
        return {"category": "osteoporosis",
                "recommendation": "골다공증, 약물 치료 권고 및 생활 습관 개선"}
    if t_score < -1.0:
        rec = "골감소증, 생활 습관 개선"
        if frax and frax >= 20:
            rec += ", FRAX 고위험 — 약물 치료 고려"
        return {"category": "osteopenia", "recommendation": rec}
    return {"category": "normal", "recommendation": "정상 골밀도, 정기 검진 권고"}
