# Admin Panel Design Specification

**Feature**: admin  
**Status**: Design  
**Created**: 2026-05-13  
**Version**: 1.0  

---

## Design Overview

OpenPACS Admin Panel은 Next.js 14 (App Router) + shadcn/ui + TanStack Query 기반의 엔터프라이즈급 관리 대시보드입니다. 모든 관리 작업을 중앙화된 웹 인터페이스에서 처리합니다.

---

## 1. Page Architecture

### Layout Structure
```
/admin
├── layout.tsx              (Admin 레이아웃: 사이드바 + 네비게이션)
├── page.tsx                (Dashboard 홈페이지)
├── users/
│   ├── page.tsx            (사용자 목록)
│   ├── [id]/
│   │   └── page.tsx        (사용자 상세/편집)
│   └── new/
│       └── page.tsx        (사용자 생성)
├── worklist/
│   ├── page.tsx            (워크리스트)
│   └── [id]/
│       └── page.tsx        (워크리스트 상세)
├── templates/
│   ├── page.tsx            (템플릿 목록)
│   ├── [id]/
│   │   └── page.tsx        (템플릿 편집)
│   └── new/
│       └── page.tsx        (템플릿 생성)
├── audit/
│   └── page.tsx            (감사 로그)
└── ai-models/
    └── page.tsx            (AI 모델 관리)
```

### Admin Layout Component
```tsx
// app/admin/layout.tsx
- AdminSidebar (네비게이션)
- AdminHeader (상단 바: 사용자 프로필, 알림, 로그아웃)
- BreadcrumbNav (현재 경로)
- ThemeToggle (라이트/다크 모드)
- Main Content Area
```

---

## 2. Core Components

### 2.1 Users Management

#### Users List Page
**파일**: `app/admin/users/page.tsx`

**기능**:
- 사용자 목록 (페이지네이션)
- 검색: 이름, 이메일, 역할
- 정렬: 생성일, 수정일, 상태
- 필터: 역할 (Admin, Radiologist, Physician, Technologist, Researcher)
- 상태 표시: Active/Inactive

**테이블 열**:
| 컬럼 | 타입 | 설명 |
|------|------|------|
| ID | UUID | 사용자 고유ID |
| Name | String | 사용자명 |
| Email | Email | 이메일 |
| Role | Badge | 역할 색상 배지 |
| Status | Badge | Active/Inactive |
| Created | Date | 생성일 |
| Actions | Button | Edit, Delete, ResetPassword |

**데이터 페칭**:
```javascript
GET /api/v1/users?page=1&limit=20&search=name&sort=created&order=desc
```

**Response Model**:
```json
{
  "count": 150,
  "total": 150,
  "page": 1,
  "limit": 20,
  "results": [
    {
      "id": "uuid",
      "name": "John Doe",
      "email": "john@example.com",
      "role": "radiologist",
      "status": "active",
      "createdAt": "2026-05-13T10:00:00Z",
      "updatedAt": "2026-05-13T10:00:00Z"
    }
  ]
}
```

#### User Create/Edit Form
**파일**: `app/admin/users/new/page.tsx` & `[id]/page.tsx`

**Form Fields**:
```
- Name (text, required, max 255)
- Email (email, required, unique)
- Role (select: admin, radiologist, physician, technologist, researcher)
- Status (toggle: active/inactive)
- Phone (tel, optional)
- Department (text, optional)
```

**Validation**:
- Email format validation + backend uniqueness check
- Name min 2, max 255 chars
- Password (on create): min 8, 1 uppercase, 1 number, 1 special

**API Calls**:
```
POST /api/v1/users                 (create)
PUT /api/v1/users/{id}             (update)
POST /api/v1/users/{id}/password   (reset password)
```

---

### 2.2 Worklist Management

#### Worklist Page
**파일**: `app/admin/worklist/page.tsx`

**기능**:
- 예약된 검사 목록
- 상태별 필터: Scheduled, In Progress, Completed, Cancelled
- 날짜 범위 필터
- 환자명 검색

