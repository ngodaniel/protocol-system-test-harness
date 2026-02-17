import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'tests/e2e',
  use: {
    baseURL: 'http://127.0.0.1:8000',
  },
  webServer: {
    command: 'uvicorn services.device_sim.app.main:app --host 127.0.0.1 --port 8000',
    url: 'http://127.0.0.1:8000/health',
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
