# InfraOS — Palo Alto Module

Device management, live connectivity/discovery, configuration visibility with
version history, and a metrics/health dashboard for Palo Alto firewalls.
Single-user, no auth/multi-tenancy in this pass (per scope agreed for this
build) — see the architecture doc from the earlier planning pass for how
Identity/RBAC/multi-tenancy layers on top later without disrupting this.

## Quick start

```bash
cp .env.example .env
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# paste into .env as CREDENTIALS_ENCRYPTION_KEY

python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# paste into .env as JWT_SECRET_KEY

docker compose up --build
```

First login: username `admin`, password whatever you set (or left as default) in `BOOTSTRAP_ADMIN_PASSWORD` in `.env` — change it immediately via a real user-management flow in any deployment that matters.

- Frontend dashboard: http://localhost:2020
- Backend API + docs: http://localhost:2010/docs
- Postgres: localhost:2001 (user/pass `infraos`/`infraos`, db `infraos`)
- Redis: localhost:2002

First run: open the dashboard, click **+ Add Firewall**, enter your PAN-OS
management IP/host, port (443 by default), and API credentials. Then use
**Test Connection** → **Discover** → **Collect Config** → **Collect Metrics**
to populate everything. After that, metrics and (periodically) config drift
checks happen automatically via the background poller — no need to keep
clicking those buttons.

## What this is (and isn't)

**Included:**
- Device CRUD with credentials routed through a pluggable secrets backend (Fernet by default; Vault optional — see caveat below)
- Connectivity test + discovery (model, serial, PAN-OS version, HA state, licenses)
- Configuration collection with version history, diff summaries (added/removed/changed), and drift flags — shown as a commit-log-style history in the UI
- Objects and security policy tables per collected version
- **Config push/commit approval workflow**: draft → validate → pending_approval → approved → pushed → committed, with RBAC (viewer/operator/admin) and a four-eyes rule (the approver cannot be the same user who requested the change) enforced server-side, not just in the UI
- **Auth**: JWT login, bcrypt password hashing, a bootstrapped default admin on first startup
- **Topology graph**: built from the actual latest collected config (device→interface→zone→policy→object edges), rendered as an interactive d3-force graph (drag, zoom, color-coded)
- **Log Analytics**: collect traffic/threat/system logs via the plugin, search/filter them, and correlate traffic logs against actual policy names to answer "which policy matched this traffic" deterministically
- **Best Practice Analyzer**: flags any-any allow rules, unused objects, duplicate policies, expired licenses, and outdated PAN-OS versions, with a computed security score
- **Reports**: executive/technical/security reports as real generated PDFs (via reportlab) or JSON
- **Two vendor plugins**: Palo Alto and Fortinet, both passing the same plugin contract test suite — this is the real proof the plugin architecture holds up, including across a vendor (FortiOS) whose config model is fundamentally different from Palo Alto's (immediate-apply vs. candidate/commit)
- **Alembic migrations**: schema is now managed as real migrations, applied automatically on startup — no more ad hoc `create_all()`
- Metrics (CPU, memory, active sessions, per-interface drops) with threshold-based health events, charted in the dashboard
- A background poller collecting metrics every 30s and checking config drift every ~10th cycle, for every registered device, automatically

**Deliberately not in this pass** (flagged, not forgotten):
- **AI Assistant** — explicitly skipped this round. The RAG grounding pattern the rest of this build already supports (log correlation, best-practice findings, impact analysis are all deterministic lookups an AI layer could cite from) but the actual LLM integration needs Ollama running somewhere with model weights pulled, which this sandbox can't do.
- Multi-tenancy (multiple orgs) — single-tenant RBAC only, per earlier scoping
- Real-time log ingestion (syslog) — log polling exists at the plugin level but isn't event-driven
- A UI for the Knowledge Graph beyond the current topology view (no Neo4j — see architecture doc for when that swap is warranted)

**Important caveat on the Vault secrets backend:** it was built and unit-tested against a *mocked* hvac client — there was no real Vault server available in this sandbox to test against. The interface and the default Fernet backend are both verified end-to-end against a real database; the Vault backend's actual network behavior against a real Vault server has **not** been verified. Smoke-test it (a `docker compose up` with the commented-out Vault dev service in `docker-compose.yml` is a reasonable way to do that) before trusting it with real credentials.

**Important caveat on the Fortinet plugin's `commit()` and `rollback()`:** FortiOS applies config changes immediately on push — there's no candidate/commit staging like Palo Alto. `commit()` is a documented no-op for this vendor (push already applied the change), and `rollback()` honestly reports "not implemented" rather than guessing at FortiOS's config-revision API shape. Both are called out loudly in the plugin's module docstring, not buried.

## Architecture notes specific to this build

- **Credentials**: routed through a `SecretsBackend` interface (`app/core/secrets_backend.py`). Fernet (encrypted blob in Postgres) is the default; Vault (KV v2, plaintext never touches Postgres) is opt-in via `SECRETS_BACKEND=vault`. See the caveat above.
- **Config drift**: every new collected version that differs from the last is flagged `is_drift: true`. The platform doesn't yet distinguish "we changed this on purpose via the approval workflow" from "someone changed it directly on the device" — that link (change requests ↔ drift detection) is a natural next connection to make.
- **Digital Twin caching**: Redis with a short TTL (default 20s), invalidated on any write. Cache hits are visible in the API response (`cache_hit: true/false`).
- **Migrations**: `alembic/` is the source of truth for schema now. On startup, the app runs `alembic upgrade head` programmatically against `DATABASE_URL` — no separate migration step needed for `docker compose up`. Generate new migrations the normal way: `alembic revision --autogenerate -m "description"` after changing a model in `app/models/`.

## Repo layout

```
backend/
  app/
    core/        settings, credential encryption, secrets backend, auth (JWT/RBAC), plugin registry
    db/          async SQLAlchemy session, Redis client
    models/      SQLAlchemy entities (devices, config versions, change requests, users, logs)
    schemas/     Pydantic request/response models
    services/    device, connectivity, config, monitoring, twin, poller, config_change, topology,
                 log, best-practice analyzer, report, auth
    routers/     FastAPI routers (one per service area, all behind auth except /auth/login)
    plugins/     the vendor plugin contract + Palo Alto and Fortinet implementations
  alembic/       schema migrations — source of truth, applied automatically on startup
  tests/         plugin contract tests (run against BOTH vendor plugins) + unit tests, 42 passing,
                 no live firewall or Vault server needed
frontend/
  src/
    api/         typed API client (attaches bearer token, handles 401 → redirect to login)
    auth/        auth context + token storage
    components/  StatusPulse, ConfigVersionLog, MetricChart, TopologyGraphView, LogsPanel,
                 BestPracticePanel, ChangesPanel, etc.
    pages/       LoginPage, DeviceListPage, DeviceDetailPage (tabs: overview, configuration,
                 objects, policies, topology, logs, security, changes)
docker-compose.yml
```

## Verifying it works without a real firewall

Every piece of this was tested end-to-end against a fake PAN-OS device (a
small FastAPI app replaying the same fixture responses used in the plugin's
own unit tests, served over real self-signed TLS) — not just unit-tested in
isolation. That process caught one real bug (a dead code path was silently
dropping the CPU metric), which is now fixed with a regression test in the
plugin suite. If you want to reproduce that kind of test yourself before
pointing this at a real device, the fixture bodies are in
`backend/tests/fixtures/paloalto/`.
