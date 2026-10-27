/**
 * Prior 원클릭 비교 (viewer-ux B, v13.17).
 *
 * 툴바 '이전검사' 버튼/단축키(p) → 백엔드 prior 조회(services/prior_lookup 재사용)
 * → 현재+prior 두 study를 로드하며 hpCompare(URL hangingprotocolid — 문자열이라
 * 매칭 우회·직접 적용)로 재진입. prior 없으면 토스트.
 */
const API_BASE = '/pacs-api/api/v1';

function currentStudyUids(): string[] {
  const params = new URLSearchParams(window.location.search);
  return params
    .getAll('StudyInstanceUIDs')
    .flatMap(v => v.split(/[,;]/))
    .map(s => s.trim())
    .filter(Boolean);
}

export async function comparePrior(servicesManager): Promise<void> {
  const { uiNotificationService } = servicesManager.services;
  const notify = (title: string, message: string, type = 'info') =>
    uiNotificationService?.show?.({ title, message, type, duration: 5000 });

  const uids = currentStudyUids();
  if (!uids.length) {
    return;
  }
  if (uids.length > 1) {
    notify('이전검사 비교', '이미 비교 화면입니다. 현재 검사만 보려면 스터디 하나로 다시 여세요.');
    return;
  }
  const current = uids[0];
  const token = localStorage.getItem('pacs_token');
  if (!token) {
    notify('이전검사 비교', '로그인 정보가 없어 이전 검사를 조회할 수 없습니다.', 'warning');
    return;
  }
  try {
    const res = await fetch(
      `${API_BASE}/studies/${encodeURIComponent(current)}/priors?max_results=1`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!res.ok) {
      throw new Error(`priors ${res.status}`);
    }
    const data = await res.json();
    const prior = (data.priors || [])[0];
    if (!prior?.study_instance_uid) {
      notify('이전검사 비교', '이 환자의 이전 검사가 없습니다.');
      return;
    }
    const date = prior.study_date
      ? ` (${String(prior.study_date).replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3')})`
      : '';
    notify('이전검사 비교', `이전 검사${date}와 비교 화면으로 전환합니다.`);
    const uids = `${encodeURIComponent(current)},${encodeURIComponent(prior.study_instance_uid)}`;
    const url =
      `/werub-viewer/viewer?StudyInstanceUIDs=${uids}` +
      `&hangingprotocolid=${encodeURIComponent('@ohif/hpCompare')}`;
    window.location.assign(url);
  } catch (e) {
    console.error('[werub-ai] prior compare failed:', e);
    notify('이전검사 비교', '이전 검사 조회에 실패했습니다.', 'error');
  }
}
