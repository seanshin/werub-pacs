# Admin Panel Implementation Guide (Do Phase)

**Feature**: admin  
**Status**: Implementation  
**Start Date**: 2026-05-13  
**Estimated Duration**: 7 hours  

---

## Implementation Checklist

### Phase 1: Foundation (2 hours)

- [ ] **1.1 Admin Layout Setup**
  - Create `admin/layout.tsx` with sidebar & header
  - Implement responsive navigation (desktop/mobile toggle)
  - Add breadcrumb navigation component
  - Setup theme toggle (light/dark mode)

- [ ] **1.2 Route Protection**
  - Create `middleware.ts` for auth check
  - Implement admin role verification
  - Setup redirect to login on unauthorized access
  - Add loading skeleton during auth check

- [ ] **1.3 API Client Setup**
  - Create `lib/api/client.ts` with axios instance
  - Setup request/response interceptors (JWT + error handling)
  - Create `lib/hooks/useApi.ts` for common API patterns
  - Add environment variable configuration

- [ ] **1.4 Shared Components**
  - [ ] `components/admin/DataTable.tsx` - Pagination, sorting, search
  - [ ] `components/admin/FilterPanel.tsx` - Dynamic filters
  - [ ] `components/admin/FormField.tsx` - Reusable form inputs
  - [ ] `components/admin/ConfirmDialog.tsx` - Delete confirmation
  - [ ] `components/admin/ErrorAlert.tsx` - Error display
  - [ ] `components/admin/LoadingSkeletons.tsx` - Skeleton loaders

---

### Phase 2: Users Management (2 hours)

- [ ] **2.1 Users List Page**
  - Create `admin/users/page.tsx`
  - Implement DataTable with columns (ID, Name, Email, Role, Status, Actions)
  - Add search by name/email
  - Add role filter dropdown
  - Add status filter (Active/Inactive)
  - Implement pagination (20 items/page)
  - Add sorting by Created Date, Last Modified
  - Add loading & empty states
  - Add API call: `GET /api/v1/users?page=X&limit=20`

- [ ] **2.2 User Create Page**
  - Create `admin/users/new/page.tsx`
  - Build form with fields: Name, Email, Role, Status, Phone, Department
  - Implement form validation with Zod + React Hook Form
  - Add "Back" button & "Create" button
  - Handle form submission: `POST /api/v1/users`
  - Show success toast on creation
  - Redirect to users list on success

- [ ] **2.3 User Edit Page**
  - Create `admin/users/[id]/page.tsx`
  - Fetch user data: `GET /api/v1/users/{id}`
  - Pre-fill form with existing values
  - Allow editing Name, Email, Role, Status, Phone, Department
  - Implement update: `PUT /api/v1/users/{id}`
  - Add "Delete User" button
  - Show delete confirmation dialog
  - Handle delete: `DELETE /api/v1/users/{id}`
  - Show error handling for 404 (user not found)

- [ ] **2.4 User List Actions**
  - Add "Edit" action (navigate to user edit page)
  - Add "Delete" action (show confirm dialog)
  - Add "Reset Password" action (call `POST /api/v1/users/{id}/password`)
  - Show inline status indicator (green=active, gray=inactive)
  - Add role badge with color coding

---

### Phase 3: Worklist & Templates (1.5 hours)

- [ ] **3.1 Worklist Page**
  - Create `admin/worklist/page.tsx`
  - Fetch worklist: `GET /api/v1/worklist?status=&date_from=&date_to=`
  - Build table with: Study ID, Patient, Modality, Status, Scheduled Date, Priority, Technologist
  - Add status filter dropdown (Scheduled, In Progress, Completed, Cancelled)
  - Add date range picker (from/to)
  - Add patient name search
  - Implement pagination
  - Add status badge styling (colors per status)
  - Add priority badge styling

- [ ] **3.2 Worklist Detail Page**
  - Create `admin/worklist/[id]/page.tsx`
  - Fetch study details
  - Display full worklist item information
  - Add status update dropdown (if allowed)
  - Add "Cancel Study" button
  - Show related images count

- [ ] **3.3 Template List Page**
  - Create `admin/templates/page.tsx`
  - Fetch templates: `GET /api/v1/templates`
  - Display as card grid or table
  - Show template name, version, usage count, last modified date
  - Add "Create Template" button
  - Add "Edit" action per template
  - Add "Delete" action with confirmation
  - Show usage statistics

