import { spawn, execFile as execFileCb } from 'node:child_process';
import { existsSync, openSync } from 'node:fs';
import { mkdir, rm } from 'node:fs/promises';
import path from 'node:path';
import { promisify } from 'node:util';
import playwright from 'playwright';

const { _electron } = playwright;
const execFile = promisify(execFileCb);
const repo = path.resolve('..');
const frontend = path.join(repo, 'frontend');
const root = path.join(repo, '.tmp', 'electron-native-acceptance-run');
const logs = path.join(root, 'logs');
const userData = path.join(root, 'userData');
const fixture = path.join(repo, 'TrainingTestCases/dexpi 1.3/example pids/E06 Pump, HeatExchanger, Nozzles Connected With PNS/E06V01-VER.EX01.xml');

async function killPort(port) {
  try {
    const { stdout } = await execFile('lsof', ['-ti', `tcp:${port}`]);
    for (const pid of stdout.trim().split('\n').filter(Boolean)) {
      try { process.kill(Number(pid), 'SIGTERM'); } catch {}
    }
  } catch {}
}

async function waitFor(url, attempts = 100) {
  for (let i = 0; i < attempts; i += 1) {
    try { const response = await fetch(url); if (response.ok) return; } catch {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

async function waitForExit(child, name) {
  if (child.exitCode !== null) return;
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${name} did not exit`)), 10_000);
    child.once('exit', () => { clearTimeout(timer); resolve(); });
  });
}

async function launchElectron() {
  const app = await _electron.launch({
    cwd: frontend,
    args: ['desktop/electron-main.cjs'],
    env: { ...process.env, PORTLOG_DESKTOP_UI_URL: 'http://127.0.0.1:3000', PORTLOG_DESKTOP_USER_DATA_DIR: userData, PORTLOG_QUIT_ON_WINDOW_ALL_CLOSED: '1' },
  });
  const window = await app.firstWindow();
  await window.getByRole('region', { name: 'Chat' }).waitFor({ state: 'visible', timeout: 30_000 });
  return { app, window };
}

async function closeElectron(instance) {
  await instance.window.close();
  await instance.app.close();
}

await Promise.all([killPort(3000), killPort(8000)]);
await rm(root, { recursive: true, force: true });
await mkdir(logs, { recursive: true });
const nextLog = openSync(path.join(logs, 'next.log'), 'a');
const next = spawn('npm', ['run', 'dev', '--', '--hostname', '127.0.0.1', '--port', '3000'], {
  cwd: frontend,
  env: { ...process.env, HARBORFIELD_DISABLE_BYOK: '1' },
  stdio: ['ignore', nextLog, nextLog],
});
try {
  await waitFor('http://127.0.0.1:3000/assistant');
  const first = await launchElectron();
  await first.app.evaluate(({ dialog }, fixturePath) => {
    dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [fixturePath] });
  }, fixture);
  await first.window.getByRole('button', { name: /^Import DEXPI/ }).click();
  await first.window.getByRole('complementary', { name: 'Process document graph panel' }).getByText('E06V01-VER.EX01.xml').waitFor({ state: 'visible', timeout: 30_000 });
  const manifest = path.join(userData, 'current-project', 'portlog-project.json');
  if (!existsSync(manifest)) throw new Error(`Manifest was not persisted: ${manifest}`);
  await closeElectron(first);
  await waitFor('http://127.0.0.1:8000/openapi.json', 1).then(() => { throw new Error('Sidecar still running after Electron quit'); }, () => {});

  const second = await launchElectron();
  await second.window.getByRole('complementary', { name: 'Process document graph panel' }).getByText('plant.xml').waitFor({ state: 'visible', timeout: 30_000 });
  await second.window.getByTestId('auto-layout-schematic').waitFor({ state: 'visible', timeout: 30_000 });
  await closeElectron(second);
  console.log(JSON.stringify({ ok: true, manifest }));
} finally {
  if (next.exitCode === null) next.kill('SIGTERM');
  await waitForExit(next, 'Next dev server').catch(() => next.kill('SIGKILL'));
}
