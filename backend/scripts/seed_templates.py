import asyncio, json, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

DB = os.environ.get("DATABASE_URL", "postgresql+asyncpg://openpacs:OpenPACS2026!@127.0.0.1:5432/openpacs")

TEMPLATES = [
    # CT
    ("흉부 CT (Chest CT)", "CT", "CHEST", "흉부 CT 기본 판독", True,
     [{"name":"폐","key":"lung","type":"textarea","default":"양측 폐야 이상 음영 없음"},{"name":"종격동","key":"mediastinum","type":"textarea","default":"종격동 림프절 비대 없음"},{"name":"심장","key":"heart","type":"textarea","default":"심비대 없음"},{"name":"대혈관","key":"vessel","type":"textarea","default":"대동맥 정상"},{"name":"흉벽","key":"wall","type":"textarea","default":"흉벽 이상 없음"}],
     "양측 폐야에 활동성 병변 없음.\n종격동 림프절 비대 없음.\n심비대 없음.\n흉막 삼출 없음.", "특이 소견 없음.",
     {"nf":"No active lesion","pe":"Pleural effusion","ggo":"Ground glass opacity","nd":"Nodule"}),
    ("복부골반 CT (Abdomen-Pelvis CT)", "CT", "ABDOMEN", "복부골반 CT 판독", False,
     [{"name":"간","key":"liver","type":"textarea","default":"간 종괴 없음"},{"name":"담낭/담도","key":"gb","type":"textarea","default":"담석 없음"},{"name":"췌장","key":"pancreas","type":"textarea","default":"정상"},{"name":"비장","key":"spleen","type":"textarea","default":"비종대 없음"},{"name":"신장","key":"kidney","type":"textarea","default":"정상"},{"name":"림프절","key":"ln","type":"textarea","default":"비대 없음"},{"name":"골반","key":"pelvis","type":"textarea","default":"이상 없음"}],
     "간, 담낭, 췌장, 비장, 양측 신장 이상 없음.\n복강 내 림프절 비대 없음.\n복수 없음.", "복부골반 CT 특이 소견 없음.",
     {"hm":"Hepatic mass","gs":"Gallstone","hn":"Hydronephrosis"}),
    ("두부 CT (Brain NCCT)", "CT", "HEAD", "두부 비조영 CT", False,
     [{"name":"뇌실질","key":"brain","type":"textarea","default":"이상 음영 없음"},{"name":"뇌실","key":"ventricle","type":"textarea","default":"크기 정상"},{"name":"두개골","key":"skull","type":"textarea","default":"골절 없음"}],
     "뇌실질 출혈/경색/종괴 없음.\n뇌실 정상.\nMidline shift 없음.", "두부 CT 특이 소견 없음.",
     {"ich":"ICH","sah":"SAH","ms":"Midline shift"}),
    ("경추 CT (C-Spine CT)", "CT", "C-SPINE", "경추 CT 판독", False,
     [{"name":"경추체","key":"body","type":"textarea","default":"정렬 정상"},{"name":"디스크","key":"disc","type":"textarea","default":"돌출 없음"},{"name":"척추관","key":"canal","type":"textarea","default":"협착 없음"}],
     "경추 정렬 정상.\n추간판 돌출/척추관 협착 없음.\n골절 없음.", "경추 CT 특이 소견 없음.", None),
    ("부비동 CT (PNS CT)", "CT", "PNS", "부비동 CT", False,
     [{"name":"부비동","key":"sinus","type":"textarea","default":"함기화 정상"},{"name":"비중격","key":"septum","type":"textarea","default":"편위 없음"}],
     "양측 부비동 함기화 정상.\n비중격 편위 없음.\n점막 비후 없음.", "부비동 CT 특이 소견 없음.", None),
    # MR
    ("뇌 MRI (Brain MRI)", "MR", "HEAD", "뇌 MRI 판독", True,
     [{"name":"뇌실질","key":"brain","type":"textarea","default":"신호 이상 없음"},{"name":"뇌실","key":"ventricle","type":"textarea","default":"크기 정상"},{"name":"뇌혈관","key":"vessel","type":"textarea","default":"이상 없음"}],
     "T1, T2, FLAIR 뇌실질 이상 신호 없음.\n뇌실 정상, midline shift 없음.\nDiffusion restriction 없음.", "뇌 MRI 특이 소견 없음.",
     {"wml":"White matter lesion","lac":"Lacunar infarction","atr":"Atrophy"}),
    ("요추 MRI (L-Spine MRI)", "MR", "L-SPINE", "요추 MRI 판독", False,
     [{"name":"L3-L4","key":"l34","type":"textarea","default":"정상"},{"name":"L4-L5","key":"l45","type":"textarea","default":"정상"},{"name":"L5-S1","key":"l5s1","type":"textarea","default":"정상"},{"name":"척추관","key":"canal","type":"textarea","default":"협착 없음"}],
     "요추 정렬 정상.\nL3-L4~L5-S1 추간판 변성/돌출 없음.\n척추관/신경공 협착 없음.", "요추 MRI 특이 소견 없음.",
     {"hivd":"HIVD","ss":"Spinal stenosis","nf":"NF compromise"}),
    ("간 MRI (Liver MRI-EOB)", "MR", "LIVER", "간 MRI (EOB) 판독", False,
     [{"name":"간실질","key":"liver","type":"textarea","default":"이상 신호 없음"},{"name":"동맥기","key":"arterial","type":"textarea","default":"조영증강 병변 없음"},{"name":"간담도기","key":"hbp","type":"textarea","default":"결손 없음"}],
     "간 실질 이상 신호 없음.\n동맥기 조기 조영증강 없음.\n간담도기 결손 없음.", "간 MRI 특이 소견 없음. LI-RADS N/A.",
     {"hcc":"HCC","lr3":"LI-RADS 3","lr5":"LI-RADS 5"}),
    ("견관절 MRI (Shoulder MRI)", "MR", "SHOULDER", "견관절 MRI", False,
     [{"name":"회전근개","key":"rc","type":"textarea","default":"정상"},{"name":"관절순","key":"labrum","type":"textarea","default":"정상"},{"name":"관절낭","key":"capsule","type":"textarea","default":"이상 없음"}],
     "극상근/극하근/견갑하근건 정상.\n관절순 파열 없음.\n관절 삼출 없음.", "견관절 MRI 특이 소견 없음.", None),
    ("골반 MRI (Pelvis MRI)", "MR", "PELVIS", "골반 MRI 판독", False,
     [{"name":"장기","key":"organ","type":"textarea","default":"정상"},{"name":"림프절","key":"ln","type":"textarea","default":"비대 없음"}],
     "자궁(전립선) 크기/신호 정상.\n부속기(정낭) 이상 없음.\n골반 림프절 비대 없음.", "골반 MRI 특이 소견 없음.", None),
    # CR/DX
    ("흉부 PA (Chest X-ray)", "CR", "CHEST", "흉부 단순촬영 판독", True,
     [{"name":"폐야","key":"lung","type":"textarea","default":"이상 없음"},{"name":"심장","key":"heart","type":"textarea","default":"심비대 없음"},{"name":"종격동","key":"mediastinum","type":"textarea","default":"이상 없음"}],
     "양측 폐야 활동성 병변 없음.\n심장 크기 정상 (CTR<50%).\nCP angle 예각.\n종격동 이상 없음.", "흉부 X-ray 특이 소견 없음.",
     {"ctr":"CTR","cpa":"CPA blunting","pe":"Pleural effusion","pnx":"Pneumothorax"}),
    ("복부 X-ray (Abdomen)", "CR", "ABDOMEN", "복부 단순촬영", False,
     [{"name":"장가스","key":"gas","type":"textarea","default":"분포 정상"},{"name":"석회화","key":"calc","type":"textarea","default":"없음"}],
     "장가스 분포 정상.\nAir-fluid level 없음.\nFree air 없음.", "복부 X-ray 특이 소견 없음.", None),
    ("무릎 X-ray (Knee)", "CR", "KNEE", "무릎 단순촬영", False,
     [{"name":"관절","key":"joint","type":"textarea","default":"간격 정상"},{"name":"골","key":"bone","type":"textarea","default":"골절 없음"}],
     "슬관절 간격 정상.\n골절/탈구 없음.\n퇴행성 변화 없음.", "무릎 X-ray 특이 소견 없음.", None),
    ("손 X-ray (Hand)", "DX", "HAND", "수부 단순촬영", False,
     [{"name":"골","key":"bone","type":"textarea","default":"골절 없음"},{"name":"관절","key":"joint","type":"textarea","default":"정상"}],
     "수부/수근부 골절 없음.\n관절 간격 정상.", "수부 X-ray 특이 소견 없음.", None),
    ("발 X-ray (Foot)", "DX", "FOOT", "족부 단순촬영", False,
     [{"name":"골","key":"bone","type":"textarea","default":"골절 없음"},{"name":"관절","key":"joint","type":"textarea","default":"정상"}],
     "족부 골절 없음.\n관절 정상.", "족부 X-ray 특이 소견 없음.", None),
    # US
    ("복부 초음파 (Abd US)", "US", "ABDOMEN", "복부 초음파 판독", True,
     [{"name":"간","key":"liver","type":"textarea","default":"에코 균질"},{"name":"담낭","key":"gb","type":"textarea","default":"담석 없음"},{"name":"CBD","key":"cbd","type":"textarea","default":"확장 없음"},{"name":"췌장","key":"pancreas","type":"textarea","default":"정상"},{"name":"비장","key":"spleen","type":"textarea","default":"비종대 없음"},{"name":"신장","key":"kidney","type":"textarea","default":"정상, 수신증 없음"}],
     "간 에코 균질, 종괴 없음.\n담석 없음, 총담관 정상.\n췌장/비장/신장 이상 없음.\n복수 없음.", "복부 초음파 특이 소견 없음.",
     {"fl":"Fatty liver","gs":"Gallstone","hn":"Hydronephrosis"}),
    ("갑상선 초음파 (Thyroid US)", "US", "THYROID", "갑상선 초음파 판독", False,
     [{"name":"우엽","key":"right","type":"textarea","default":"결절 없음"},{"name":"좌엽","key":"left","type":"textarea","default":"결절 없음"},{"name":"림프절","key":"ln","type":"textarea","default":"비대 없음"}],
     "갑상선 양엽 크기 정상.\n에코 균질, 결절 없음.\n경부 림프절 비대 없음.", "갑상선 초음파 정상. K-TIRADS 2.",
     {"kt3":"K-TIRADS 3","kt4":"K-TIRADS 4","kt5":"K-TIRADS 5","fna":"FNA 권장"}),
    ("유방 초음파 (Breast US)", "US", "BREAST", "유방 초음파 (BI-RADS)", False,
     [{"name":"우측","key":"right","type":"textarea","default":"이상 없음"},{"name":"좌측","key":"left","type":"textarea","default":"이상 없음"},{"name":"액와","key":"axilla","type":"textarea","default":"림프절 비대 없음"}],
     "양측 유방 종괴 없음.\n액와 림프절 비대 없음.", "양측 유방 초음파 정상. BI-RADS 1.",
     {"br2":"BI-RADS 2","br3":"BI-RADS 3","br4":"BI-RADS 4"}),
    ("경동맥 초음파 (Carotid US)", "US", "CAROTID", "경동맥 초음파", False,
     [{"name":"우측","key":"right","type":"textarea","default":"정상"},{"name":"좌측","key":"left","type":"textarea","default":"정상"},{"name":"IMT","key":"imt","type":"textarea","default":"<1.0mm"}],
     "양측 경동맥 혈류 정상.\nIMT 정상.\n유의한 협착/폐쇄 없음.", "경동맥 초음파 특이 소견 없음.", None),
    ("심장 초음파 (Echo)", "US", "HEART", "심장 초음파 판독", False,
     [{"name":"좌심실","key":"lv","type":"textarea","default":"기능 정상 (EF 60%)"},{"name":"판막","key":"valve","type":"textarea","default":"이상 없음"},{"name":"심낭","key":"pericardium","type":"textarea","default":"삼출 없음"}],
     "좌심실 크기/벽운동 정상. EF 60%.\n각 판막 역류/협착 없음.\n심낭 삼출 없음.", "심장 초음파 정상. 좌심실 기능 정상.",
     {"ef":"EF","mr":"MR","ar":"AR","tr":"TR"}),
]

async def seed():
    engine = create_async_engine(DB)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        # Delete old and re-insert all
        await db.execute(text("DELETE FROM report_templates"))
        for t in TEMPLATES:
            name, mod, bp, desc, default, sections, normal, impression, macros = t
            await db.execute(text("""
                INSERT INTO report_templates (name, modality, body_part, description, is_default, sections, normal_template, impression_template, macros)
                VALUES (:name, :mod, :bp, :desc, :default, CAST(:sec AS jsonb), :normal, :imp, CAST(:mac AS jsonb))
            """), {
                "name": name, "mod": mod, "bp": bp, "desc": desc, "default": default,
                "sec": json.dumps(sections, ensure_ascii=False),
                "normal": normal, "imp": impression,
                "mac": json.dumps(macros, ensure_ascii=False) if macros else None,
            })
            print(f"  + {mod} {name}")
        await db.commit()
        result = await db.execute(text("SELECT count(*) FROM report_templates"))
        print(f"\nTotal: {result.scalar()} templates")
    await engine.dispose()

asyncio.run(seed())
