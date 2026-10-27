"""Reading report PDF generation."""
import io
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.report import ReportReadRoles, _can_read_study  # 동일 역할게이트·PHYSICIAN 스코프 재사용
from app.core.database import get_db
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.report import Report
from app.models.user import User

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


def _generate_report_html(report: Report) -> str:
    """Generate HTML for report PDF."""
    signed = f"{report.signed_by_name} ({report.signed_at.strftime('%Y-%m-%d %H:%M')})" if report.signed_at else "미서명"
    urgency_labels = {"normal": "정상", "non_urgent": "비긴급 이상", "urgent": "긴급"}
    urgency_color = {"normal": "#16a34a", "urgent": "#dc2626"}.get(report.urgency, "#333")

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family: 'Noto Sans KR', sans-serif; margin: 40px; color: #333; font-size: 14px; }}
  h1 {{ font-size: 22px; border-bottom: 2px solid #2563eb; padding-bottom: 8px; color: #1e3a5f; }}
  .header {{ display: flex; justify-content: space-between; margin-bottom: 20px; }}
  .info-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
  .info-table td {{ padding: 6px 12px; border: 1px solid #ddd; }}
  .info-table td:first-child {{ background: #f8f9fa; font-weight: bold; width: 120px; }}
  .section {{ margin-bottom: 16px; }}
  .section h3 {{ font-size: 14px; color: #2563eb; margin-bottom: 4px; border-left: 3px solid #2563eb; padding-left: 8px; }}
  .section-content {{ background: #f8f9fa; padding: 12px; border-radius: 4px; white-space: pre-wrap; line-height: 1.6; }}
  .impression {{ background: #ecfdf5; border-left: 4px solid #16a34a; }}
  .urgency {{ display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; color: white; background: {urgency_color}; }}
  .footer {{ margin-top: 30px; border-top: 1px solid #ddd; padding-top: 10px; font-size: 12px; color: #888; }}
  .signature {{ margin-top: 20px; text-align: right; }}
  .disclaimer {{ font-size: 11px; color: #999; margin-top: 20px; padding: 8px; background: #fefce8; border-radius: 4px; }}
</style></head><body>
<h1>판독 리포트</h1>

<table class="info-table">
  <tr><td>환자명</td><td>{report.patient_name or '-'}</td><td>환자번호</td><td>{report.patient_id}</td></tr>
  <tr><td>모달리티</td><td>{report.modality or '-'}</td><td>검사일</td><td>{report.study_date or '-'}</td></tr>
  <tr><td>검사설명</td><td>{report.study_description or '-'}</td><td>접수번호</td><td>{report.accession_number or '-'}</td></tr>
  <tr><td>긴급도</td><td><span class="urgency">{urgency_labels.get(report.urgency, report.urgency or '정상')}</span></td>
      <td>상태</td><td>{report.status}</td></tr>
</table>

{f'<div class="section"><h3>임상 정보</h3><div class="section-content">{report.clinical_info}</div></div>' if report.clinical_info else ''}

<div class="section"><h3>소견 (Findings)</h3>
<div class="section-content">{report.findings or '-'}</div></div>

<div class="section"><h3>결론 (Impression)</h3>
<div class="section-content impression">{report.impression or '-'}</div></div>

{f'<div class="section"><h3>권고 사항</h3><div class="section-content">{report.recommendation}</div></div>' if report.recommendation else ''}

<div class="signature">
  <p><strong>판독의:</strong> {report.author_name}</p>
  <p><strong>서명:</strong> {signed}</p>
</div>

<div class="footer">
  <p>OpenPACS — 병원 PACS 시스템</p>
  <p>Study UID: {report.study_instance_uid}</p>
  <p>생성일: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
</div>

<div class="disclaimer">
  본 리포트는 전자의무기록의 일부이며, 무단 복제 및 배포를 금합니다.
</div>
</body></html>"""


@router.get("/{report_id}/pdf")
async def download_report_pdf(
    report_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ReportReadRoles)],
):
    """Download reading report as PDF (HTML-based).

    Returns HTML that can be printed to PDF via browser.
    For proper PDF, use browser's Print → Save as PDF.
    """
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise NotFoundError(resource="Report", resource_id=str(report_id))
    # PHYSICIAN은 본인 의뢰 study의 PDF만(이름+MRN 노출 차단).
    if not await _can_read_study(db, user, report.study_instance_uid):
        raise ForbiddenError("본인이 의뢰한 환자의 리포트만 열람할 수 있습니다.")

    html = _generate_report_html(report)

    return StreamingResponse(
        iter([html.encode("utf-8")]),
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f"inline; filename=report_{str(report_id)[:8]}.html",
        },
    )
