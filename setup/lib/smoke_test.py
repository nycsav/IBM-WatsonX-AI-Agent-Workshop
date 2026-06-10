#!/usr/bin/env python3
"""
smoke_test.py — attendee-side connectivity check.

Reads .env from the repo root (the file connect-workshop.sh just wrote)
and runs two probes:

    1. Cassandra: TLS connect + SELECT COUNT(*) FROM <your keyspace>.customers
       Verifies the slip password works against Cassandra AND that your
       per-user GRANTs are in place (you can read your own keyspace).

    2. watsonx.data Presto: mint Bearer token from Software Hub +
       SHOW SCHEMAS FROM iceberg_data.
       Verifies the same slip password works against Software Hub auth
       AND that the Presto HTTP API is reachable end-to-end.

Both must pass. On failure, prints which probe failed and a one-line
hint at what to check.

Reads WORKSHOP_PASSWORD from the environment (connect-workshop.sh sets
it before invoking) rather than from .env, so the .env file can be
committed-by-mistake without leaking the password to git history.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV_FILE.is_file():
        print(f"[FAIL] {ENV_FILE} does not exist. Run connect-workshop.sh first.")
        sys.exit(1)
    for raw in ENV_FILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def probe_cassandra(env: dict[str, str], password: str) -> bool:
    print("→ Cassandra (TLS + SELECT)…", end=" ", flush=True)
    try:
        from cassandra.cluster import Cluster
        from cassandra.auth import PlainTextAuthProvider
        from cassandra.connection import DefaultEndPoint, EndPointFactory
    except ImportError:
        print("FAIL\n   cassandra-driver not installed (re-run connect-workshop.sh).")
        return False

    class _RouteEndPointFactory(EndPointFactory):
        """Every Cassandra node sits behind one TLS-passthrough route. The
        driver discovers the other nodes via system.peers and, by default,
        builds an endpoint per node from that node's *reported* address (an
        internal 10.x pod IP) and its native port (9042) — neither reachable
        from outside the cluster. The driver then burns a full connect_timeout
        dialing each unreachable endpoint before the session settles: a
        guaranteed ~15s stall per connect, minutes on a lossy link. Collapsing
        every discovered node to the single route endpoint (host:443) keeps the
        driver on the one reachable address *and* port. Contact points bypass
        the factory, so the initial connect is unaffected.

        An AddressTranslator alone is not enough here: it rewrites the address
        but leaves the node's reported native port (9042) intact, so the driver
        still stalls dialing the route host on a port it doesn't expose."""

        def __init__(self, route_host: str, route_port: int) -> None:
            self._route_host = route_host
            self._route_port = route_port

        def create(self, row):  # noqa: ANN001 - driver-defined signature
            return DefaultEndPoint(self._route_host, self._route_port)

        def create_from_sni(self, sni):  # noqa: ANN001 - driver-defined signature
            return DefaultEndPoint(self._route_host, self._route_port)

    host = env["CASSANDRA_HOST"]
    port = int(env["CASSANDRA_PORT"])
    user = env["WORKSHOP_USER"]
    suffix = env["WORKSHOP_SCHEMA_SUFFIX"]
    # One probe per domain so a silently partial provision (#101) doesn't
    # slip past the smoke. Each (keyspace, table) pair is small + always
    # populated by load-sample-data.sh; COUNT works even if rows=0 because
    # what we actually validate is "keyspace exists + GRANT in place."
    domain_probes = [
        ("ecommerce", f"ecommerce_{suffix}", "customers"),
        ("iot",       f"iot_{suffix}",       "device_state_current"),
        ("financial", f"financial_{suffix}", "accounts"),
    ]

    # cassandra-driver IP-vs-hostname workaround: it resolves the contact
    # point to an IP before TLS, then validates the cert against the IP.
    # Disable hostname matching but keep CA-chain validation; pass the
    # original hostname via ssl_options for SNI.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False

    def _connect_with_retry():
        """Build the cluster + open the session, retrying transient connect
        failures. Lossy networks (conference/hotel/airline wifi) occasionally
        drop the initial TLS connect to the route; a couple of quick retries
        turn a one-off OperationTimedOut into a clean connect instead of a
        failed smoke. Auth/permission errors are not retried — they won't fix
        themselves and the caller's classifier should report them verbatim."""
        last_exc = None
        for attempt in range(3):
            cl = Cluster(
                contact_points=[host], port=port,
                ssl_context=ctx,
                ssl_options={"server_hostname": host},
                auth_provider=PlainTextAuthProvider(user, password),
                endpoint_factory=_RouteEndPointFactory(host, port),
                connect_timeout=15,
            )
            try:
                # Auth once via the first domain's keyspace (no_keyspace works
                # too but using a real keyspace doubles as a connection check).
                return cl, cl.connect(domain_probes[0][1])
            except Exception as exc:
                try: cl.shutdown()
                except Exception: pass
                last_exc = exc
                m = str(exc)
                if any(s in m for s in ("AuthenticationFailed", "Bad credentials",
                                        "Unauthorized", "no SELECT")):
                    raise
                if attempt < 2:
                    time.sleep(2)
        raise last_exc

    cluster = None
    try:
        cluster, session = _connect_with_retry()
        results = []
        for domain, ks, tbl in domain_probes:
            try:
                row = session.execute(f"SELECT COUNT(*) FROM {ks}.{tbl}").one()
                results.append((domain, ks, tbl, int(row[0]), None))
            except Exception as inner:
                results.append((domain, ks, tbl, None, str(inner)))
        failed = [r for r in results if r[4] is not None]
        if failed:
            print("FAIL")
            for domain, ks, tbl, _, err in failed:
                if "no SELECT permission" in err or ("Unauthorized" in err and "permission" in err.lower()):
                    print(f"   [{domain}] no SELECT on {ks}.{tbl} — ask operator to re-run provision-schemas.sh for {user}")
                elif "keyspace" in err.lower() and ("does not exist" in err.lower() or "not found" in err.lower()):
                    print(f"   [{domain}] keyspace {ks} missing — ask operator to run provision-schemas.sh for {user}")
                elif "does not exist" in err.lower() or "unconfigured table" in err.lower():
                    print(f"   [{domain}] table {ks}.{tbl} missing — ask operator to run load-sample-data.sh for {user}")
                else:
                    print(f"   [{domain}] {err[:200]}")
            return False
        details = ", ".join(f"{ks}.{tbl}={n}" for _, ks, tbl, n, _ in results)
        print(f"OK ({details})")
        return True
    except Exception as e:
        msg = str(e)
        print("FAIL")
        # cassandra-driver wraps the real error; the substring distinguishes
        # bad-password from missing-grants. AuthenticationFailed = pw wrong;
        # Unauthorized (in NoHostAvailable wrapper) usually = grants missing.
        if "AuthenticationFailed" in msg or "Bad credentials" in msg:
            print("   Password rejected. Re-check your slip.")
        elif "no SELECT permission" in msg or ("Unauthorized" in msg and "permission" in msg.lower()):
            print(f"   Logged in but no SELECT on ecommerce_{suffix} — ask operator to re-run provision-schemas.sh")
        elif "keyspace" in msg.lower() and ("does not exist" in msg.lower() or "not found" in msg.lower()):
            print(f"   Keyspace ecommerce_{suffix} not found — ask operator to run provision-schemas.sh for {user}")
        else:
            print(f"   {msg[:300]}")
        return False
    finally:
        if cluster is not None:
            try: cluster.shutdown()
            except Exception: pass