**테이블 열**:
| 컬럼 | 타입 | 설명 |
|------|------|------|
| Study ID | UUID | 검사ID |
| Patient | String | 환자명 |
| Modality | Badge | 검사 방식 (CT, MR, XR, etc) |
| Status | Badge | 상태 (색상 구분) |
| Scheduled Date | Date | 예약 날짜 |
| Priority | Badge | 우선순위 (Normal, Urgent, STAT) |
| Technologist | String | 담당 기사 |
| Actions | Button | View, Edit, Cancel |

**API Call**:
```
GET /api/v1/worklist?status=scheduled&date_from=2026-05-01&date_to=2026-05-31
```

---

### 2.3 Report Template Management

#### Template List Page
**파일**: `app/admin/templates/page.tsx`

**기능**:
- 템플릿 목록 (카드 또는 테이블)
- 템플릿 생성, 편집, 삭제
- 버전 관리 표시
- 사용 통계 (사용 횟수)

**카드 표시**:
```
┌─────────────────────────┐
│ 템플릿명                  │
│ v1.2 (Latest)           │
│ 150회 사용               │
│ 마지막 수정: 2026-05-13 │
│ [Edit] [Preview] [Delete]│
└─────────────────────────┘
```

#### Template Editor
**파일**: `app/admin/templates/[id]/page.tsx`

**에디터**:
- 마크다운 에디터 (좌측)
- 미리보기 (우측, 라이브 업데이트)
- 템플릿 변수 삽입 (`{{patient_name}}`, `{{date}}`, etc)
- 저장 & 버전 생성

**마크다운 지원**:
- 기본 문법 (bold, italic, headers)
- 테이블
- 리스트
- 코드 블록 (금지)
- HTML 제거 (XSS 방지)

**API Calls**:
```
GET /api/v1/templates/{id}
PUT /api/v1/templates/{id}
POST /api/v1/templates
DELETE /api/v1/templates/{id}
```

---

### 2.4 Audit Log Viewer

#### Audit Log Page
**파일**: `app/admin/audit/page.tsx`

**기능**:
- 감사 로그 목록 (시간순 역정렬)
- 필터:
  - 날짜 범위 (Date Picker)
  - 사용자 (Select + Search)
  - 작업 유형 (LOGIN, CREATE, UPDATE, DELETE, EXPORT)
  - 엔티티 (User, Study, Report, Template, etc)
- 검색: 로그 메시지, IP 주소

**테이블 열**:
| 컬럼 | 타입 | 설명 |
|------|------|------|
| Timestamp | DateTime | 작업 시간 |
| User | String | 사용자명 |
| Action | Badge | 작업 유형 (색상) |
| Entity | String | 대상 (e.g., Study, User) |
| Details | String | 상세 (클릭 시 상세 정보) |
| IP | String | IP 주소 |
| Status | Badge | Success/Failed |

**상세 보기 (Modal)**:
```json
{
  "id": "uuid",
  "timestamp": "2026-05-13T10:30:00Z",
  "userId": "uuid",
  "userName": "John Doe",
  "action": "UPDATE",
  "entity": "User",
  "entityId": "uuid",
  "changes": {
    "status": ["active", "inactive"]
  },
  "ipAddress": "192.168.1.1",
  "userAgent": "Mozilla/5.0...",
  "status": "success"
}
```

**API Call**:
```
GET /api/v1/audit?date_from=2026-05-01&date_to=2026-05-31&action=UPDATE&limit=50&page=1
```

**내보내기 기능**:
- CSV export (선택된 행 또는 전체)
- JSON export

---

### 2.5 AI Model Management

#### AI Models Page
**파일**: `app/admin/ai-models/page.tsx`

**기능**:
- 등록된 AI 모델 목록
- 모델 상태 (Active/Inactive)
- 모델 성능 메트릭 표시
- 모델 활성화/비활성화
- 모델 삭제

**카드 표시**:
```
┌──────────────────────────────┐
│ [Lung Cancer Detection]      │
│ v2.1.0                       │
│ Status: Active (Green)       │
│ Accuracy: 94.2%              │
│ Inference Time: 250ms        │
│ Last Updated: 2026-05-10     │
│ [Disable] [View Metrics] [Delete]│
└──────────────────────────────┘
```

**상태 표시**:
- Active: 초록색
- Inactive: 회색
- Error: 빨간색

