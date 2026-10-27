# Admin Panel Feature Plan

**Feature**: admin  
**Status**: Planning  
**Created**: 2026-05-13  
**Target Completion**: v1.1  

---

## Executive Summary

OpenPACS 관리 대시보드(Admin Panel)는 시스템 관리자가 사용자, 워크리스트, 템플릿, 감사 로그, AI 모델을 중앙에서 관리할 수 있는 웹 기반 관리 인터페이스입니다. Next.js 기반의 모던 UI로 구현되어 있으며, 역할 기반 접근 제어(RBAC)를 통해 보안이 강화되어 있습니다.

---

## Requirements

### Functional Requirements

#### 1. 사용자 관리 (User Management)
- [ ] 사용자 목록 조회 (페이지네이션 포함)
- [ ] 사용자 생성 (Create)
- [ ] 사용자 정보 수정 (Update)
- [ ] 사용자 삭제 (Delete, Soft Delete)
- [ ] 사용자 역할 변경 (Role assignment)
- [ ] 비밀번호 초기화
- [ ] 사용자 상태 활성화/비활성화

#### 2. 워크리스트 관리 (Worklist Management)
- [ ] 예약된 검사 목록 조회
- [ ] 검사 상태 추적 (Scheduled → In Progress → Completed)
- [ ] 검사 정보 수정
- [ ] 검사 삭제 (취소)
- [ ] 일괄 작업 (Bulk operations)

#### 3. 판독 템플릿 관리 (Report Template Management)
- [ ] 템플릿 목록 조회
- [ ] 템플릿 생성 (마크다운 에디터)
- [ ] 템플릿 수정
- [ ] 템플릿 삭제
- [ ] 템플릿 버전 관리
- [ ] 템플릿 미리보기

#### 4. 감사 로그 조회 (Audit Log Viewer)
- [ ] 감사 로그 목록 (필터 & 검색)
- [ ] 로그 상세 조회
- [ ] 로그 익스포트 (CSV/JSON)
- [ ] 날짜 범위 필터링
- [ ] 사용자별/작업별 필터링

#### 5. AI 모델 관리 (AI Model Management)
- [ ] 등록된 AI 모델 목록
- [ ] 모델 상태 모니터링 (Active/Inactive)
- [ ] 모델 메타데이터 조회
- [ ] 모델 활성화/비활성화
- [ ] 모델 삭제

### Non-Functional Requirements

- **Authentication**: JWT Bearer Token 인증 필수
- **Authorization**: Admin 역할 전용 접근
- **Performance**: 1000+ 레코드 페이지네이션 처리
- **UI/UX**: Responsive 디자인 (모바일 지원)
- **Accessibility**: WCAG 2.1 준수
- **Data Validation**: 입력값 검증 및 에러 메시지 표시

---

## Key Features

| Feature | Priority | Impact | Effort |
|---------|----------|--------|--------|
| 사용자 관리 CRUD | P0 | 핵심 | M |
| 워크리스트 관리 | P1 | 중요 | M |
| 감사 로그 조회 | P1 | 의료 준수 | S |
| 템플릿 관리 | P2 | 편의성 | L |
| AI 모델 관리 | P2 | 시스템 관리 | S |

---

## Architecture & Technical Decisions

### Frontend Stack
- **Framework**: Next.js 14 (App Router)
- **UI Library**: shadcn/ui (Tailwind CSS)
- **State Management**: React Context API (+ TanStack Query for caching)
- **Form Validation**: React Hook Form + Zod
- **Data Table**: TanStack React Table v8 (pagination, sorting, filtering)

### Backend API Integration
- **Base URL**: `/pacs-api/api/v1/`
- **Authentication**: Authorization header (Bearer {token})
- **Error Handling**: StandardError response format with request_id

### Data Caching Strategy
- List endpoints: 5분 TTL (TanStack Query)
- User details: 30초 TTL (빈번한 업데이트)
- System settings: 1시간 TTL

