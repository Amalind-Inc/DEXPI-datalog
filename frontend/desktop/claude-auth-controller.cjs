const DEFAULT_TIMEOUT_MS = 120_000;
const PROVIDER = "anthropic";
const SERVICE = "org.portlog.desktop.anthropic.oauth";
const ACCOUNT = "default";

function createClaudeAuthController(options) {
  const oauth = options.oauth;
  const keychain = options.keychain;
  const openExternal = options.openExternal;
  const now = options.now ?? (() => Date.now());
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  let credentials = null;
  let loaded = false;
  let state = "logged_out";
  let error = null;
  let loginRun = null;
  let authGeneration = 0;

  async function loadStoredCredentials() {
    if (loaded) return;
    loaded = true;
    let raw;
    try {
      raw = await keychain.read();
    } catch {
      state = "logged_out";
      error = "Claude credentials could not be read from Keychain.";
      return;
    }
    credentials = parseCredentials(raw);
    if (credentials) state = "logged_in";
  }

  async function status() {
    await loadStoredCredentials();
    if (!loginRun && credentials) await refreshIfNeeded();
    return publicStatus();
  }

  async function login() {
    if (loginRun) return loginRun.promise;
    const generation = ++authGeneration;
    const controller = new AbortController();
    let cancelLogin;
    let rejectCancellation;
    const cancellation = new Promise((_, reject) => {
      rejectCancellation = reject;
    });
    const cancellationError = () => abortError("Claude login cancelled.");
    const run = {
      controller,
      promise: null,
      cancel: () => {
        if (controller.signal.aborted) return;
        controller.abort();
        rejectCancellation(cancellationError());
      },
    };
    cancelLogin = run.cancel;
    loginRun = run;
    state = "opening_browser";
    error = null;

    const providerLogin = Promise.resolve().then(() =>
      oauth.login({
        signal: controller.signal,
        onAuth: (info) => {
          if (controller.signal.aborted) return;
          state = "waiting_for_authorization";
          void Promise.resolve(openExternal(info.url)).catch(() => {
            error = "PortLog could not open the Claude authorization page.";
            cancelLogin();
          });
        },
        onProgress: () => {},
        onManualCodeInput: () => waitForAbort(controller.signal),
        onPrompt: async () => {
          if (controller.signal.aborted) throw abortError("Claude login cancelled.");
          throw abortError("Claude login requires browser authorization.");
        },
        onDeviceCode: () => {},
        onSelect: async () => undefined,
      }),
    );
    // A provider implementation may own a callback listener. Always consume
    // its eventual rejection even when PortLog's timeout/cancellation wins.
    void providerLogin.catch(() => {});

    const timeout = setTimeout(() => {
      if (!controller.signal.aborted) {
        error = "Claude login timed out. Try again.";
        cancelLogin();
      }
    }, timeoutMs);

    run.promise = (async () => {
      try {
        const result = await Promise.race([providerLogin, cancellation]);
        if (controller.signal.aborted) throw cancellationError();
        const next = parseCredentials(result);
        if (!next) throw new Error("Invalid credentials returned by Claude.");
        await keychain.write(JSON.stringify(next));
        if (controller.signal.aborted) return publicStatus();
        credentials = next;
        state = "logged_in";
        error = null;
        return publicStatus();
      } catch (cause) {
        if (generation !== authGeneration) throw publicError("Claude login cancelled.");
        if (controller.signal.aborted || isAbortError(cause)) {
          state = "cancelled";
          error = error ?? "Claude login cancelled.";
        } else {
          state = "logged_out";
          error = "Claude login could not be completed.";
        }
        throw publicError(error);
      } finally {
        clearTimeout(timeout);
        if (loginRun === run) loginRun = null;
      }
    })();
    return run.promise;
  }

  async function cancel() {
    if (!loginRun) return publicStatus();
    loginRun.cancel();
    return publicStatus();
  }

  async function logout() {
    authGeneration += 1;
    if (loginRun) loginRun.cancel();
    credentials = null;
    loaded = true;
    try {
      await keychain.delete();
    } catch {
      state = "logged_in";
      error = "Claude credentials could not be removed from Keychain.";
      throw publicError(error);
    }
    state = "logged_out";
    error = null;
    return publicStatus();
  }

  async function getAccessToken() {
    await loadStoredCredentials();
    if (!credentials) throw publicError(error ?? "Claude is not connected.");
    await refreshIfNeeded();
    if (!credentials) throw publicError(error ?? "Claude is not connected.");
    return oauth.getApiKey(credentials);
  }

  async function refreshIfNeeded() {
    if (!credentials) return false;
    if (credentials.expires > now()) {
      state = "logged_in";
      return true;
    }
    try {
      const refreshed = parseCredentials(await oauth.refreshToken(credentials));
      if (!refreshed) throw new Error("Invalid refreshed credentials.");
      await keychain.write(JSON.stringify(refreshed));
      credentials = refreshed;
      state = "logged_in";
      error = null;
      return true;
    } catch {
      credentials = null;
      state = "refresh_failed";
      error = "Claude session expired or could not be refreshed. Log in again.";
      return false;
    }
  }

  function publicStatus() {
    return {
      provider: PROVIDER,
      state,
      recoverable: true,
      ...(error ? { error } : {}),
      ...(credentials && state === "logged_in" ? { expiresAt: credentials.expires } : {}),
    };
  }

  return {
    status,
    login,
    cancel,
    logout,
    getAccessToken,
    constants: { provider: PROVIDER, service: SERVICE, account: ACCOUNT },
  };
}

function parseCredentials(value) {
  let candidate = value;
  if (typeof value === "string") {
    try {
      candidate = JSON.parse(value);
    } catch {
      return null;
    }
  }
  if (!candidate || typeof candidate !== "object") return null;
  const record = candidate;
  if (
    typeof record.access !== "string" ||
    typeof record.refresh !== "string" ||
    typeof record.expires !== "number" ||
    !Number.isFinite(record.expires)
  )
    return null;
  return { access: record.access, refresh: record.refresh, expires: record.expires };
}

function waitForAbort(signal) {
  if (signal.aborted) return Promise.resolve("");
  return new Promise((resolve) =>
    signal.addEventListener("abort", () => resolve(""), { once: true }),
  );
}

function abortError(message) {
  const error = new Error(message);
  error.name = "AbortError";
  return error;
}

function isAbortError(value) {
  return value && typeof value === "object" && value.name === "AbortError";
}

function publicError(message) {
  const error = new Error(message);
  error.code = "CLAUDE_AUTH_RECOVERABLE";
  return error;
}

module.exports = {
  ACCOUNT,
  DEFAULT_TIMEOUT_MS,
  PROVIDER,
  SERVICE,
  createClaudeAuthController,
};