**API Calls**:
```
GET /api/v1/ai/models
POST /api/v1/ai/models/{id}/enable
POST /api/v1/ai/models/{id}/disable
DELETE /api/v1/ai/models/{id}
```

---

## 3. Shared Components

### 3.1 Data Table Component
```tsx
<DataTable
  columns={[...]}
  data={users}
  pagination={{page, limit, total}}
  isLoading={isLoading}
  onPageChange={setPage}
  onSort={setSort}
  searchFields={['name', 'email']}
/>
```

**기능**:
- 페이지네이션 (이전/다음/페이지 입력)
- 정렬 (헤더 클릭)
- 스켈레톤 로딩 상태
- 빈 상태 메시지

### 3.2 Filter Panel
```tsx
<FilterPanel
  filters={[
    { id: 'status', label: 'Status', type: 'select', options: [...] },
    { id: 'dateRange', label: 'Date Range', type: 'daterange' },
  ]}
  onFilter={handleFilter}
/>
```

### 3.3 Form Components
```tsx
<Form>
  <FormField name="email" label="Email" type="email" required />
  <FormField name="role" label="Role" type="select" options={roles} />
  <FormButton type="submit">Save</FormButton>
</Form>
```

**Validation**: Zod + React Hook Form

### 3.4 Dialog Components
```tsx
<ConfirmDialog
  title="Delete User?"
  description="This action cannot be undone."
  onConfirm={handleDelete}
/>
```

---

## 4. State Management

### API Integration (TanStack Query)
```tsx
// Hooks
const { data, isLoading, error } = useQuery({
  queryKey: ['users', page, limit, search],
  queryFn: () => fetchUsers({page, limit, search}),
  staleTime: 5 * 60 * 1000, // 5 분
})

const mutation = useMutation({
  mutationFn: updateUser,
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['users'] })
  }
})
```

### Form State (React Hook Form)
```tsx
const form = useForm({
  resolver: zodResolver(userSchema),
  defaultValues: user,
})
```

### Client State (React Context)
- Admin preferences (theme, sidebar collapse)
- Selected filters (per page)
- Clipboard state (for bulk actions)

---

## 5. Error Handling

### Error Display Pattern
```tsx
{error && (
  <Alert variant="destructive">
    <AlertTitle>Error</AlertTitle>
    <AlertDescription>{error.message}</AlertDescription>
  </Alert>
)}
```

### Error Types & Messages
| Error | Message | Action |
|-------|---------|--------|
| 401 Unauthorized | "Your session expired. Please login again." | Redirect to login |
| 403 Forbidden | "You don't have permission to perform this action." | Show warning |
| 404 Not Found | "Resource not found. It may have been deleted." | Navigate back |
| 422 Validation Error | "{field} is required" (per field) | Highlight field |
| 500 Server Error | "An error occurred. Please try again." | Retry button |

### Network Error Handling
- Automatic retry on network failures (up to 3 times)
- Exponential backoff
- Offline indicator (if offline mode needed)

---

## 6. Security & Access Control

### Authentication
- JWT token required (Authorization header)
- Role check: Only Admin role can access `/admin/*`
- Route protection middleware

### Input Validation
- Email format validation (frontend + backend)
- Email uniqueness check (backend)
- Phone number format (optional backend validation)
- HTML/Script sanitization (DOMPurify)

### RBAC Enforcement
```tsx
<AdminRoute>
  <AdminLayout>
    {/* Only accessible if user.role === 'admin' */}
  </AdminLayout>
</AdminRoute>
```

### CSRF Protection
- Next.js built-in CSRF protection
- SameSite cookie: Strict

---

## 7. Performance Optimization

### Code Splitting
```tsx
const UsersList = lazy(() => import('./users/page'))
const TemplateEditor = lazy(() => import('./templates/[id]/page'))
```

### Data Caching Strategy
| Resource | TTL | Stale | Revalidate |
|----------|-----|-------|-----------|
| User list | 5 min | 2 min | Manual |
| User detail | 30 sec | 10 sec | Manual |
| Templates | 10 min | 3 min | Manual |
| Audit logs | 1 min | 30 sec | Auto (every min) |
| AI Models | 5 min | 2 min | Manual |

### Virtual Scrolling
- Used for tables with 1000+ rows
- `react-window` integration

