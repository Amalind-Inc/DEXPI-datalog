const { existsSync, readFileSync } = require('node:fs');
const path = require('node:path');

const FIXED_OPENROUTER = Object.freeze({
  provider: 'openrouter',
  model: 'deepseek/deepseek-v4-flash',
  credentialSource: 'environment',
});

function resolveOpenRouterEnv({ appIsPackaged, repoRoot, env = process.env }) {
  if (readEnv(env, 'PORTLOG_IGNORE_LOCAL_OPENROUTER_ENV') === '1') return { ...FIXED_OPENROUTER, configured: false, credential: undefined };
  const direct = readEnv(env, 'OPENROUTER_API_KEY');
  const credential = direct ?? (appIsPackaged ? undefined : readDotEnvValue(path.join(repoRoot, '.env'), 'OPENROUTER_API_KEY'));
  return {
    ...FIXED_OPENROUTER,
    configured: Boolean(credential),
    credential,
  };
}

function redactedOpenRouterState(resolved) {
  return {
    provider: FIXED_OPENROUTER.provider,
    model: FIXED_OPENROUTER.model,
    credentialSource: FIXED_OPENROUTER.credentialSource,
    configured: Boolean(resolved?.credential),
  };
}

function readEnv(env, key) {
  const value = env[key];
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function readDotEnvValue(filePath, key) {
  if (!existsSync(filePath)) return undefined;
  const prefix = `${key}=`;
  for (const rawLine of readFileSync(filePath, 'utf8').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#') || !line.startsWith(prefix)) continue;
    return stripEnvQuotes(line.slice(prefix.length).trim());
  }
  return undefined;
}

function stripEnvQuotes(value) {
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) return value.slice(1, -1);
  return value;
}

module.exports = { FIXED_OPENROUTER, resolveOpenRouterEnv, redactedOpenRouterState };
