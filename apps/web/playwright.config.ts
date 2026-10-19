import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 60000,
  workers: 1,
  fullyParallel: false,
  reporter: [['list'], ['json', { outputFile: '../../data/v6-playwright-results.json' }]],
  webServer: !process.env.REPOLENS_WEB_URL
    ? {
        command: `${process.env.REPOLENS_TEST_PYTHON || 'python'} -m repolens.workbench.launcher --port 8770 --no-browser --data-dir data/v6-e2e`,
        cwd: '../..',
        url: 'http://127.0.0.1:8770/api/health',
        timeout: 30000,
      }
    : undefined,
  use: {
    baseURL: process.env.REPOLENS_WEB_URL || 'http://127.0.0.1:8770',
    channel: process.env.CI ? undefined : 'msedge',
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
});