### Image Optimization
- Avatar images: `next/image` with `placeholder="blur"`
- Lazy loading by default

---

## 8. Responsive Design

### Breakpoints
```css
- Mobile: 320px - 640px (single column, stacked layout)
- Tablet: 641px - 1024px (2 columns, sidebar hidden)
- Desktop: 1025px+ (3+ columns, sidebar visible)
```

### Mobile Adaptations
- Sidebar → Bottom navigation (mobile)
- Table → Card layout (mobile)
- Compact spacing & font sizes
- Touch-friendly button sizes (44px minimum)

---

## 9. API Integration Details

### Base Configuration
```javascript
const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || '/pacs-api',
  timeout: 10000,
})

// Request interceptor (add JWT)
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('authToken')
  config.headers.Authorization = `Bearer ${token}`
  return config
})

// Response interceptor (handle 401/403)
api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401) {
      // Redirect to login
    }
    return Promise.reject(error)
  }
)
```

### API Endpoints Used

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/v1/users` | List users |
| POST | `/api/v1/users` | Create user |
| PUT | `/api/v1/users/{id}` | Update user |
| DELETE | `/api/v1/users/{id}` | Delete user |
| POST | `/api/v1/users/{id}/password` | Reset password |
| GET | `/api/v1/worklist` | List worklist |
| GET | `/api/v1/templates` | List templates |
| POST | `/api/v1/templates` | Create template |
| PUT | `/api/v1/templates/{id}` | Update template |
| DELETE | `/api/v1/templates/{id}` | Delete template |
| GET | `/api/v1/audit` | List audit logs |
| GET | `/api/v1/ai/models` | List AI models |
| POST | `/api/v1/ai/models/{id}/enable` | Enable model |
| POST | `/api/v1/ai/models/{id}/disable` | Disable model |

---

## 10. Testing Strategy

### Unit Tests (Jest)
- Component rendering
- Form validation
- Utility functions

### Integration Tests
- Data fetching & caching
- Form submission
- Error handling

### E2E Tests (Playwright)
- User CRUD workflow
- Worklist filtering & pagination
- Template editor markdown preview

### Coverage Target
- > 85% code coverage
- All critical paths covered
- Error scenarios tested

---

## 11. Accessibility (WCAG 2.1 Level AA)

### Requirements
- Semantic HTML (button, form, heading hierarchy)
- ARIA labels on form inputs
- Keyboard navigation (Tab, Enter, Escape)
- Color contrast (4.5:1 for text)
- Focus visible (outline or highlight)
- Screen reader support

### Tools
- axe DevTools (manual testing)
- lighthouse (automated)
- Keyboard navigation testing

---

## 12. Implementation Order

### Phase 1: Foundation (2 hours)
1. Admin layout & sidebar
2. Route protection middleware
3. API client setup
4. Shared components (DataTable, FilterPanel, etc)

### Phase 2: Users Management (2 hours)
5. Users list page
6. User create/edit form
7. User delete dialog
8. Password reset

### Phase 3: Worklist & Templates (1.5 hours)
9. Worklist page
10. Template CRUD
11. Template editor with markdown

### Phase 4: Audit & AI (1 hour)
12. Audit log viewer
13. AI models page
14. Export functionality

### Phase 5: Polish (0.5 hours)
15. Error handling refinement
16. Mobile responsive adjustments
17. Performance optimization

---

## 13. Known Constraints & Assumptions

- Backend APIs must return paginated results
- User role defaults to 'physician' if not specified
- Email must be unique across system
- Soft delete enabled for users (status = inactive)
- Markdown editor HTML tags are stripped for security
- Admin users can only delete inactive users (business rule)

---

## 14. Success Criteria

| Criteria | Target |
|----------|--------|
| All 5 management features operational | 100% |
| API endpoint coverage | 100% |
| Code coverage (unit tests) | > 85% |
| Accessibility (WCAG 2.1 AA) | 100% |
| Mobile responsive (3 breakpoints) | 100% |
| Load time (first paint) | < 2s |
| Design match rate | ≥ 90% |

---

**Document Version**: 1.0  
**Phase**: Design  
**Next Step**: `/pdca do admin`