- [ ] **3.4 Template Editor**
  - Create `admin/templates/[id]/page.tsx` (edit) & `new/page.tsx` (create)
  - Left side: Markdown editor (textarea)
  - Right side: Live markdown preview
  - Add variable insertion buttons: {{patient_name}}, {{date}}, {{doctor}}, etc
  - Add format toolbar (Bold, Italic, Heading, List, Table buttons)
  - Implement markdown to HTML preview (sanitized)
  - Add "Save" button: `PUT /api/v1/templates/{id}` or `POST /api/v1/templates`
  - Add "Preview" toggle
  - Show unsaved changes warning

---

### Phase 4: Audit & AI (1 hour)

- [ ] **4.1 Audit Log Page**
  - Create `admin/audit/page.tsx`
  - Fetch audit logs: `GET /api/v1/audit?date_from=&date_to=&action=&user_id=`
  - Build table with: Timestamp, User, Action, Entity, Details, IP, Status
  - Add date range filter (from/to)
  - Add action filter dropdown (LOGIN, CREATE, UPDATE, DELETE, EXPORT)
  - Add user filter (select + search)
  - Add search for IP address or message
  - Implement pagination
  - Add "View Details" modal (show JSON changes)
  - Add "Export to CSV" button
  - Add "Export to JSON" button

- [ ] **4.2 Audit Log Detail Modal**
  - Show full log details in modal
  - Display changes in before/after format
  - Show timestamps in local timezone
  - Add copy-to-clipboard for request ID

- [ ] **4.3 AI Models Page**
  - Create `admin/ai-models/page.tsx`
  - Fetch models: `GET /api/v1/ai/models`
  - Display as card grid
  - Show: Model name, version, status (Active/Inactive), accuracy, inference time
  - Add "Enable" / "Disable" toggle per model
  - Add "Delete" button with confirmation
  - Show last updated date
  - Add model type badge (Classification, Detection, Segmentation)

- [ ] **4.4 AI Model Actions**
  - Implement enable: `POST /api/v1/ai/models/{id}/enable`
  - Implement disable: `POST /api/v1/ai/models/{id}/disable`
  - Implement delete: `DELETE /api/v1/ai/models/{id}`
  - Show loading state during action
  - Show success/error toast

---

### Phase 5: Polish & Optimization (0.5 hours)

- [ ] **5.1 Error Handling**
  - Wrap all API calls in try-catch
  - Show error alerts on failure
  - Implement retry logic for failed requests
  - Handle 401 (redirect to login), 403 (show forbidden message), 404 (show not found)
  - Show user-friendly error messages

- [ ] **5.2 Loading States**
  - Add skeleton loaders for tables
  - Add spinner during data fetch
  - Disable buttons during submission
  - Show loading state on page transitions

- [ ] **5.3 Mobile Responsiveness**
  - Test on mobile (320px)
  - Convert sidebar to bottom navigation on mobile
  - Stack form fields vertically on mobile
  - Hide non-essential columns on mobile (use card layout)
  - Test tablet (640px) and desktop (1024px) breakpoints

- [ ] **5.4 Performance Optimization**
  - Implement TanStack Query caching (5min TTL for lists)
  - Add debounce to search inputs (300ms)
  - Lazy load large lists (virtual scrolling if 1000+ items)
  - Optimize image loading (avatars with placeholder)
  - Check Lighthouse score (target > 85)

- [ ] **5.5 Accessibility Review**
  - Verify keyboard navigation (Tab, Enter, Escape)
  - Add ARIA labels to form inputs
  - Check color contrast (target 4.5:1)
  - Test with screen reader
  - Verify heading hierarchy

---

## Key Files & Components to Create

