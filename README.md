# MQTT to PostgreSQL Pipeline — Backend API Service

Flask-based backend that ingests MQTT data, stores device configuration, and
exposes a REST API plus a web UI for managing traps.

## Implemented features

- **Flask app** with application factory, rotating file + console logging, and
  JSON error handlers.
- **MQTT monitoring** (paho-mqtt 2.x) — background, non-blocking client with
  auto-reconnect/backoff, resubscribe-on-connect, and console logging of every
  received message. Toggle with `MQTT_ENABLED`.
- **SQLite trap store** (SQLAlchemy) with a `traps` table created on startup.
- **REST CRUD API** at `/api/traps` (list/get/create/update/delete) with
  validation and proper status codes.
- **Web UI** at `/traps` (Jinja2 + Bootstrap) for full CRUD with search, sort,
  pagination, and notifications. Toggle with `ENABLE_FRONTEND`.
- **API key authentication** — `/api/*` endpoints require an `Authorization:
  Bearer <API_KEY>` header; the web UI has a `/login` page (key stored in
  `sessionStorage`). Toggle by setting/clearing `API_KEY`.

## Project structure

```
.
├── app/
│   ├── __init__.py            # app factory: logging, DB, blueprints, MQTT
│   ├── config.py              # env-based config
│   ├── auth.py                # API key auth decorator + helpers
│   ├── routes/
│   │   ├── api.py             # Hello World (/) + /api/auth/verify
│   │   ├── traps.py           # CRUD API (/api/traps)
│   │   └── frontend.py        # web UI routes (/traps, /login)
│   ├── models/
│   │   ├── database.py        # shared SQLAlchemy instance
│   │   └── trap.py            # Trap model
│   ├── services/
│   │   └── mqtt_service.py    # MQTT client + init_mqtt(app)
│   ├── templates/             # traps.html, login.html
│   └── static/css|js          # style.css, traps.js
├── data/                      # SQLite db (gitignored)
├── tests/mqtt_diag.py         # MQTT wildcard diagnostic tool
├── logs/                      # rotating logs (gitignored)
├── .env.example
├── requirements.txt
└── run.py
```

## Setup

A virtual environment already exists at `venv/`.

```bash
# Activate the venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# (Optional) create your .env from the example
cp .env.example .env
```

## Run

```bash
python run.py
```

The service starts on `http://localhost:5000` (configurable via `FLASK_PORT`).

```bash
curl http://localhost:5000/
# -> Hello World
```

## API documentation (OpenAPI)

An `openapi.yaml` specification is included in the project root covering all
19 endpoints, data models, and authentication. Import it into **Bruno**:

1. Open Bruno → *Collections* → *Import Collection*
2. Choose **OpenAPI v3** → select `openapi.yaml`
3. Set the collection-level auth header: `Authorization: Bearer <API_KEY>`

You can also browse it with any OpenAPI viewer (Swagger UI, Redoc, etc.).

## Configuration

Config is read from environment variables (see `.env.example`).

| Variable           | Default       | Description                                  |
| ------------------ | ------------- | -------------------------------------------- |
| `FLASK_ENV`        | `development` | Enables debug mode/reloader.                 |
| `FLASK_PORT`       | `5000`        | HTTP port.                                   |
| `LOG_LEVEL`        | `DEBUG`       | Logging verbosity.                           |
| `LOG_DIR`          | `logs`        | Rotating log file folder.                    |
| `ENABLE_FRONTEND`  | `true`        | Serve the `/traps` UI; `false` → 404.        |
| `API_KEY`          | — (unset)     | Secret for `/api/*` + UI login. Unset → auth disabled (warning logged). |
| `DATABASE_URL`     | `sqlite:///data/traps.db` | SQLAlchemy database URL.         |
| `MQTT_ENABLED`     | `true`        | Start the MQTT client.                       |
| `MQTT_BROKER_HOST` | `localhost`   | MQTT broker host.                            |
| `MQTT_BROKER_PORT` | `1883`        | MQTT broker port.                            |
| `MQTT_TOPICS`      | —             | Comma-separated topic filters.               |
| `MQTT_CLIENT_ID`   | auto          | Client id (generated if unset).              |
| `MQTT_USERNAME`    | —             | Optional broker username.                    |
| `MQTT_PASSWORD`    | —             | Optional broker password.                    |
| `MQTT_KEEPALIVE`   | `60`          | Keepalive seconds.                           |