### Security Considerations
- [ ] RBAC: Admin 역할 검증
- [ ] Input sanitization: XSS 방지
- [ ] CSRF 토큰 (Next.js 기본)
- [ ] Rate limiting: 관리 API 속도 제한
- [ ] Audit logging: 모든 변경사항 기록

---

## Scope

### In Scope
✅ 5가지 주요 관리 기능 (Users, Worklist, Templates, Audit, AI Models)  
✅ 모더니즘 UI (shadcn/ui + Tailwind)  
✅ 페이지네이션 및 필터링  
✅ 권한 기반 접근 제어 (Admin only)  
✅ 에러 처리 및 로딩 상태  
✅ 반응형 디자인 (Desktop/Tablet/Mobile)  

### Out of Scope (Future Releases)
❌ Advanced reporting/analytics  
❌ Bulk import (CSV/Excel)  
❌ Email notifications  
❌ Scheduled tasks  
❌ Custom fields  

---

## Success Criteria

| Criteria | Target | Measurement |
|----------|--------|-------------|
| **Design Compliance** | ≥90% Match Rate | Gap analysis report |
| **API Coverage** | 100% endpoints used | All 5 features functional |
| **Security** | 0 critical vulnerabilities | OWASP checklist |
| **Performance** | <500ms initial load | Lighthouse audit |
| **Accessibility** | WCAG 2.1 Level AA | axe DevTools |
| **Responsiveness** | Mobile-first | 3 breakpoints tested |

---

## Implementation Order

### Phase 1: Users Management
1. User list page (pagination, search)
2. User create/edit form
3. User delete (with confirmation)
4. Role assignment

### Phase 2: Worklist & Templates
5. Worklist page (status overview)
6. Template CRUD (with markdown editor)
7. Audit log viewer

### Phase 3: AI Models & Polish
8. AI model list (with status)
9. Model management (enable/disable)
10. UI refinement & mobile optimization

---

## Dependencies & Prerequisites

### Backend APIs Required
- ✅ `GET /api/v1/users` (list with pagination)
- ✅ `POST /api/v1/users` (create)
- ✅ `PUT /api/v1/users/{id}` (update)
- ✅ `DELETE /api/v1/users/{id}` (delete)
- ✅ `GET /api/v1/worklist` (list)
- ✅ `GET /api/v1/templates` (list)
- ✅ `POST /api/v1/templates` (create)
- ✅ `GET /api/v1/audit` (logs)
- ✅ `GET /api/v1/ai/models` (list)

### Frontend Libraries
- `next@14.0.0+`
- `shadcn/ui@latest`
- `react-hook-form@7.45+`
- `zod@3.22+`
- `@tanstack/react-table@8.0+`
- `@tanstack/react-query@4.32+`

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| Backend API delays | Medium | High | Parallel development with mock API |
| RBAC enforcement gaps | Low | High | Security review before release |
| Performance on large datasets | Medium | Medium | Implement virtual scrolling + pagination |
| Mobile UI complexity | Medium | Medium | Mobile-first design approach |

---

## Metrics & Success Indicators

- ✅ 100% CRUD operations functional
- ✅ < 100ms response time for list operations
- ✅ 0 console errors/warnings
- ✅ > 85% code coverage (unit tests)
- ✅ Zero critical accessibility issues
- ✅ Design match rate ≥ 90%

---

## Timeline Estimate

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| Design Document | 30 min | design.md |
| Implementation | 4-6 hours | Code + components |
| Testing | 1-2 hours | Unit + E2E tests |
| Gap Analysis | 30 min | analysis.md |
| Final Report | 30 min | report.md |
| **Total** | **7-9 hours** | Completed admin panel |

---

## Notes & Assumptions

- Backend APIs are already implemented (or will be mocked)
- Design system (shadcn/ui) is already configured
- User has admin role to test admin features
- Docker environment is running for backend testing
- TypeScript strict mode enabled

---

**Document Version**: 1.0  
**Phase**: Planning  
**Next Step**: `/pdca design admin`
