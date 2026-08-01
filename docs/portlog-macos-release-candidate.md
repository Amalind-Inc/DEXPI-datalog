# PortLog macOS development release candidate

This document describes the release candidate produced by `pydexpi-datalog-1-34eu.7`.
It is a development build, not a public production release.

## Locked support target

- macOS 14 Sonoma or newer
- Apple Silicon `arm64` only (M1 or newer)
- Intel/x64, Universal builds, macOS 13 and earlier, Windows, and Linux are out of scope
- The primary artifact is an arm64 DMG; the matching `.app` directory is also emitted for smoke testing
- The app bundle is read-only at runtime and may be copied to a path containing spaces

The package embeds the standalone Next renderer, an arm64 PyInstaller Python sidecar,
and the arm64 Soufflé executable. A user must not install Node.js, Python, Soufflé, or
a hosted PortLog account.

## Build

Run on an arm64 Mac with the repository virtualenv and Homebrew Soufflé available:

```bash
cd frontend
npm install
npm run desktop:package:dir
```

The command builds the Next standalone renderer, freezes the local API with PyInstaller,
copies `/opt/homebrew/bin/souffle` into the sidecar, stages only the Electron runtime
dependencies, and invokes electron-builder. Set `PORTLOG_SOUFFLE_PATH` when the arm64
Soufflé binary is elsewhere.

Outputs:

```text
frontend/release/dist/PortLog-0.1.0-arm64.dmg
frontend/release/dist/mac-arm64/PortLog.app
```

The exact filename is printed by electron-builder. `release-manifest.json` records the
architecture and signing posture. The package is deliberately arm64-only.

## Signing and Gatekeeper

The candidate uses ad-hoc signing (`identity: "-"`) and is **not notarized**. It must be
labelled `Development release candidate—not notarized`; this is not a claim of normal
public-install trust.

On a clean supported Mac, copy the app from the mounted DMG to Applications. If Gatekeeper
blocks the first launch, use Finder's **Open** action from the app's context menu and accept
the explicit warning. Do not bypass Gatekeeper for an artifact whose checksum or source is
not trusted. Developer ID signing, notarization, stapling, auto-update, and public download
hosting are out of scope for this ticket.

## Runtime data and secrets

- Application support and project state: `~/Library/Application Support/PortLog/`
- Rebuildable caches: `~/Library/Caches/PortLog/`
- Provider credentials and OAuth tokens: macOS Keychain only
- Local review backend: loopback `127.0.0.1:8000`, owned and supervised by the app
- Bundled resources: `Contents/Resources/ui` and `Contents/Resources/review-sidecar`

The app never treats the source checkout or the user's current working directory as a
packaged resource root. A failed launch must not leave a PortLog-owned sidecar behind; normal
quit sends termination to active workers and the sidecar before exiting.

## Verification

After building, run the release-stage tests and launch smoke test:

```bash
npm run desktop:verify
```

This checks the DMG/arm64 builder contract, staged UI/Python/Soufflé resources, provider
auth modules, the absence of a host Python/Node/Soufflé requirement in the launch
environment, and a real packaged `.app` launch to the Chat region. It writes representative
acceptance measurements to `frontend/release/acceptance-results.json` when the smoke test
completes.

The full clean-machine journey remains the release gate: launch, first-run diagnostics,
DEXPI import and preparation, supported BYOK login, grounded inspection and evidence
selection, deterministic verification, cancellation, quit, relaunch, and review reopen.
Run that journey on a clean non-admin macOS 14+ Apple Silicon account with no Homebrew,
Node, Python, or Soufflé installed before distributing the candidate.

Windows and Linux are intentionally not silently supported by this artifact.
