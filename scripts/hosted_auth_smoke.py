"""Live proof that hosted sign-in isolates two users, end to end.

Starts the real Next app and the real Python backend, signs two users up
through the actual endpoints, and checks what each of them can see. This is
the acceptance evidence for bead pydexpi-datalog-1-2afe.6 (ADR 0016), kept
runnable rather than described: the claim it makes -- that one user cannot
reach another user's work -- is worth re-checking rather than trusting.

Not part of pytest, because it binds ports and needs a production Next build.
Run it by hand after changing anything on the auth path:

    cd frontend && npm run build && cd ..
    HARBORFIELD_DEPLOYMENT_PROFILE=hosted BETTER_AUTH_SECRET=... \
      BETTER_AUTH_URL=http://localhost:3100 HARBORFIELD_AUTH_DB=/tmp/e2e-auth.sqlite3 \
      node frontend/scripts/migrate-auth.mjs
    .venv/bin/python scripts/hosted_auth_smoke.py
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO = Path("/Users/vikramoddiraju/LogicProgramming/pydexpi-datalog-1")
FRONTEND = REPO / "frontend"
NEXT = "http://localhost:3100"
API = "http://127.0.0.1:8100"
FIXTURE = (
    REPO
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)

common = {
    "HARBORFIELD_DEPLOYMENT_PROFILE": "hosted",
    "BETTER_AUTH_SECRET": "e2e-secret-0123456789abcdefghij",
    "BETTER_AUTH_URL": NEXT,
    "HARBORFIELD_AUTH_DB": "/tmp/e2e-auth.sqlite3",
}

backend_env = {
    **os.environ,
    **common,
    "HARBORFIELD_QA_PROVIDER": "scripted",
    "PYTHONPATH": str(REPO),
    "HARBORFIELD_REVIEW_ARTIFACT_ROOT": "/tmp/e2e-artifacts",
    "HARBORFIELD_OIDC_ISSUER": NEXT,
    "HARBORFIELD_OIDC_AUDIENCE": NEXT,
    "HARBORFIELD_OIDC_JWKS_URL": f"{NEXT}/api/auth/jwks",
}
next_env = {**os.environ, **common, "HARBORFIELD_REVIEW_API_URL": API, "PORT": "3100"}

procs: list[subprocess.Popen] = []


def start(cmd: list[str], cwd: Path, env: dict, log: str) -> None:
    handle = open(log, "w")
    procs.append(
        subprocess.Popen(cmd, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT,
                         start_new_session=True)
    )


def wait_for(url: str, label: str, timeout: float = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            httpx.get(url, timeout=3)
            print(f"  {label} up")
            return
        except Exception:
            time.sleep(1)
    raise SystemExit(f"{label} did not start; see logs")


def stop() -> None:
    for p in procs:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except Exception:
            pass


def signup(email: str) -> httpx.Client:
    client = httpx.Client(
        base_url=NEXT, timeout=60, follow_redirects=True,
        # Browsers always send Origin; Better Auth requires it on state-changing
        # calls as CSRF protection. Omitting it made an earlier run look like a
        # sign-out bug when it was the guard doing its job.
        headers={"Origin": NEXT},
    )
    r = client.post(
        "/api/auth/sign-up/email",
        json={"email": email, "password": "correct-horse-battery-staple", "name": email},
    )
    assert r.status_code in (200, 201), f"sign-up {email}: {r.status_code} {r.text[:300]}"
    assert client.cookies, f"no session cookie for {email}"
    return client


def main() -> int:
    print("starting servers...")
    start(["npm", "start", "--", "--port", "3100"], FRONTEND, next_env, "/tmp/e2e-next.log")
    start(
        [str(REPO / ".venv/bin/python"), "-m", "uvicorn",
         "pydexpi_datalog.web.asgi:app", "--host", "127.0.0.1", "--port", "8100"],
        REPO, backend_env, "/tmp/e2e-api.log",
    )
    wait_for(f"{NEXT}/sign-in", "next")
    wait_for(f"{API}/docs", "backend")

    print("\n1. anonymous request to the backend")
    anon = httpx.get(f"{API}/api/review/sessions", timeout=30)
    print(f"   direct backend, no token -> {anon.status_code} (want 401)")
    assert anon.status_code == 401, anon.text

    print("\n2. two users sign up through the real UI endpoints")
    alice, bob = signup("alice@example.com"), signup("bob@example.com")
    print("   alice and bob signed in")

    print("\n3. alice prepares a review session through Next")
    prepared = alice.post(
        "/api/review/sessions/alice-e2e/prepare",
        json={"filename": "E06.xml", "content": FIXTURE.read_text(encoding="utf-8")},
        timeout=180,
    )
    print(f"   prepare -> {prepared.status_code}")
    assert prepared.status_code == 200, prepared.text[:400]

    print("\n4. what each caller can see")
    results = {}
    for name, client in (("alice", alice), ("bob", bob)):
        listed = client.get("/api/review/sessions", timeout=60)
        ids = [s["session_id"] for s in listed.json().get("sessions", [])]
        results[name] = ids
        print(f"   {name:<6} -> {listed.status_code} {ids}")

    anon_client = httpx.Client(base_url=NEXT, timeout=60)
    anon_listed = anon_client.get("/api/review/sessions")
    print(f"   anon   -> {anon_listed.status_code} {anon_listed.text[:80]}")

    print("\n5. alice signs out")
    signed_out = alice.post("/api/auth/sign-out", json={})
    after_out = alice.get("/api/review/sessions", timeout=60)
    print(f"   sign-out -> {signed_out.status_code}; then list -> {after_out.status_code}")

    print("\n6. alice signs back in (not signs up)")
    again = httpx.Client(base_url=NEXT, timeout=60, follow_redirects=True,
                         headers={"Origin": NEXT})
    signed_in = again.post(
        "/api/auth/sign-in/email",
        json={"email": "alice@example.com", "password": "correct-horse-battery-staple"},
    )
    relisted = again.get("/api/review/sessions", timeout=60)
    back = [s["session_id"] for s in relisted.json().get("sessions", [])]
    print(f"   sign-in -> {signed_in.status_code}; list -> {relisted.status_code} {back}")

    print("\n7. verdict")
    ok = True
    if results["alice"] != ["alice-e2e"]:
        print("   FAIL alice cannot see her own session")
        ok = False
    else:
        print("   OK   alice sees her own session")
    if results["bob"] != []:
        print("   FAIL bob can see alice's session")
        ok = False
    else:
        print("   OK   bob sees nothing of alice's")
    if anon_listed.status_code == 200 and anon_listed.json().get("sessions"):
        print("   FAIL anonymous caller saw sessions")
        ok = False
    else:
        print("   OK   anonymous caller sees nothing")
    if after_out.status_code != 401:
        print(f"   FAIL signed-out session still served ({after_out.status_code})")
        ok = False
    else:
        print("   OK   signing out revokes access immediately")
    if back != ["alice-e2e"]:
        print(f"   FAIL sign-in did not restore alice's work: {back}")
        ok = False
    else:
        print("   OK   signing back in restores her own work, and only hers")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        stop()
