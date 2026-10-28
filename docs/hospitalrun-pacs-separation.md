## PACS 분리 공지 (2026-05-09)

### 변경 사항
PACS(Orthanc + OHIF Viewer + FastAPI 백엔드) 관련 코드와 설정이 **별도 프로젝트로 분리**되었습니다.

- **새 저장소**: https://github.com/seanshin/werub-pacs
- **서버 코드**: `/home/deploy/openpacs/backend/`
- **담당 CLI**: openpacs 프로젝트에서 별도 관리

### 이 프로젝트(HospitalRun)에서 달라진 점

**docker-compose.yml이 변경됨** (`/home/deploy/hospital-run/infra/docker/docker-compose.yml`)
- 기존: postgres + redis만 정의
- 변경: postgres + redis + **orthanc + ohif + backend(FastAPI)** 추가됨
- HospitalRun 서비스(api, web, migrate, nginx)는 docker-compose.prod.yml에 있으므로 영향 없음

**Nginx 설정 변경됨** (`/etc/nginx/sites-enabled/hospital-run`)
- `/pacs-api/` 경로 추가됨 → FastAPI OpenPACS API (포트 8001)
- 기존 HospitalRun 경로(`/api/`, `/`)는 그대로 유지, 변경 없음

**PostgreSQL**
- `openpacs` DB가 추가됨 (기존 `hospitalrun` DB는 변경 없음)
- `hospital` 사용자 비밀번호가 `secret`으로 리셋됨

### HospitalRun CLI가 지켜야 할 규칙
1. **docker-compose.yml의 orthanc, ohif, backend 서비스를 수정/삭제하지 말 것** — OpenPACS 팀이 관리
2. **Nginx에서 `/pacs-api/`, `/dicom-web/`, `/wado`, `/pacs/`, `/viewer/` 경로를 건드리지 말 것**
3. **PostgreSQL `openpacs` DB를 건드리지 말 것**
4. HospitalRun 서비스 변경 시 `docker compose restart` 대신 **개별 서비스 지정**: `docker compose restart api web`
5. docker-compose.yml 수정이 필요하면 **postgres, redis 서비스만 수정** 가능

### 포트 할당 정리

| 포트 | 서비스 | 소유 |
|------|--------|------|
| 3000 | HospitalRun Web (Next.js) | HospitalRun |
| 4000 | HospitalRun API (NestJS) | HospitalRun |
| 5432 | PostgreSQL | 공유 (hospitalrun DB + openpacs DB) |
| 6379 | Redis | 공유 |
| 3001 | OHIF Viewer | **OpenPACS** |
| 4242 | Orthanc DICOM | **OpenPACS** |
| 8001 | FastAPI Backend | **OpenPACS** |
| 8042 | Orthanc HTTP | **OpenPACS** |

### 문의
PACS 관련 이슈는 https://github.com/seanshin/werub-pacs 에서 관리합니다.
