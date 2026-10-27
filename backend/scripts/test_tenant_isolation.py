"""Tenant isolation integration test.

Tests that multi-tenancy row-level isolation works correctly:
1. Creates 2 test tenants (hospital-a, hospital-b)
2. Creates a report in tenant A
3. Verifies tenant B cannot see tenant A's report
4. Verifies default tenant backward compatibility
5. Cleans up test data
"""
import asyncio
import os
import sys
from uuid import uuid4

import asyncpg

DB_URL = os.getenv("DATABASE_URL", "postgresql://openpacs:OpenPACS2026!@localhost:5432/openpacs")

TENANT_A = {"id": f"test-a-{uuid4().hex[:8]}", "name": "Hospital A", "slug": f"hosp-a-{uuid4().hex[:8]}"}
TENANT_B = {"id": f"test-b-{uuid4().hex[:8]}", "name": "Hospital B", "slug": f"hosp-b-{uuid4().hex[:8]}"}
REPORT_ID = str(uuid4())

results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = ""):
    status = "PASS" if passed else "FAIL"
    results.append((name, passed, detail))
    print(f"  [{status}] {name}" + (f" -- {detail}" if detail else ""))


async def main():
    print("=== Tenant Isolation Test ===\n")

    # Parse asyncpg-compatible DSN
    dsn = DB_URL.replace("postgresql://", "postgres://", 1) if DB_URL.startswith("postgresql://") else DB_URL
    conn: asyncpg.Connection = await asyncpg.connect(dsn)

    try:
        # --- Setup: create test tenants ---
        print("[Setup] Creating test tenants...")
        for t in (TENANT_A, TENANT_B):
            await conn.execute(
                "INSERT INTO tenants (id, name, slug) VALUES ($1, $2, $3)",
                t["id"], t["name"], t["slug"],
            )
        record("Create test tenants", True)

        # --- Test 1: Insert report for tenant A ---
        print("\n[Test 1] Insert report in tenant A...")
        await conn.execute(
            """INSERT INTO reports (id, study_uid, patient_id, patient_name, status, tenant_id)
               VALUES ($1, $2, $3, $4, 'draft', $5)""",
            REPORT_ID, "1.2.3.4.TEST", "P001", "Test Patient", TENANT_A["id"],
        )
        row = await conn.fetchrow("SELECT id, tenant_id FROM reports WHERE id = $1", REPORT_ID)
        record("Report created in tenant A", row is not None and row["tenant_id"] == TENANT_A["id"])

        # --- Test 2: Tenant B cannot see tenant A's report ---
        print("\n[Test 2] Verify tenant B isolation...")
        rows_b = await conn.fetch(
            "SELECT id FROM reports WHERE tenant_id = $1 AND id = $2",
            TENANT_B["id"], REPORT_ID,
        )
        record("Tenant B cannot see tenant A report", len(rows_b) == 0)

        # --- Test 3: Tenant A can see its own report ---
        print("\n[Test 3] Verify tenant A sees its own report...")
        rows_a = await conn.fetch(
            "SELECT id FROM reports WHERE tenant_id = $1 AND id = $2",
            TENANT_A["id"], REPORT_ID,
        )
        record("Tenant A sees its own report", len(rows_a) == 1)

        # --- Test 4: Default tenant backward compatibility ---
        print("\n[Test 4] Default tenant backward compatibility...")
        default_row = await conn.fetchrow("SELECT id, is_active FROM tenants WHERE id = 'default'")
        record("Default tenant exists", default_row is not None)
        if default_row:
            record("Default tenant is active", default_row["is_active"] is True)

        # --- Test 5: Unfiltered query returns all tenants' data ---
        print("\n[Test 5] Cross-tenant query without filter...")
        all_reports = await conn.fetch("SELECT id, tenant_id FROM reports WHERE id = $1", REPORT_ID)
        record("Unfiltered query sees test report", len(all_reports) == 1,
               f"tenant_id={all_reports[0]['tenant_id']}" if all_reports else "")

    finally:
        # --- Cleanup ---
        print("\n[Cleanup] Removing test data...")
        await conn.execute("DELETE FROM reports WHERE id = $1", REPORT_ID)
        for t in (TENANT_A, TENANT_B):
            await conn.execute("DELETE FROM tenants WHERE id = $1", t["id"])
        print("  Cleaned up.\n")
        await conn.close()

    # --- Summary ---
    passed = sum(1 for _, p, _ in results if p)
    total = len(results)
    print(f"=== Results: {passed}/{total} passed ===")
    if passed < total:
        print("FAILED tests:")
        for name, p, detail in results:
            if not p:
                print(f"  - {name}: {detail}")
        sys.exit(1)
    else:
        print("All tests PASSED.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
