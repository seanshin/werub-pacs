"""Viewer launch by AccessionNumber (P4 / LIS C1).

External systems (e.g. LIS pathology reading screen) know a study by its
AccessionNumber, not its StudyInstanceUID. The WeRU.B viewer route only accepts
`?StudyInstanceUIDs=`. This thin launcher resolves AccessionNumber -> Study UID(s)
via Orthanc and 302-redirects into the viewer, so a caller can open one URL:

    https://his.example.org/pacs-api/api/v1/viewer/launch?AccessionNumber=ACC-SP-2026-0456

Design notes:
- No auth dependency: this is a top-level browser navigation (new window/tab)
  which cannot carry a Bearer header. The *viewer* enforces auth (SSO/localStorage
  token) when it loads. This endpoint only reveals an opaque UID via a redirect —
  no PHI — mirroring the viewer being a public entry point.
- Not an open-redirect: the target origin+path are fixed (settings.base_url +
  /werub-viewer/viewer); only opaque Study UIDs from Orthanc go into the query.
"""
import logging
from html import escape
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/viewer", tags=["Viewer Launch"])


def _err(message: str, accession: str, status: int) -> HTMLResponse:
    body = (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<title>WeRU.B 뷰어</title></head>"
        "<body style='font-family:sans-serif;padding:2rem;color:#222'>"
        f"<h3>{escape(message)}</h3>"
        f"<p>AccessionNumber: <code>{escape(accession)}</code></p>"
        "</body></html>"
    )
    return HTMLResponse(body, status_code=status)


@router.get("/launch", summary="AccessionNumber로 뷰어 실행")
async def launch_viewer(
    request: Request,
    AccessionNumber: str | None = Query(None, max_length=64),
    accession: str | None = Query(None, max_length=64),
):
    """Resolve AccessionNumber to Study UID(s) and 302-redirect into the viewer.

    Accepts `AccessionNumber` (DICOM/QIDO convention) or `accession` alias.
    404 if no matching study; 400 if the parameter is missing.
    """
    acc = (AccessionNumber or accession or "").strip()
    if not acc:
        return _err("AccessionNumber 파라미터가 필요합니다", "", 400)

    orthanc = request.app.state.http_client
    try:
        # ModalitiesInStudy is only populated via RequestedTags (see dicomweb.py)
        resp = await orthanc.post(
            "/tools/find",
            json={"Level": "Study", "Query": {"AccessionNumber": acc}, "Expand": True,
                  "Limit": 10, "RequestedTags": ["ModalitiesInStudy"]},
        )
        studies = resp.json() if resp.status_code == 200 else []
    except Exception as e:
        logger.error("viewer/launch Orthanc lookup failed for %r: %s", acc, e)
        return _err("검사 조회 중 오류가 발생했습니다", acc, 502)

    studies = studies if isinstance(studies, list) else []
    uids = [u for u in (s.get("MainDicomTags", {}).get("StudyInstanceUID") for s in studies) if u]
    if not uids:
        return _err("해당 AccessionNumber의 검사를 찾을 수 없습니다", acc, 404)

    # Whole Slide Microscopy (SM) must open in the microscopy mode route; the
    # default /viewer (cornerstone/longitudinal) does not render WSI. Detect SM
    # via ModalitiesInStudy and route accordingly.
    def _mods(s):
        rt = s.get("RequestedTags") or {}
        return (rt.get("ModalitiesInStudy") or s.get("MainDicomTags", {}).get("ModalitiesInStudy", "") or "")
    is_sm = any("SM" in _mods(s).split("\\") for s in studies)
    route = "microscopy" if is_sm else "viewer"

    query = urlencode([("StudyInstanceUIDs", u) for u in uids])
    target = f"{settings.base_url}/werub-viewer/{route}?{query}"
    logger.info("viewer/launch %r -> %d study(ies), route=%s", acc, len(uids), route)
    return RedirectResponse(url=target, status_code=302)