### Directory Structure
```
admin/
├── layout.tsx                    # Admin layout wrapper
├── page.tsx                      # Dashboard home
├── users/
│   ├── page.tsx                  # Users list
│   ├── new/page.tsx              # Create user
│   └── [id]/page.tsx             # Edit user
├── worklist/
│   ├── page.tsx                  # Worklist list
│   └── [id]/page.tsx             # Worklist detail
├── templates/
│   ├── page.tsx                  # Templates list
│   ├── new/page.tsx              # Create template
│   └── [id]/page.tsx             # Edit template
├── audit/
│   └── page.tsx                  # Audit logs
└── ai-models/
    └── page.tsx                  # AI models

components/admin/
├── AdminSidebar.tsx              # Navigation sidebar
├── AdminHeader.tsx               # Top header bar
├── BreadcrumbNav.tsx             # Breadcrumb
├── DataTable.tsx                 # Reusable table component
├── FilterPanel.tsx               # Filter controls
├── FormField.tsx                 # Form input wrapper
├── ConfirmDialog.tsx             # Delete confirmation
├── ErrorAlert.tsx                # Error message
├── LoadingSkeletons.tsx           # Skeleton loaders
├── MarkdownEditor.tsx            # Markdown editor for templates
└── AuditLogDetail.tsx            # Modal for log details

lib/
├── api/
│   ├── client.ts                 # Axios configuration
│   └── endpoints.ts              # API endpoint constants
├── hooks/
│   ├── useApi.ts                 # Common API hook
│   ├── useUsers.ts               # Users API queries
│   ├── useWorklist.ts            # Worklist API queries
│   ├── useTemplates.ts           # Templates API queries
│   ├── useAudit.ts               # Audit API queries
│   └── useAIModels.ts            # AI models API queries
├── validators/
│   ├── userSchema.ts             # Zod user validation
│   ├── templateSchema.ts         # Zod template validation
│   └── filterSchema.ts           # Zod filter validation
└── utils/
    ├── formatters.ts             # Date, role, status formatters
    └── exporters.ts              # CSV/JSON export helpers

middleware.ts                      # Route protection middleware
```

---

## Dependencies to Install

```bash
# Core dependencies (if not already installed)
npm install next@14 react@18 react-dom@18
npm install shadcn-ui
npm install @tanstack/react-table@8
npm install @tanstack/react-query@5
npm install react-hook-form@7 zod
npm install axios
npm install tailwindcss postcss autoprefixer
npm install class-variance-authority clsx tailwind-merge
npm install react-markdown remark-gfm
npm install js-cookie js-cookie-ts

# UI Components (via shadcn-cli)
npx shadcn-ui@latest add button
npx shadcn-ui@latest add input
npx shadcn-ui@latest add select
npx shadcn-ui@latest add textarea
npx shadcn-ui@latest add badge
npx shadcn-ui@latest add dialog
npx shadcn-ui@latest add alert
npx shadcn-ui@latest add card
npx shadcn-ui@latest add tabs
npx shadcn-ui@latest add date-picker
npx shadcn-ui@latest add table
npx shadcn-ui@latest add skeleton
npx shadcn-ui@latest add toast

# Dev dependencies (for testing)
npm install -D @testing-library/react @testing-library/jest-dom jest
npm install -D @types/js-cookie
```

---

## API Endpoints Reference

### Users API
```
GET    /api/v1/users?page=1&limit=20&search=&sort=created&order=desc
POST   /api/v1/users
GET    /api/v1/users/{id}
PUT    /api/v1/users/{id}
DELETE /api/v1/users/{id}
POST   /api/v1/users/{id}/password
```

### Worklist API
```
GET    /api/v1/worklist?status=&date_from=&date_to=&search=&page=1&limit=20
GET    /api/v1/worklist/{id}
PUT    /api/v1/worklist/{id}/status
DELETE /api/v1/worklist/{id}
```

### Templates API
```
GET    /api/v1/templates
POST   /api/v1/templates
GET    /api/v1/templates/{id}
PUT    /api/v1/templates/{id}
DELETE /api/v1/templates/{id}
```

### Audit API
```
GET    /api/v1/audit?date_from=&date_to=&action=&user_id=&page=1&limit=50
GET    /api/v1/audit/{id}
GET    /api/v1/audit/export?format=csv|json
```

### AI Models API
```
GET    /api/v1/ai/models
POST   /api/v1/ai/models/{id}/enable
POST   /api/v1/ai/models/{id}/disable
DELETE /api/v1/ai/models/{id}
```

---

## Environment Variables

Create `.env.local`:
```bash
# API Configuration
NEXT_PUBLIC_API_URL=http://localhost:8001/pacs-api
NEXT_PUBLIC_API_TIMEOUT=10000

# Authentication
NEXT_PUBLIC_AUTH_TOKEN_KEY=authToken
NEXT_PUBLIC_AUTH_REFRESH_INTERVAL=5m

# Pagination
NEXT_PUBLIC_PAGE_SIZE=20
NEXT_PUBLIC_AUDIT_PAGE_SIZE=50

# Features
NEXT_PUBLIC_ENABLE_DARK_MODE=true
NEXT_PUBLIC_ENABLE_EXPORT=true
```