def probe_presto(env: dict[str, str], password: str) -> bool:
    print("→ watsonx.data Presto (Bearer + SHOW SCHEMAS)…", end=" ", flush=True)
    wxd_host = env["WXD_HOST"]
    presto_host = env["PRESTO_HOST"]
    user = env["WORKSHOP_USER"]

    ctx = ssl.create_default_context()
    # TechZone cluster routes use a publicly-trusted LE wildcard cert,
    # so default verification works. If the operator is using a private
    # cert authority later, set CASSANDRA_USE_SSL handling here.

    # 1. Mint Bearer token from Software Hub.
    try:
        req = urllib.request.Request(
            f"https://{wxd_host}/icp4d-api/v1/authorize",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"username": user, "password": password}).encode(),
        )
        with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
            body = json.loads(r.read())
        token = body.get("token")
        if not token:
            print("FAIL\n   /icp4d-api/v1/authorize returned no token.")
            return False
    except urllib.error.HTTPError as e:
        print("FAIL")
        if e.code == 401:
            print("   Authentication rejected. Re-check the password on your slip.")
        else:
            print(f"   HTTP {e.code} from Software Hub auth ({wxd_host})")
        return False
    except Exception as e:
        print(f"FAIL\n   Could not reach Software Hub at {wxd_host}: {e}")
        return False

    # 2. POST SHOW SCHEMAS to Presto with the Bearer token + poll once.
    try:
        req = urllib.request.Request(
            f"https://{presto_host}/v1/statement",
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Presto-User": user,
                "Content-Type": "text/plain",
            },
            data=b"SHOW SCHEMAS FROM iceberg_data",
        )
        with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
            resp = json.loads(r.read())
        next_uri = resp.get("nextUri")
        schemas: list[str] = []
        # Poll up to 30 pages — SHOW SCHEMAS is tiny, completes immediately.
        for _ in range(30):
            if not next_uri:
                break
            with urllib.request.urlopen(
                urllib.request.Request(
                    next_uri,
                    headers={"Authorization": f"Bearer {token}",
                             "X-Presto-User": user},
                ),
                context=ctx, timeout=30,
            ) as r:
                resp = json.loads(r.read())
            for row in resp.get("data") or []:
                schemas.append(row[0])
            if resp.get("stats", {}).get("state") == "FAILED":
                print(f"FAIL\n   Presto query failed: {resp.get('error', {}).get('message', '')[:200]}")
                return False
            next_uri = resp.get("nextUri")

        # #101: validate all three per-domain Iceberg schemas, not just ecommerce.
        suffix = env["WORKSHOP_SCHEMA_SUFFIX"]
        expected = [f"{d}_{suffix}" for d in ("ecommerce", "iot", "financial")]
        missing = [s for s in expected if s not in schemas]
        if not missing:
            print(f"OK (your schemas visible: {', '.join(expected)})")
            return True
        # Some/all missing — still a success for the smoke (Presto/auth work),
        # but flag specifically which domain so the operator can fix.
        print(f"OK with caveat — missing in iceberg_data: {', '.join(missing)}")
        print(f"   Ask operator to run provision-schemas.sh for your user.")
        return True
    except urllib.error.HTTPError as e:
        print(f"FAIL\n   HTTP {e.code} from Presto ({presto_host})")
        return False
    except Exception as e:
        print(f"FAIL\n   Could not query Presto at {presto_host}: {e}")
        return False


def main() -> int:
    env = load_env()
    password = os.environ.get("WORKSHOP_PASSWORD")
    if not password:
        # Fallback: from .env (mostly for re-running by hand).
        password = env.get("WORKSHOP_PASSWORD")
    if not password:
        print("[FAIL] WORKSHOP_PASSWORD not set (env or .env).")
        return 1

    required = ["WXD_HOST", "PRESTO_HOST", "CASSANDRA_HOST", "CASSANDRA_PORT",
                "WORKSHOP_USER", "WORKSHOP_SCHEMA_SUFFIX"]
    missing = [k for k in required if not env.get(k)]
    if missing:
        print(f"[FAIL] Missing in .env: {missing}")
        return 1

    cass_ok = probe_cassandra(env, password)
    presto_ok = probe_presto(env, password)
    return 0 if (cass_ok and presto_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
