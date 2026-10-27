import { defineConfig } from '@playwright/test';

// 운영 서버 대상 클릭스루 — 로그인 rate limit(5/min/계정) 때문에 workers=1 + 토큰 캐시 사용
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: process.env.PACS_BASE_URL || 'https://his.example.org',
    ignoreHTTPSErrors: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    locale: 'ko-KR',
    viewport: { width: 1600, height: 900 },
  },
  reporter: [['list']],
});
