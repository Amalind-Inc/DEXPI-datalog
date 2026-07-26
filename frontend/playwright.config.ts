import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: true,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command:
        "HARBORFIELD_DEPLOYMENT_PROFILE=local HARBORFIELD_QA_PROVIDER=scripted HARBORFIELD_QA_SCRIPTED_STEP_DELAY_MS=300 PYTHONPATH=.. HARBORFIELD_REVIEW_ARTIFACT_ROOT=../.tmp/review-sessions ../.venv/bin/python -m uvicorn pydexpi_datalog.web.asgi:app --host 127.0.0.1 --port 8000",
      url: "http://127.0.0.1:8000/docs",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      // Force the deterministic stub provider for e2e regardless of any real key
      // in the shell or repo .env. The real tool-calling model path is covered by
      // Python integration tests (test_qa_turns_real_provider.py).
      command: "HARBORFIELD_DISABLE_BYOK=1 npm run dev -- --hostname 127.0.0.1",
      url: "http://127.0.0.1:3000",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