## Trap configuration API (`/api/traps`)

Trap device configurations are stored in a file-based **SQLite** database
(`data/traps.db`, created automatically on startup). Override the location with
the `DATABASE_URL` environment variable.

> **Auth:** when `API_KEY` is set, every `/api/traps` request must include an
> `Authorization: Bearer <API_KEY>` header (see [Authentication](#authentication)).
> The examples below omit it for brevity.

> SQLite has no native `SERIAL` / `NUMERIC` / `TIMESTAMPTZ`. The ORM uses an
> autoincrement integer PK, `Decimal` temperatures, and UTC datetimes; the
> `updated_at` column is bumped automatically on every change.

### Data model (`traps` table)

| Field         | Type           | Constraints                       | Notes                                                  |
| ------------- | -------------- | --------------------------------- | ------------------------------------------------------ |
| `id`          | integer        | primary key, auto-increment       | Read-only; assigned by the database.                   |
| `status`      | string(20)     | **required**                      | e.g. `active`, `inactive`.                             |
| `trap_id`     | string(50)     | **required**, **unique**          | Business identifier; duplicates return `409`.          |
| `tracker_id`  | string(50)     | **required**                      | Associated tracker identifier.                         |
| `location`    | string(50)     | optional                          |                                                        |
| `door_status` | string(20)     | optional                          | e.g. `open`, `closed`; typically set by sensors.       |
| `temperature` | numeric(5,2)   | optional                          | Numeric; serialized as a JSON number.                  |
| `notes`       | string(255)    | optional                          | Free-text.                                             |
| `updated_by`  | string(50)     | defaults to `system`              | Who made the change (see below). Required on `PUT`.    |
| `created_at`  | datetime (UTC) | read-only                         | ISO-8601; set on creation.                             |
| `updated_at`  | datetime (UTC) | read-only, auto-updated           | ISO-8601; bumped on every change.                      |

**`updated_by` semantics:** this column records the source of a change — a
manual API call should pass the user making it (e.g. `"alice"`), while automated
sensor updates use the default `"system"`. Useful for auditing/debugging when
sensors update `door_status` or `location`.

### Endpoints

| Method | Path              | Description                                          |
| ------ | ----------------- | --------------------------------------------------- |
| GET    | `/api/traps`      | List traps. Query: `limit` (default 100), `offset` (default 0), `status` filter. |
| GET    | `/api/traps/<id>` | Get a single trap by numeric `id`.                  |
| POST   | `/api/traps`      | Create a trap. Requires `status`, `trap_id`, `tracker_id`. |
| PUT    | `/api/traps/<id>` | Update a trap. Requires `updated_by` in the body.   |
| DELETE | `/api/traps/<id>` | Delete a trap.                                       |

### Status codes

| Code  | Meaning                                                              |
| ----- | ------------------------------------------------------------------- |
| `200` | Success (GET, PUT, DELETE).                                          |
| `201` | Created (POST).                                                     |
| `400` | Bad request — missing required field, invalid type, non-integer `limit`/`offset`, or missing `updated_by` on update. |
| `404` | Trap not found.                                                     |
| `409` | Conflict — `trap_id` already exists.                                |
| `500` | Internal server error.                                              |

Error responses are JSON of the form `{"error": "<message>"}`.

### Validation rules

- `status`, `trap_id`, `tracker_id` are required on create (`400` if missing).
- `trap_id` must be unique (`409` on duplicate, on both create and update).
- `updated_by` is required on every update (`400` if missing/empty); on create it
  defaults to `system` when omitted.
- `temperature` must be numeric (`400` otherwise); string fields must not exceed
  their max length.
- `limit` and `offset` must be non-negative integers (`400` otherwise).

### Examples

**Create** — `POST /api/traps`

```bash
curl -X POST http://localhost:8080/api/traps -H 'Content-Type: application/json' \
  -d '{
    "status": "active",
    "trap_id": "TRAP-001",
    "tracker_id": "TRK-001",
    "location": "north",
    "temperature": 23.5,
    "updated_by": "alice"
  }'
```

Response `201 Created`:

```json
{
  "id": 1,
  "status": "active",
  "trap_id": "TRAP-001",
  "tracker_id": "TRK-001",
  "location": "north",
  "door_status": null,
  "temperature": 23.5,
  "notes": null,
  "updated_by": "alice",
  "created_at": "2026-06-24T08:39:06.316701",
  "updated_at": "2026-06-24T08:39:06.316705"
}
```

**List** (filter + paginate) — returns a JSON array:

```bash
curl 'http://localhost:8080/api/traps?status=active&limit=10&offset=0'
```

**Get one** — `GET /api/traps/1` (`200`, or `404` if absent):

```bash
curl http://localhost:8080/api/traps/1
```

**Update** — `PUT /api/traps/1` (`updated_by` required); `updated_at` is bumped
automatically:

```bash
curl -X PUT http://localhost:8080/api/traps/1 -H 'Content-Type: application/json' \
  -d '{"door_status": "open", "updated_by": "alice"}'
```

**Delete** — `DELETE /api/traps/1`:

```bash
curl -X DELETE http://localhost:8080/api/traps/1
# -> 200 {"message": "Trap 1 deleted"}
```

## Web UI (`/traps`)

A Jinja2 + Bootstrap single-page interface for managing traps, served at
`http://localhost:<port>/traps`. It calls the `/api/traps` endpoints via
`fetch()` and provides:

- A sortable table of all traps (click any column header to sort).
- **Add Trap** button and per-row **Edit**/**Delete** actions (delete asks for
  confirmation).
- Client-side **search** by Trap ID or Location, server-side **status** filter,
  and **pagination** (page-size selector + Prev/Next).
- Client-side required-field validation and toast notifications that surface
  API errors (e.g. duplicate `trap_id`, missing `updated_by`).

Disable it by setting `ENABLE_FRONTEND=false`, after which `/traps` returns
`404` while the JSON API at `/api/traps` keeps working.

> The UI loads Bootstrap 5 and Bootstrap Icons from a CDN, so the page needs
> internet access when first loaded.

## Authentication

API key authentication protects all `/api/*` endpoints. Set a secret in the
environment:

```
API_KEY=your-secret-key
```

If `API_KEY` is **unset**, authentication is disabled (the app logs a warning on
startup and runs normally, so the key can be added later).

**Calling the API** — include the key as a Bearer token:

```bash
curl http://localhost:8080/api/traps -H "Authorization: Bearer your-secret-key"
```

A missing or invalid key returns `401`:

```json
{ "error": "Invalid or missing API key" }
```

**Web UI login** — visiting `/traps` without a key in `sessionStorage` redirects
to `/login`. The login page verifies the key against `GET /api/auth/verify`,
stores it in `sessionStorage` (not persisted across browser sessions), and sends
it on every API call. Any `401` response clears the stored key and returns the
user to `/login`. A **Logout** button clears the key.

**Public (no auth required):** `/` (Hello World), `/login`, `/static/*`, and the
`/traps` HTML page (its data is protected at the API layer).

## Security

Configuration is loaded entirely from environment variables — no credentials are
hardcoded anywhere in the source.

**Environment setup**

- Copy the template and fill in your values: `cp .env.example .env`.
- **Never commit `.env`.** It is gitignored, along with `logs/` and `data/`
  (which can contain operational data such as device IDs, GPS coordinates, and
  raw payloads). After `git init`, run `git status` and confirm `.env`, `logs/`,
  and `data/` are **not** staged before your first commit.

**API key**

- Generate a strong key and set it as `API_KEY`:

  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

- If `API_KEY` is unset, authentication is **disabled** (a warning is logged) —
  always set it outside local development.

**Production hardening**

- Set `FLASK_ENV=production` to disable the debugger/reloader (avoids exposing
  stack traces and the interactive debugger).
- Do **not** run the Flask dev server in production. Use a WSGI server such as
  **gunicorn** behind a **TLS-terminating reverse proxy**; bind to localhost/the
  proxy rather than `0.0.0.0` when publicly exposed.
- Use **MQTT over TLS** (port 8883) and database TLS where supported; keep all
  broker/DB credentials in environment variables only.

**Recommended (not yet implemented)**

- Rate limiting on `/api/*`, especially `/api/auth/verify`, to deter API-key
  brute forcing (e.g. `flask-limiter`).
- Security headers (e.g. `flask-talisman` or at the proxy) and scoped CORS only
  if a cross-origin client (e.g. Grafana) needs API access.
- Run a dependency vulnerability scan before each release: `pip-audit`.

## Docker deployment

A multi-stage `Dockerfile`, `uwsgi.ini`, and `docker-compose.yml` are included
for production-style deployment.

**Quick start**

```bash
# Ensure a .env file exists (copy from the example if you haven't already)
cp .env.example .env    # then edit with your broker, API key, etc.

docker-compose build
docker-compose up -d
```

The app is available at `http://localhost:${FLASK_PORT:-5000}`. The SQLite
database file (`data/traps.db`) is mounted as a volume and survives restarts.

**Other commands**

```bash
docker-compose logs -f          # follow logs
docker-compose down             # stop
docker-compose up -d --build    # rebuild and restart
```

**What's inside**

| Layer    | Detail                                                |
| -------- | ----------------------------------------------------- |
| Base     | `python:3.11-slim`                                    |
| Server   | **uWSGI** (compiled in a builder stage → slim runtime)|
| User     | `appuser` (non-root)                                  |
| Config   | `.env` via `env_file` + `environment` overrides        |
| Health   | `curl /api/health` every 30 s                         |
| Workers  | `UWSGI_PROCESSES` (default 2) × `UWSGI_THREADS` (2)   |
| Port     | `FLASK_PORT` (default 5000)                            |

**Production notes**

- `FLASK_ENV` is set to `production` → debug/reloader are **off**.
- Set a strong `API_KEY` and real MQTT broker details in your `.env`.
- The `.env` file must contain at least the variables listed in
  [Configuration](#configuration) — the app will warn but start gracefully for
  optional values (e.g. missing MQTT broker).

## Roadmap

- **Done:** Flask scaffolding, MQTT monitoring, SQLite trap CRUD API, web UI,
  API key authentication.
- **Next:** PostgreSQL storage, data-processing layer, Grafana metrics endpoints.

## Troubleshooting: wildcard subscriptions

**Symptom:** the broker ACKs the subscription (granted QoS 0) but no messages
ever arrive on a `+` wildcard topic.

**Cause:** `+` matches *exactly one* topic level, and an MQTT topic filter must
have the **same number of levels** as the published topic. A filter that is one
level too short silently matches nothing — the SUBACK only confirms the filter
was accepted, not that anything matches it.

**Example (ChirpStack v4):** devices publish to

```
application/<app-id>/device/<devEUI>/event/<type>   e.g. .../event/up, /event/log, /event/txack
```

so subscribing to `application/<app-id>/device/+/event` (ending at `event`)
matches **nothing**. The correct filters are:

| Filter                                     | Matches                          |
| ------------------------------------------ | -------------------------------- |
| `application/<id>/device/+/event/+`        | all event types, all devices     |
| `application/<id>/device/+/event/up`       | uplinks only                     |
| `application/<id>/device/#`                | everything under each device     |

**Diagnose:** run the bundled tool, which subscribes to the broken, fixed, and
multi-level patterns at once and reports per-pattern message counts:

```bash
venv/bin/python tests/mqtt_diag.py 30
```

The MQTT service also logs SUBACK granted codes (rejections are flagged as
errors), per-message QoS/retain, and paho's raw protocol packets at DEBUG level
for full message-flow visibility.