---

## Code Snippets & Patterns

### 1. Using TanStack Query for Data Fetching
```tsx
// lib/hooks/useUsers.ts
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api/client'

export function useUsers(page = 1, limit = 20, search = '') {
  return useQuery({
    queryKey: ['users', page, limit, search],
    queryFn: async () => {
      const { data } = await api.get('/users', {
        params: { page, limit, search }
      })
      return data
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}
```

### 2. Using React Hook Form + Zod
```tsx
// components/admin/UserForm.tsx
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { userSchema } from '@/lib/validators/userSchema'

export function UserForm({ defaultValues, onSubmit }) {
  const form = useForm({
    resolver: zodResolver(userSchema),
    defaultValues,
  })

  return (
    <form onSubmit={form.handleSubmit(onSubmit)}>
      <FormField
        label="Name"
        {...form.register('name')}
        error={form.formState.errors.name?.message}
      />
      <button type="submit">Save</button>
    </form>
  )
}
```

### 3. Protected Admin Route
```tsx
// app/admin/layout.tsx
import { redirect } from 'next/navigation'
import { getSession } from '@/lib/auth'

export default async function AdminLayout({ children }) {
  const session = await getSession()
  
  if (!session?.user || session.user.role !== 'admin') {
    redirect('/login')
  }

  return (
    <div className="flex">
      <AdminSidebar />
      <main className="flex-1">{children}</main>
    </div>
  )
}
```

### 4. Data Table with Pagination
```tsx
// components/admin/DataTable.tsx
import { useState } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  getPaginationRowModel,
} from '@tanstack/react-table'

export function DataTable({ columns, data, pagination, onPageChange }) {
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    state: { pagination },
    onPaginationChange: onPageChange,
  })

  return (
    <div>
      <table>
        {/* render table */}
      </table>
      {/* pagination controls */}
    </div>
  )
}
```

---

## Testing Approach

### Unit Tests (Jest + React Testing Library)
```bash
# Test layout rendering
# Test form validation
# Test data table sorting/filtering
# Test modal dialogs
```

### Integration Tests
```bash
# Test user CRUD workflow
# Test worklist filtering
# Test template editor
# Test audit log export
```

### E2E Tests (Playwright)
```bash
# Test complete admin workflow
# Test authentication & authorization
# Test error handling
# Test mobile responsiveness
```

---

## Git Commit Strategy

```bash
git commit -m "chore: setup admin layout and navigation"
git commit -m "feat: implement users management CRUD"
git commit -m "feat: implement worklist and templates management"
git commit -m "feat: implement audit log viewer and AI models page"
git commit -m "refactor: optimize performance and accessibility"
git commit -m "test: add unit and integration tests"
```

---

## Deployment Checklist

- [ ] All environment variables set in production
- [ ] API endpoints verified against backend
- [ ] Error handling tested (401, 403, 404, 500)
- [ ] Mobile responsiveness verified
- [ ] Accessibility audit passed
- [ ] Performance audit (Lighthouse > 85)
- [ ] Security review (XSS, CSRF, injection)
- [ ] Rate limiting tested
- [ ] Database queries optimized

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Implementation time | ≤ 7 hours |
| Code coverage | ≥ 85% |
| Lighthouse score | ≥ 85 |
| API endpoint coverage | 100% |
| Mobile usability | Pass |
| Accessibility | WCAG 2.1 AA |

---

## Common Pitfalls & Solutions

| Pitfall | Solution |
|---------|----------|
| Slow data loading | Use TanStack Query caching + virtual scrolling |
| Form validation errors | Use Zod + React Hook Form + field-level errors |
| Auth token expiration | Implement refresh token logic in interceptor |
| Mobile layout broken | Use mobile-first CSS + test at 320px |
| XSS in markdown | Use DOMPurify to sanitize HTML |
| Missing error handling | Wrap all API calls in try-catch + show user feedback |

---

**Start Date**: 2026-05-13  
**Estimated Completion**: ~7 hours  
**Next Phase**: Gap analysis (`/pdca analyze admin`)
