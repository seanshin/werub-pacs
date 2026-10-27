"""
Seed script for OpenPACS test data.

Seeds:
1. Additional test users (technologist, researcher)
2. Normalization config for all modalities
3. Supplier-specific normalization rules
4. Sample batch jobs with file records
5. Inference results for completed jobs

Usage:
  python scripts/seed_test_data.py

Requires DATABASE_URL environment variable.
"""
import asyncio
import os
import sys
import json
from datetime import datetime, timezone, timedelta
from uuid import uuid4

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://openpacs:OpenPACS2026!@127.0.0.1:5432/openpacs")
os.environ.setdefault("ORTHANC_PASSWORD", "CHANGE_ME")
os.environ.setdefault("SECRET_KEY", "openpacs-secret-key-change-in-production")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


async def seed():
    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        now = datetime.now(timezone.utc)

        # =====================================================================
        # 1. Additional test users
        # =====================================================================
        existing_users = await db.execute(text("SELECT username FROM users"))
        user_names = {r[0] for r in existing_users}

        new_users = [
            ("tech.park", "TECHNOLOGIST", "Park Technologist"),
            ("researcher.lee", "RESEARCHER", "Lee Researcher"),
        ]

        for username, role, full_name in new_users:
            if username not in user_names:
                # bcrypt hash for "Test1234!"
                pw_hash = "$2b$12$LJ3m4ys8Kqx.vZJ0j0eOGeOmKz7OZhRkYPGqNlFQ7a7aI5.5.P6u"
                await db.execute(text("""
                    INSERT INTO users (id, username, email, hashed_password, role, full_name, is_active, created_at, updated_at)
                    VALUES (:id, :username, :email, :pw, :role, :name, true, :now, :now)
                """), {
                    "id": str(uuid4()), "username": username,
                    "email": f"{username}@openpacs.local",
                    "pw": pw_hash,
                    "role": role, "name": full_name, "now": now,
                })
                print(f"  + User: {username} ({role})")

        # =====================================================================
        # 2. Normalization config (modality-specific)
        # =====================================================================
        existing_configs = await db.execute(text("SELECT modality FROM normalization_config"))
        config_modalities = {r[0] for r in existing_configs}

        modality_configs = [
            {
                "modality": "CT",
                "algorithms": {"pixel_spacing": True, "missing_tags": True, "photometric": False, "charset": True},
                "risk_tiers": {"safe": "auto", "medium": "manual", "risky": "reject"},
            },
            {
                "modality": "CR",
                "algorithms": {"pixel_spacing": True, "missing_tags": True, "photometric": True, "charset": True},
                "risk_tiers": {"safe": "auto", "medium": "auto", "risky": "manual"},
            },
            {
                "modality": "DX",
                "algorithms": {"pixel_spacing": True, "missing_tags": True, "photometric": True, "charset": True},
                "risk_tiers": {"safe": "auto", "medium": "auto", "risky": "manual"},
            },
            {
                "modality": "MR",
                "algorithms": {"pixel_spacing": True, "missing_tags": True, "photometric": False, "charset": True},
                "risk_tiers": {"safe": "auto", "medium": "manual", "risky": "reject"},
            },
            {
                "modality": "US",
                "algorithms": {"pixel_spacing": False, "missing_tags": True, "photometric": False, "charset": True},
                "risk_tiers": {"safe": "auto", "medium": "auto", "risky": "manual"},
            },
            {
                "modality": "MG",
                "algorithms": {"pixel_spacing": True, "missing_tags": True, "photometric": True, "charset": True},
                "risk_tiers": {"safe": "auto", "medium": "manual", "risky": "reject"},
            },
        ]

        for cfg in modality_configs:
            if cfg["modality"] not in config_modalities:
                await db.execute(text("""
                    INSERT INTO normalization_config (id, modality, algorithms, risk_tiers, updated_by, created_at, updated_at)
                    VALUES (:id, :mod, CAST(:alg AS jsonb), CAST(:risk AS jsonb), 'admin', :now, :now)
                """), {
                    "id": str(uuid4()), "mod": cfg["modality"],
                    "alg": json.dumps(cfg["algorithms"]),
                    "risk": json.dumps(cfg["risk_tiers"]),
                    "now": now,
                })
                print(f"  + NormConfig: {cfg['modality']}")

        # =====================================================================
        # 3. Supplier normalization rules
        # =====================================================================
        existing_rules = await db.execute(text("SELECT supplier_name FROM supplier_rules"))
        rule_suppliers = {r[0] for r in existing_rules}

        supplier_rules = [
            {
                "supplier_name": "siemens",
                "rule_version": "1.0",
                "rule_config": {
                    "manufacturer_patterns": ["SIEMENS", "Siemens Healthineers"],
                    "charset_fix": "ISO_IR 192",
                    "pixel_spacing_override": False,
                    "private_tag_cleanup": ["(0009,xxxx)", "(0019,xxxx)", "(0029,xxxx)"],
                    "known_issues": ["JPEG density mismatch in older CT scanners"],
                },
                "description": "Siemens DICOM normalization: charset fix, private tag cleanup",
            },
            {
                "supplier_name": "ge",
                "rule_version": "1.0",
                "rule_config": {
                    "manufacturer_patterns": ["GE MEDICAL", "GE Healthcare"],
                    "charset_fix": "ISO_IR 100",
                    "pixel_spacing_override": False,
                    "private_tag_cleanup": ["(0009,xxxx)", "(0043,xxxx)", "(0045,xxxx)"],
                    "known_issues": ["Missing PatientBirthDate in some CR systems"],
                },
                "description": "GE Healthcare DICOM normalization: charset, missing tag defaults",
            },
            {
                "supplier_name": "philips",
                "rule_version": "1.0",
                "rule_config": {
                    "manufacturer_patterns": ["Philips", "PHILIPS"],
                    "charset_fix": "ISO_IR 192",
                    "pixel_spacing_override": False,
                    "private_tag_cleanup": ["(2001,xxxx)", "(2005,xxxx)"],
                    "known_issues": ["Photometric interpretation issues in some MR"],
                },
                "description": "Philips DICOM normalization: photometric fix, private tag cleanup",
            },
            {
                "supplier_name": "fuji",
                "rule_version": "1.0",
                "rule_config": {
                    "manufacturer_patterns": ["FUJIFILM", "FUJI PHOTO"],
                    "charset_fix": "ISO_IR 149",
                    "pixel_spacing_override": True,
                    "private_tag_cleanup": [],
                    "known_issues": ["JPEG density always 72 DPI regardless of actual spacing"],
                },
                "description": "Fujifilm CR: critical JPEG density correction required",
            },
            {
                "supplier_name": "carestream",
                "rule_version": "1.0",
                "rule_config": {
                    "manufacturer_patterns": ["Carestream", "CARESTREAM"],
                    "charset_fix": "ISO_IR 100",
                    "pixel_spacing_override": True,
                    "private_tag_cleanup": [],
                    "known_issues": ["JPEG density set to 96 DPI (Windows default)"],
                },
                "description": "Carestream CR/DR: JPEG density correction for Windows-based systems",
            },
        ]

        for rule in supplier_rules:
            if rule["supplier_name"] not in rule_suppliers:
                await db.execute(text("""
                    INSERT INTO supplier_rules (id, supplier_name, rule_version, is_active, rule_config, managed_by, description, created_at, updated_at)
                    VALUES (:id, :name, :ver, true, CAST(:config AS jsonb), 'admin', :desc, :now, :now)
                """), {
                    "id": str(uuid4()), "name": rule["supplier_name"],
                    "ver": rule["rule_version"],
                    "config": json.dumps(rule["rule_config"]),
                    "desc": rule["description"], "now": now,
                })
                print(f"  + SupplierRule: {rule['supplier_name']}")

        # =====================================================================
        # 4. Sample batch jobs with file records
        # =====================================================================
        existing_batches = await db.execute(text("SELECT count(*) FROM batch_jobs"))
        batch_count = existing_batches.scalar()

        if batch_count == 0:
            # Get admin user id
            admin_result = await db.execute(text("SELECT id FROM users WHERE username = 'admin'"))
            admin_row = admin_result.fetchone()
            admin_id = admin_row[0] if admin_row else str(uuid4())

            # Get tech user id
            tech_result = await db.execute(text("SELECT id FROM users WHERE role = 'TECHNOLOGIST'"))
            tech_row = tech_result.fetchone()
            tech_id = tech_row[0] if tech_row else admin_id

            sample_batches = [
                {
                    "user_id": str(admin_id),
                    "status": "completed",
                    "total_files": 15, "processed_files": 15,
                    "succeeded_files": 13, "failed_files": 2,
                    "supplier": "siemens",
                    "started_at": now - timedelta(hours=3),
                    "completed_at": now - timedelta(hours=2, minutes=45),
                    "error_summary": {"failed_files": ["corrupted_header.dcm", "missing_pixel_data.dcm"]},
                    "files": [
                        {"filename": f"CT_CHEST_{i:03d}.dcm", "status": "completed" if i < 14 else "failed",
                         "modality": "CT", "patient_id": "PAT001", "detected_supplier": "siemens",
                         "study_instance_uid": "1.2.840.113619.2.416.10688137.1234567890.001"}
                        for i in range(1, 16)
                    ],
                },
                {
                    "user_id": str(tech_id),
                    "status": "completed",
                    "total_files": 5, "processed_files": 5,
                    "succeeded_files": 5, "failed_files": 0,
                    "supplier": "ge",
                    "started_at": now - timedelta(hours=1),
                    "completed_at": now - timedelta(minutes=50),
                    "error_summary": None,
                    "files": [
                        {"filename": f"CR_CHEST_{i:03d}.dcm", "status": "completed",
                         "modality": "CR", "patient_id": "PAT002", "detected_supplier": "ge",
                         "study_instance_uid": "1.2.840.113619.2.416.10688137.9876543210.002"}
                        for i in range(1, 6)
                    ],
                },
                {
                    "user_id": str(admin_id),
                    "status": "processing",
                    "total_files": 30, "processed_files": 18,
                    "succeeded_files": 16, "failed_files": 2,
                    "supplier": "auto_detect",
                    "started_at": now - timedelta(minutes=10),
                    "completed_at": None,
                    "error_summary": None,
                    "files": [
                        {"filename": f"MR_BRAIN_{i:03d}.dcm", "status": "completed" if i <= 18 else "pending",
                         "modality": "MR", "patient_id": "PAT003", "detected_supplier": "philips",
                         "study_instance_uid": "1.2.840.113619.2.416.10688137.5555555555.003"}
                        for i in range(1, 31)
                    ],
                },
                {
                    "user_id": str(tech_id),
                    "status": "queued",
                    "total_files": 8, "processed_files": 0,
                    "succeeded_files": 0, "failed_files": 0,
                    "supplier": "fuji",
                    "started_at": None, "completed_at": None,
                    "error_summary": None,
                    "files": [
                        {"filename": f"DX_SPINE_{i:03d}.dcm", "status": "pending",
                         "modality": "DX", "patient_id": "PAT004", "detected_supplier": "fuji",
                         "study_instance_uid": "1.2.840.113619.2.416.10688137.7777777777.004"}
                        for i in range(1, 9)
                    ],
                },
            ]

            for batch_data in sample_batches:
                batch_id = str(uuid4())
                await db.execute(text("""
                    INSERT INTO batch_jobs (id, user_id, status, total_files, processed_files,
                        succeeded_files, failed_files, supplier, started_at, completed_at,
                        error_summary, created_at, updated_at)
                    VALUES (:id, :uid, :status, :total, :processed, :succeeded, :failed,
                        :supplier, :started, :completed, CAST(:err AS jsonb), :now, :now)
                """), {
                    "id": batch_id, "uid": batch_data["user_id"],
                    "status": batch_data["status"],
                    "total": batch_data["total_files"],
                    "processed": batch_data["processed_files"],
                    "succeeded": batch_data["succeeded_files"],
                    "failed": batch_data["failed_files"],
                    "supplier": batch_data["supplier"],
                    "started": batch_data["started_at"],
                    "completed": batch_data["completed_at"],
                    "err": json.dumps(batch_data["error_summary"]) if batch_data["error_summary"] else None,
                    "now": now,
                })
                print(f"  + BatchJob: {batch_data['status']} ({batch_data['total_files']} files, {batch_data['supplier']})")

                # Insert file records
                for seq, f in enumerate(batch_data["files"], 1):
                    await db.execute(text("""
                        INSERT INTO batch_job_files (id, batch_id, filename, sequence_number, status,
                            modality, patient_id, detected_supplier, study_instance_uid, created_at, updated_at)
                        VALUES (:id, :bid, :fname, :seq, :status, :mod, :pid, :supplier, :suid, :now, :now)
                    """), {
                        "id": str(uuid4()), "bid": batch_id,
                        "fname": f["filename"], "seq": seq,
                        "status": f["status"],
                        "mod": f["modality"], "pid": f["patient_id"],
                        "supplier": f["detected_supplier"],
                        "suid": f["study_instance_uid"],
                        "now": now,
                    })

        # =====================================================================
        # 5. Inference results for completed jobs
        # =====================================================================
        existing_results = await db.execute(text("SELECT count(*) FROM inference_results"))
        result_count = existing_results.scalar()

        if result_count == 0:
            # Find completed inference jobs
            completed_jobs = await db.execute(text("""
                SELECT id, model_name, study_instance_uid, inference_time_ms
                FROM inference_jobs WHERE status = 'COMPLETED'
            """))
            jobs = completed_jobs.fetchall()

            for job in jobs:
                job_id, model_name, study_uid, inf_time = job

                # Create SEG result
                await db.execute(text("""
                    INSERT INTO inference_results (id, job_id, dicom_type, orthanc_id, file_path, metadata, created_at, updated_at)
                    VALUES (:id, :jid, 'SEG', :oid, :fp, CAST(:meta AS jsonb), :now, :now)
                """), {
                    "id": str(uuid4()), "jid": str(job_id),
                    "oid": f"orthanc-seg-{str(job_id)[:8]}",
                    "fp": f"/results/{now.strftime('%Y/%m')}/seg_{str(job_id)[:8]}.dcm",
                    "meta": json.dumps({
                        "model_name": model_name,
                        "study_instance_uid": study_uid,
                        "inference_time_ms": inf_time,
                        "confidence_score": 0.87,
                        "findings_count": 2,
                        "segmentation_labels": ["lung_nodule", "ground_glass_opacity"],
                        "dicom_seg_version": "1.0",
                    }),
                    "now": now,
                })
                print(f"  + InferenceResult SEG: job {str(job_id)[:8]}")

        # =====================================================================
        # 6. Normalization reviews (sample decisions)
        # =====================================================================
        existing_reviews = await db.execute(text("SELECT count(*) FROM normalization_reviews"))
        review_count = existing_reviews.scalar()

        if review_count == 0:
            # Get completed batch with files
            batches = await db.execute(text("""
                SELECT bj.id as batch_id, bjf.id as file_id
                FROM batch_jobs bj
                JOIN batch_job_files bjf ON bjf.batch_id = bj.id
                WHERE bj.status = 'completed'
                LIMIT 5
            """))
            batch_files = batches.fetchall()

            review_decisions = ["approved", "approved", "approved", "deferred", "rejected"]
            for i, (batch_id, file_id) in enumerate(batch_files):
                decision = review_decisions[i % len(review_decisions)]
                await db.execute(text("""
                    INSERT INTO normalization_reviews (id, batch_id, file_id, decision,
                        reviewer_id, comment, reviewed_changes, created_at, updated_at)
                    VALUES (:id, :bid, :fid, :decision, :reviewer, :note, CAST(:changes AS jsonb), :now, :now)
                """), {
                    "id": str(uuid4()),
                    "bid": str(batch_id), "fid": str(file_id),
                    "decision": decision,
                    "reviewer": "admin",
                    "note": f"Review #{i+1}: {decision} - normalization changes verified" if decision == "approved"
                            else f"Review #{i+1}: {decision} - needs further review",
                    "changes": json.dumps({
                        "pixel_spacing_corrected": True if i % 2 == 0 else False,
                        "missing_tags_added": ["PatientBirthDate", "PatientSex"] if i % 3 == 0 else [],
                        "charset_fixed": i % 2 == 1,
                        "risk_level": "safe" if decision == "approved" else "medium",
                    }),
                    "now": now,
                })
                print(f"  + Review: {decision} (file {str(file_id)[:8]})")

        await db.commit()
        print("\n✅ Seed data complete!")

        # Summary
        tables = [
            "users", "ai_models", "inference_jobs", "inference_results",
            "batch_jobs", "batch_job_files", "normalization_config",
            "normalization_reviews", "supplier_rules",
        ]
        print("\n📊 Table counts:")
        for tbl in tables:
            result = await db.execute(text(f"SELECT count(*) FROM {tbl}"))
            count = result.scalar()
            print(f"  {tbl}: {count}")

    await engine.dispose()


if __name__ == "__main__":
    print("🌱 Seeding OpenPACS test data...\n")
    asyncio.run(seed())
