"""
OpenPACS v8.3 Performance Load Test
====================================
Locust-based load test targeting the production server.

Usage:
    # Web UI (recommended)
    locust -f tests/load/locustfile.py --host https://his.example.org

    # Headless: 50 users, ramp 5/s, run 5 min
    locust -f tests/load/locustfile.py --host https://his.example.org \
        --users 50 --spawn-rate 5 --run-time 5m --headless \
        --csv results/load_test

    # Smoke test: 5 users
    locust -f tests/load/locustfile.py --host https://his.example.org \
        --users 5 --spawn-rate 1 --run-time 1m --headless

Environment variables:
    PACS_USERNAME  - login username (default: admin)
    PACS_PASSWORD  - login password (default: CHANGE_ME)
    ORTHANC_USER   - Orthanc basic auth user (default: admin)
    ORTHANC_PASS   - Orthanc basic auth password (default: CHANGE_ME)
"""

import json
import os
import random
import time

from locust import HttpUser, TaskSet, between, events, task, tag


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PACS_USERNAME = os.getenv("PACS_USERNAME", "admin")
PACS_PASSWORD = os.getenv("PACS_PASSWORD", "CHANGE_ME")
ORTHANC_USER = os.getenv("ORTHANC_USER", "admin")
ORTHANC_PASS = os.getenv("ORTHANC_PASS", "CHANGE_ME")

MODALITIES = ["CR", "CT", "MR", "DX", "US", "XA", "MG", "PT"]
BODY_PARTS = ["CHEST", "ABDOMEN", "HEAD", "SPINE", "PELVIS", "KNEE", "SHOULDER"]


# ---------------------------------------------------------------------------
# Shared state: study IDs discovered during the test
# ---------------------------------------------------------------------------
_discovered_studies = []
_discovered_series = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def orthanc_auth():
    """Return basic auth tuple for Orthanc endpoints."""
    return (ORTHANC_USER, ORTHANC_PASS)


# ---------------------------------------------------------------------------
# Main User
# ---------------------------------------------------------------------------
class PACSUser(HttpUser):
    """Simulates a radiologist / physician using the PACS system."""

    wait_time = between(1, 3)
    access_token = None
    refresh_token = None
    user_id = None

    def on_start(self):
        """Login and obtain JWT token."""
        resp = self.client.post(
            "/pacs-api/api/v1/auth/login",
            json={"username": PACS_USERNAME, "password": PACS_PASSWORD},
            name="/auth/login",
        )
        if resp.status_code == 200:
            data = resp.json()
            self.access_token = data["access_token"]
            self.refresh_token = data["refresh_token"]
            self.user_id = data.get("user_id")
        else:
            self.access_token = None

    @property
    def auth_headers(self):
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        return {}

    # -----------------------------------------------------------------------
    # Scenario 1: Core API Endpoints
    # -----------------------------------------------------------------------
    @task(5)
    @tag("health")
    def health_check(self):
        self.client.get("/pacs-api/health", name="/health")

    @task(10)
    @tag("api", "statistics")
    def get_statistics(self):
        self.client.get(
            "/pacs-api/api/v1/statistics",
            headers=self.auth_headers,
            name="/statistics",
        )

    @task(15)
    @tag("api", "worklist")
    def get_worklist(self):
        self.client.get(
            "/pacs-api/api/v1/worklist",
            headers=self.auth_headers,
            name="/worklist",
        )

    @task(10)
    @tag("api", "dashboard")
    def get_dashboard(self):
        self.client.get(
            "/pacs-api/api/v1/dashboard/today",
            headers=self.auth_headers,
            name="/dashboard/today",
        )

    @task(10)
    @tag("api", "reports")
    def get_reports(self):
        self.client.get(
            "/pacs-api/api/v1/reports",
            headers=self.auth_headers,
            name="/reports",
        )

    @task(5)
    @tag("api", "reading-stats")
    def get_reading_stats(self):
        """Note: /api/v1/reports/statistics is shadowed by /api/v1/reports/{report_id}
        due to router registration order. Using /api/v1/dashboard/today as proxy."""
        self.client.get(
            "/pacs-api/api/v1/dashboard/today",
            headers=self.auth_headers,
            name="/dashboard/today (stats proxy)",
        )

    @task(5)
    @tag("api", "notifications")
    def get_notifications(self):
        self.client.get(
            "/pacs-api/api/v1/notifications?limit=20",
            headers=self.auth_headers,
            name="/notifications",
        )

    @task(3)
    @tag("api", "system")
    def get_system_info(self):
        self.client.get(
            "/pacs-api/api/v1/system/info",
            headers=self.auth_headers,
            name="/system/info",
        )

    # -----------------------------------------------------------------------
    # Scenario 2: DICOMweb Queries (via Nginx proxy → Orthanc)
    # -----------------------------------------------------------------------
    @task(20)
    @tag("dicomweb", "studies")
    def dicomweb_search_studies(self):
        params = {}
        if random.random() < 0.5:
            params["ModalitiesInStudy"] = random.choice(MODALITIES)
        if random.random() < 0.3:
            params["limit"] = 25

        resp = self.client.get(
            "/dicom-web/studies",
            params=params,
            name="/dicom-web/studies",
        )
        if resp.status_code == 200:
            try:
                studies = resp.json()
                if studies and isinstance(studies, list):
                    for s in studies[:5]:
                        study_uid = s.get("0020000D", {}).get("Value", [None])[0]
                        if study_uid and study_uid not in _discovered_studies:
                            _discovered_studies.append(study_uid)
                            if len(_discovered_studies) > 200:
                                _discovered_studies.pop(0)
            except (json.JSONDecodeError, TypeError):
                pass

    @task(15)
    @tag("dicomweb", "series")
    def dicomweb_search_series(self):
        if not _discovered_studies:
            return
        study_uid = random.choice(_discovered_studies)
        resp = self.client.get(
            f"/dicom-web/studies/{study_uid}/series",
            name="/dicom-web/studies/[uid]/series",
        )
        if resp.status_code == 200:
            try:
                series_list = resp.json()
                if series_list and isinstance(series_list, list):
                    for sr in series_list[:3]:
                        series_uid = sr.get("0020000E", {}).get("Value", [None])[0]
                        if series_uid:
                            entry = (study_uid, series_uid)
                            if entry not in _discovered_series:
                                _discovered_series.append(entry)
                                if len(_discovered_series) > 200:
                                    _discovered_series.pop(0)
            except (json.JSONDecodeError, TypeError):
                pass

    @task(5)
    @tag("dicomweb", "metadata")
    def dicomweb_study_metadata(self):
        if not _discovered_studies:
            return
        study_uid = random.choice(_discovered_studies)
        with self.client.get(
            f"/dicom-web/studies/{study_uid}/metadata",
            name="/dicom-web/studies/[uid]/metadata",
            catch_response=True,
        ) as resp:
            if resp.status_code == 404:
                resp.success()  # Study may have been removed; not a real error

    @task(3)
    @tag("dicomweb", "instances")
    def dicomweb_series_instances(self):
        if not _discovered_series:
            return
        study_uid, series_uid = random.choice(_discovered_series)
        self.client.get(
            f"/dicom-web/studies/{study_uid}/series/{series_uid}/instances",
            name="/dicom-web/studies/[uid]/series/[uid]/instances",
        )

    # -----------------------------------------------------------------------
    # Scenario 3: Worklist workflow (create → list → update)
    # -----------------------------------------------------------------------
    @task(3)
    @tag("api", "worklist", "write")
    def worklist_workflow(self):
        accession = f"LT{int(time.time()*1000000)}{random.randint(0,99999):05d}"
        modality = random.choice(MODALITIES)
        body_part = random.choice(BODY_PARTS)

        payload = {
            "patient_id": f"PT-LOAD-{random.randint(1000,9999)}",
            "patient_name": f"LOAD^TEST^{random.randint(1,50)}",
            "accession_number": accession,
            "requested_procedure_id": f"RP-{accession}",
            "requested_procedure_description": f"{modality} {body_part}",
            "scheduled_station_ae_title": "OPENPACS",
            "modality": modality,
            "scheduled_date": "2026-05-20",
            "body_part_examined": body_part,
            "priority": random.choice(["routine", "high", "stat"]),
        }

        resp = self.client.post(
            "/pacs-api/api/v1/worklist",
            json=payload,
            headers=self.auth_headers,
            name="/worklist [POST]",
        )
        if resp.status_code in (200, 201):
            try:
                item = resp.json()
                item_id = item.get("id")
                if item_id:
                    self.client.get(
                        f"/pacs-api/api/v1/worklist/{item_id}",
                        headers=self.auth_headers,
                        name="/worklist/[id] [GET]",
                    )
            except (json.JSONDecodeError, TypeError):
                pass

    # -----------------------------------------------------------------------
    # Scenario 4: Report workflow (read existing)
    # -----------------------------------------------------------------------
    @task(5)
    @tag("api", "reports", "templates")
    def get_report_templates(self):
        self.client.get(
            "/pacs-api/api/v1/templates",
            headers=self.auth_headers,
            name="/templates",
        )

    # -----------------------------------------------------------------------
    # Scenario 5: Auth - token refresh
    # -----------------------------------------------------------------------
    @task(2)
    @tag("auth")
    def refresh_token(self):
        if not self.refresh_token:
            return
        resp = self.client.post(
            "/pacs-api/api/v1/auth/refresh",
            json={"refresh_token": self.refresh_token},
            name="/auth/refresh",
        )
        if resp.status_code == 200:
            data = resp.json()
            self.access_token = data.get("access_token", self.access_token)
            self.refresh_token = data.get("refresh_token", self.refresh_token)

    # -----------------------------------------------------------------------
    # Scenario 6: Audit log (admin reads)
    # -----------------------------------------------------------------------
    @task(2)
    @tag("api", "audit")
    def get_audit_logs(self):
        self.client.get(
            "/pacs-api/api/v1/audit?limit=20",
            headers=self.auth_headers,
            name="/audit",
        )

    # -----------------------------------------------------------------------
    # Scenario 7: SLA / Emergency
    # -----------------------------------------------------------------------
    @task(2)
    @tag("api", "sla")
    def get_sla_config(self):
        self.client.get(
            "/pacs-api/api/v1/sla/config",
            headers=self.auth_headers,
            name="/sla/config",
        )

    @task(2)
    @tag("api", "emergency")
    def get_emergency_board(self):
        self.client.get(
            "/pacs-api/api/v1/emergency/board",
            headers=self.auth_headers,
            name="/emergency/board",
        )


# ---------------------------------------------------------------------------
# Event Hooks: Custom reporting
# ---------------------------------------------------------------------------
@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    """Print summary on test completion."""
    stats = environment.runner.stats
    total = stats.total

    print("\n" + "=" * 70)
    print("OpenPACS Load Test Summary")
    print("=" * 70)
    print(f"Total requests:    {total.num_requests}")
    print(f"Total failures:    {total.num_failures}")
    print(f"Error rate:        {total.fail_ratio * 100:.2f}%")
    print(f"Avg response time: {total.avg_response_time:.0f}ms")
    print(f"p50:               {total.get_response_time_percentile(0.50):.0f}ms")
    print(f"p95:               {total.get_response_time_percentile(0.95):.0f}ms")
    print(f"p99:               {total.get_response_time_percentile(0.99):.0f}ms")
    print(f"RPS:               {total.current_rps:.1f}")
    print(f"Studies discovered: {len(_discovered_studies)}")
    print("=" * 70)

    # Pass/Fail evaluation
    fail_ratio = total.fail_ratio
    p95 = total.get_response_time_percentile(0.95)

    issues = []
    if fail_ratio > 0.01:
        issues.append(f"Error rate {fail_ratio*100:.2f}% > 1%")
    if p95 > 2000:
        issues.append(f"p95 {p95:.0f}ms > 2000ms")

    if issues:
        print(f"RESULT: FAIL - {'; '.join(issues)}")
    else:
        print("RESULT: PASS")
    print("=" * 70)
