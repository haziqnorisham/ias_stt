# Trap Management Service — Backend API Service

Flask-based backend that ingests device telemetry (pushed by the ChirpStack
HTTP integration), stores device configuration, and exposes a REST API plus a
web UI for managing traps.

## Implemented features

- **Flask app** with application factory, rotating file + console logging, and
  JSON error handlers.
- **HTTP telemetry ingest** at `POST /api/telemetry/ingest` — receives decoded
  GPS tracker payloads from ChirpStack's HTTP integration and runs the shared
  processing pipeline (tracker update, geofence + deployment logic).
- **Tracker uplink history** — every valid uplink from a registered tracker is
  persisted with parsed telemetry fields and the original decoded JSON payload;
  view it through `/api/uplinks` or the `/uplinks` UI page.
- **MQTT monitoring** (paho-mqtt 2.x, optional, off by default) — background,
  non-blocking client with auto-reconnect/backoff, resubscribe-on-connect, and
  console logging of every received message. Toggle with `MQTT_ENABLED`.
- **SQLite trap store** (SQLAlchemy) with a `traps` table created on startup.
- **REST CRUD API** at `/api/traps` (list/get/create/update/delete) with
  validation and proper status codes.
- **Deployment action history** with administrator-managed action types and
  immutable, picture-backed actions recorded against active deployments.
- **Web UI** at `/traps` (Jinja2 + Bootstrap) for full CRUD with search, sort,
  pagination, and notifications. Toggle with `ENABLE_FRONTEND`.
- **JWT authentication** — local users authenticate through `/auth/login`, then
  call protected endpoints with a short-lived JWT access token. A seven-day
  refresh token is used to obtain new access tokens.
- **Legacy service authentication** — `API_KEY` remains available for service
  integrations such as telemetry ingestion and can be scoped with
  `API_KEY_PERMISSIONS`.
- **Cross-origin API access** — CORS remains enabled for all origins and supports
  bearer-token requests through the `Authorization` header.

## Project structure

```
.
├── app/
│   ├── __init__.py            # app factory: logging, DB, blueprints, MQTT
│   ├── config.py              # env-based config
│   ├── auth.py                # JWT auth, permissions, and service-key helpers
│   ├── routes/
│   │   ├── auth.py             # JWT login, refresh, me, and logout
│   │   ├── api.py             # Hello World (/) + /api/auth/verify
│   │   ├── traps.py           # CRUD API (/api/traps)
│   │   ├── deployments.py     # Deployment and location APIs
│   │   ├── deployment_actions.py # Action type and action APIs
│   │   ├── users.py           # Administrator-only local-user CRUD API
│   │   ├── uplinks.py         # Uplink history API (/api/uplinks)
│   │   └── frontend.py        # legacy web UI routes (/traps, /login)
│   ├── models/
│   │   ├── database.py        # shared SQLAlchemy instance
│   │   ├── trap.py            # Trap model
│   │   ├── deployment.py       # Deployment model
│   │   ├── deployment_action.py # Immutable deployment action model
│   │   ├── deployment_action_type.py # Action type model and seeds
│   │   ├── user.py            # Local JWT user model
│   │   └── tracker_uplink.py  # Persisted tracker uplink history
│   ├── services/
│   │   ├── deployment_action_service.py # Action picture storage helpers
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

An `openapi.yaml` specification is included in the project root covering the
API endpoints, data models, and authentication. Import it into **Bruno**:

1. Open Bruno → *Collections* → *Import Collection*
2. Choose **OpenAPI v3** → select `openapi.yaml`
3. Set the collection-level auth header: `Authorization: Bearer <ACCESS_TOKEN>`

You can also browse it with any OpenAPI viewer (Swagger UI, Redoc, etc.).

## Configuration

Config is read from environment variables (see `.env.example`).

| Variable           | Default       | Description                                  |
| ------------------ | ------------- | -------------------------------------------- |
| `FLASK_ENV`        | `development` | Enables debug mode/reloader.                 |
| `FLASK_PORT`       | `5000`        | HTTP port.                                   |
| `LOG_LEVEL`        | `DEBUG`       | Logging verbosity.                           |
| `LOG_DIR`          | `logs`        | Rotating log file folder.                    |
| `APP_TIMEZONE`     | `Asia/Kuala_Lumpur` | Timezone for API timestamps, UI dates, and application logs. |
| `ENABLE_FRONTEND`  | `true`        | Serve the `/traps` UI; `false` → 404.        |
| `API_KEY`          | — (unset)     | Optional legacy service key for integrations. |
| `API_KEY_PERMISSIONS` | `*`        | Comma-separated permissions for the legacy service key. |
| `JWT_SECRET_KEY`   | —             | Stable signing secret; required in production. |
| `JWT_ACCESS_TOKEN_MINUTES` | `15`    | Access-token lifetime. |
| `JWT_REFRESH_TOKEN_DAYS` | `7`       | Refresh-token lifetime. |
| `DATABASE_URL`     | `sqlite:///data/traps.db` | SQLAlchemy database URL.         |
| `MQTT_ENABLED`     | `false`       | Start the MQTT client (optional; HTTP ingest is the default). |
| `MQTT_BROKER_HOST` | `localhost`   | MQTT broker host.                            |
| `MQTT_BROKER_PORT` | `1883`        | MQTT broker port.                            |
| `MQTT_TOPICS`      | —             | Comma-separated topic filters.               |
| `MQTT_CLIENT_ID`   | auto          | Client id (generated if unset).              |
| `MQTT_USERNAME`    | —             | Optional broker username.                    |
| `MQTT_PASSWORD`    | —             | Optional broker password.                    |
| `MQTT_KEEPALIVE`   | `60`          | Keepalive seconds.                           |

## Time handling

The application stores timestamps in UTC and converts them to `APP_TIMEZONE`
when serializing API responses, rendering frontend dates, and writing
application logs. The default is `Asia/Kuala_Lumpur`, which is UTC+8.

Set another IANA timezone in `.env` if needed, for example:

```dotenv
APP_TIMEZONE=Asia/Singapore
```

Restart the application after changing the setting. Existing database records
are not rewritten; they remain UTC and are converted using the current setting
when returned or displayed. Docker containers also receive the same timezone
through `TZ`. For a non-Docker deployment, the host operating-system timezone
can be aligned separately with `sudo timedatectl set-timezone Asia/Kuala_Lumpur`.

## Telemetry ingestion (`POST /api/telemetry/ingest`)

Decoded GPS tracker payloads are pushed to this endpoint by **ChirpStack's HTTP
integration**. The body must be the standard ChirpStack JSON envelope
(`deviceInfo` + `object`); processing is identical to the (optional) MQTT path:

1. `deviceInfo.devEui` is looked up in `smart_trap_tracker`; **unknown devices
   are silently ignored** and the endpoint still returns `200` (matching the
   former MQTT behaviour).
2. `object.latitude` / `object.longitude` / `object.position` / `object.battery`
   are persisted to the tracker row. A finite numeric `object.temperature`
   updates the latest tracker temperature in °C; uplinks without a valid
   temperature leave the previous reading intact.
3. The geofence check and deployment/trap-status logic run when coordinates
   are present.

> **Auth:** when `API_KEY` is set, the request must include
> `Authorization: Bearer <API_KEY>` — the ChirpStack HTTP integration supports
> custom headers.

### ChirpStack v4 setup

1. In ChirpStack: *Application → Integrations → HTTP* → **Add integration**.
2. Payload encoding: **JSON**, event endpoint URL:
   `http://<host>:<port>/api/telemetry/ingest`
3. Add a custom header: `Authorization: Bearer <your-api-key>`.

### Example

```bash
curl -X POST http://localhost:5000/api/telemetry/ingest \
  -H 'Authorization: Bearer your-secret-key' \
  -H 'Content-Type: application/json' \
  -d '{
    "deviceInfo": { "devEui": "a1b2c3d4e5f6a7b8", "deviceName": "trap-tracker-01" },
    "object": { "latitude": -1.2921, "longitude": 36.8219, "position": "normal", "battery": 95, "temperature": 23.5 }
  }'
# -> 200 {"status": "processed"}
```

| Code  | Meaning                                              |
| ----- | --------------------------------------------------- |
| `200` | Payload accepted and processed (unknown devEui included). |
| `400` | Body is not valid JSON.                              |
| `401` | Missing/invalid API key (when `API_KEY` is set).     |

## Tracker uplink history (`/api/uplinks` and `/uplinks`)

Every valid JSON uplink whose `deviceInfo.devEui` matches a registered
`smart_trap_tracker.device_eui` is stored as a separate row in the
`tracker_uplinks` table. This happens for both HTTP and MQTT ingestion paths.
Unknown devices are not stored. An uplink is recorded even when its `object`
section is missing or does not contain any recognized sensor fields.

Each stored row includes:

- The device EUI, receive timestamp, source, and MQTT topic/HTTP endpoint
- Parsed latitude, longitude, position, and battery values when valid
- The original decoded JSON payload for audit and troubleshooting

The raw payload is stored in the database but is never written to application
logs. The list endpoint excludes it to keep responses compact; the detail
endpoint and the **View** action on `/uplinks` expose it on demand. There is no
automatic retention cleanup, so the `tracker_uplinks` table will grow with each
received uplink.
The history API derives a nullable Celsius `temperature` from each stored
payload's `object.temperature` field without a separate database column.

### Endpoints

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/uplinks` | List history, newest first. Query: `limit`, `offset`, `device_eui`, `source`. |
| GET | `/api/uplinks/<id>` | Get one uplink including its raw decoded JSON payload. |

The SB Admin 2-style `/uplinks` page provides tracker/source filters,
pagination, refresh, and an uplink detail modal.

## Latest tracker temperatures

`GET /api/stt` and `GET /api/stt/<id>` include `temperature` (°C) and
`temperature_received_at` (the server receipt time of that reading). Both are
null until a valid temperature arrives. These fields describe the tracker
sensor and are separate from the editable `traps.temperature` value.

After deploying this backend update to an existing database, restore the
latest valid reading from each tracker's stored raw uplinks before releasing
the tracker page update:

```bash
flask --app run.py backfill-tracker-temperatures
```

The command is safe to repeat. It does not change a tracker's general
`updated_date` or replace a newer reading received during the backfill.

## Latest tracker signal strength

The tracker APIs (`/api/stt`, `/api/stt/<id>`, and `/api/stt/unassigned`)
include read-only `rssi` (dBm) and `rssi_received_at`. The trap list, detail,
and save responses include the assigned tracker's equivalent fields as
`tracker_rssi` and `tracker_rssi_received_at`, under the existing trap
permissions.

RSSI is derived from the newest stored HTTP or MQTT message, ordered by
server receipt time and then uplink ID. When multiple gateways received a
message, the strongest finite numeric `rxInfo[].rssi` is used (`rx_info` is
also accepted). A newest message without RSSI returns null rather than an
older reading. The receipt time still identifies that newest message; both
fields are null when no stored message exists. Uplink list/detail responses
also expose the RSSI for that individual message.

Only each requested tracker's newest payload is fetched, in one batch
query per result page. Existing stored messages work immediately; no schema
upgrade or backfill is required. Deploy the backend before the UI update.

## Unassigned trackers API (`/api/stt/unassigned`)

`GET /api/stt/unassigned` returns registered smart trap trackers that are not
referenced by any row in the `traps` table. A tracker is matched by comparing
its `device_eui` with `traps.tracker_id`.

Both active and inactive traps count as assignments. Empty `tracker_id` values
do not count as assignments. Matching is exact and case-sensitive.

The endpoint returns the standard tracker objects and supports the same
pagination parameters as the regular tracker list:

| Parameter | Default | Description |
| --- | ---: | --- |
| `limit` | `100` | Maximum number of trackers to return. |
| `offset` | `0` | Number of trackers to skip. |

Example:

```bash
curl 'http://localhost:8080/api/stt/unassigned?limit=100&offset=0'
```

Use a JWT access token in the `Authorization: Bearer <ACCESS_TOKEN>` header.
Legacy service integrations may use the configured API key. The endpoint
returns `200` with an empty array when every registered tracker is assigned or
no trackers exist.

## Trap configuration API (`/api/traps`)

Trap device configurations are stored in a file-based **SQLite** database
(`data/traps.db`, created automatically on startup). Override the location with
the `DATABASE_URL` environment variable.

The application applies idempotent schema upgrades on startup so existing
databases receive newly added nullable columns without losing trap records.

> **Auth:** every `/api/traps` request requires a JWT access token. Legacy
> service integrations may use the configured API key. The examples below omit
> authentication headers for brevity.

> SQLite has no native `SERIAL` / `NUMERIC` / `TIMESTAMPTZ`. The ORM uses an
> autoincrement integer PK, `Decimal` temperatures, and UTC datetimes; the
> `updated_at` column is bumped automatically on every change.

### Data model (`traps` table)

| Field         | Type           | Constraints                       | Notes                                                  |
| ------------- | -------------- | --------------------------------- | ------------------------------------------------------ |
| `id`          | integer        | primary key, auto-increment       | Read-only; assigned by the database.                   |
| `status`      | string(20)     | **required**                      | e.g. `active`, `inactive`.                             |
| `trap_id`     | string(50)     | **required**, **unique**          | Business identifier; duplicates return `409`.          |
| `asset_number` | string(100)    | optional                          | Asset identifier; nullable and not required to be unique. |
| `tracker_id`  | string(50)     | optional                          | Linked tracker device EUI (empty allowed; UI offers a dropdown). |
| `location`    | string(50)     | optional                          |                                                        |
| `door_status` | string(20)     | optional                          | e.g. `open`, `closed`; typically set by sensors.       |
| `temperature` | numeric(5,2)   | optional                          | Numeric; serialized as a JSON number.                  |
| `notes`       | string(255)    | optional                          | Free-text.                                             |
| `updated_by`  | string(50)     | defaults to `system`              | Actor derived by the backend for authenticated changes. |
| `created_at`  | datetime (UTC) | read-only                         | ISO-8601; set on creation.                             |
| `updated_at`  | datetime (UTC) | read-only, auto-updated           | ISO-8601; bumped on every change.                      |

**`updated_by` semantics:** this column records the authenticated actor for
manual API changes. The backend ignores a client-provided `updated_by` value.
Automated sensor updates use the default `"system"`.

### Endpoints

| Method | Path              | Description                                          |
| ------ | ----------------- | --------------------------------------------------- |
| GET    | `/api/traps`      | List traps. Query: `limit` (default 100), `offset` (default 0), `status` filter. |
| GET    | `/api/traps/<id>` | Get a single trap by numeric `id`.                  |
| POST   | `/api/traps`      | Create a trap. Requires `status`, `trap_id`. |
| PUT    | `/api/traps/<id>` | Update a trap. The backend derives `updated_by`. |
| DELETE | `/api/traps/<id>` | Delete a trap.                                       |

### Status codes

| Code  | Meaning                                                              |
| ----- | ------------------------------------------------------------------- |
| `200` | Success (GET, PUT, DELETE).                                          |
| `201` | Created (POST).                                                     |
| `400` | Bad request — missing required field, invalid type, or non-integer `limit`/`offset`. |
| `404` | Trap not found.                                                     |
| `409` | Conflict — `trap_id` already exists.                                |
| `500` | Internal server error.                                              |

Error responses are JSON of the form `{"error": "<message>"}`.

### Validation rules

- `status`, `trap_id` are required on create (`400` if missing).
- `trap_id` must be unique (`409` on duplicate, on both create and update).
- `asset_number` is optional, nullable, limited to 100 characters, and may be
  duplicated.
- `updated_by` is ignored when supplied by a client; the backend records the
  authenticated username or service identity.
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
    "asset_number": "ASSET-001",
    "tracker_id": "TRK-001",
    "location": "north",
    "temperature": 23.5
  }'
```

Response `201 Created`:

```json
{
  "id": 1,
  "status": "active",
  "trap_id": "TRAP-001",
  "asset_number": "ASSET-001",
  "tracker_id": "TRK-001",
  "location": "north",
  "door_status": null,
  "temperature": 23.5,
  "notes": null,
  "updated_by": "admin",
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

**Update** — `PUT /api/traps/1`; `updated_at` is bumped automatically and
`updated_by` is derived from the authenticated user:

```bash
curl -X PUT http://localhost:8080/api/traps/1 -H 'Content-Type: application/json' \
  -d '{"door_status": "open"}'
```

**Delete** — `DELETE /api/traps/1`:

```bash
curl -X DELETE http://localhost:8080/api/traps/1
# -> 200 {"message": "Trap 1 deleted"}
```

## Deployment actions

A deployment represents one active period for a trap. Deployment actions record
the work performed during that period. Actions are immutable: they cannot be
updated or individually deleted, and are removed only when their deployment is
deleted.

### Action types

Action types are stored in `deployment_action_types`. The initial seeded types
are `bait_added`, `routine_check`, and `bait_removed`.

All authenticated users with deployment read permission can list active action
types:

```text
GET /api/deployment-action-types
```

Only administrators with `settings:admin` can create, update, or delete action
types. Administrators may update only `label`, `description`, and `is_active`;
the `code` is immutable. An action type referenced by a deployment action cannot
be deleted. It must be deactivated instead by setting `is_active` to `false`.

```text
POST   /api/deployment-action-types
GET    /api/deployment-action-types/<id>
PUT    /api/deployment-action-types/<id>
DELETE /api/deployment-action-types/<id>
```

Action type timestamps are managed by SQLAlchemy. Clients cannot provide or
override `created_at` or `updated_at`.

### Creating an action

Actions can be added only to active deployments. Each action requires exactly
one picture and may include an optional note. The request must use
`multipart/form-data`:

```text
POST /api/deployments/<deployment_id>/actions
```

Form fields:

```text
action_type_id = 1
notes = Fresh bait added
picture = <jpg, jpeg, png, or gif file>
```

The backend assigns `performed_at` and `performed_by` from the authenticated
request. These values cannot be supplied or changed by the client.

Deployment action permissions are:

- `deployments:read` to list actions and retrieve action pictures.
- `deployments:update` to create actions.

```text
GET /api/deployments/<deployment_id>/actions
GET /api/deployment-actions/<action_id>/picture
```

There are no update or delete endpoints for deployment actions. The response
contains the action type object, optional note, required picture URL and
filename, action timestamp, and actor username.

Deployment locations remain separate historical records and continue to use
the existing location endpoints. Deployment-level notes and standalone
deployment pictures are not supported; notes and pictures belong to actions.

## Web UI (`/traps`)

A Jinja2 + Bootstrap single-page interface for managing traps, served at
`http://localhost:<port>/traps`. It calls the `/api/traps` endpoints via
`fetch()` and provides:

- A sortable table of all traps (click any column header to sort).
- **Add Trap** button and per-row **Edit**/**Delete** actions (delete asks for
  confirmation).
- Client-side **search** by Asset Number, Trap ID, or Location, server-side **status** filter,
  and **pagination** (page-size selector + Prev/Next).
- Client-side required-field validation and toast notifications that surface
  API errors (e.g. duplicate `trap_id` and invalid field values).

Disable it by setting `ENABLE_FRONTEND=false`, after which `/traps` returns
`404` while the JSON API at `/api/traps` keeps working.

> The UI uses an SB Admin 2-style layout with Bootstrap 5 and Bootstrap Icons
> vendored locally under `app/static/vendor/`, so no internet access is required
> at runtime.

## Authentication

The API supports `LOCAL` and `LDAP` application users. Both credential providers
converge on the same Flask-issued JWT.

Create or maintain the break-glass LOCAL account with the Flask CLI:

```
flask --app run.py create-user admin --role administrator
```

The command prompts for a password. LOCAL passwords are stored as Werkzeug
PBKDF2 hashes. LDAP passwords are only sent to the backend for a login attempt;
they are not stored locally or included in tokens. At least one enabled LOCAL
administrator is protected from deletion, deactivation, or demotion. Set a
stable JWT signing secret before running in production:

```
JWT_SECRET_KEY=long-random-signing-secret
JWT_ACCESS_TOKEN_MINUTES=15
JWT_REFRESH_TOKEN_DAYS=7
```

**Login** — send either LOCAL or provisioned LDAP credentials to `/auth/login`.
The backend first looks up the username in the application database, ignoring
case and surrounding whitespace. Missing, ambiguous, or inactive accounts are
rejected with `401 INVALID_CREDENTIALS` without contacting LDAP. Flask selects
the provider from the application account record; the client does not select a
provider at login. Both HTTP and HTTPS requests are accepted:

```bash
curl -X POST http://localhost:8080/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your-password"}'
```

LOCAL accounts are verified against their stored password hash. For LDAP
accounts, the backend resolves the stored stable directory subject to obtain
the current DN, checks the directory identity and account status, then binds
with the submitted password. Login does not search LDAP for unknown usernames
or alternative login names. If a directory username changes, synchronize the
application account through `POST /api/users/<id>/sync-profile` before login
with the new username.

The response contains an access token and refresh token. Include the access
token on protected requests:

```bash
curl http://localhost:8080/api/traps \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

When the access token expires, request a replacement with the refresh token:

```bash
curl -X POST http://localhost:8080/auth/refresh \
  -H "Authorization: Bearer <REFRESH_TOKEN>"
```

Both providers receive the same login response with access and refresh JWTs.
JWT `sub` is the local application user ID; claims include the local role,
provider, and token version, but never directory passwords or bind credentials.
`GET /auth/me` returns current local profile/role data. Access tokens last 15
minutes by default and refresh tokens last seven days by default. `POST
/auth/logout` returns `204`; logout remains client-side and does not revoke a
copied token.

Each JWT-authenticated API request checks the local user is still present,
enabled, and on the current token version, and derives current permissions from
the local role. These checks do not contact LDAP. An application administrator
disabling a user or changing their role/password invalidates prior tokens. An
LDAP account disabled in the directory may continue using an already-issued
access token until its short expiry; LDAP refresh checks directory identity and
account status and will reject renewal. Refreshing an LDAP session requires the
directory to be available; LOCAL authentication and refresh are independent of
LDAP availability.

**Public (no auth required):** `/`, `/api/health`, `/auth/login`, and
`/auth/logout`. Protected API requests require a valid JWT unless they use the
explicitly configured legacy service API key.

## User Provisioning API

Users can be managed by an authenticated administrator through `/api/users`.
The create request explicitly chooses `auth_provider` as `LOCAL` or `LDAP`.
These endpoints require an administrator JWT and do not accept the legacy
service API key.

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/ldap/users?search=...` | Search directory users to provision (administrator only). |
| GET | `/api/users` | List application users. Supports `limit`, `offset`, and `search`. |
| GET | `/api/users/<id>` | Get one application user. |
| POST | `/api/users` | Create a LOCAL user or provision an LDAP user. |
| PUT | `/api/users/<id>` | Update locally managed role/status and LOCAL profile/password. |
| POST | `/api/users/<id>/sync-profile` | Synchronize LDAP-owned profile fields. |
| DELETE | `/api/users/<id>` | Delete a user. |

Example create request:

```http
POST /api/users
Authorization: Bearer <ADMIN_ACCESS_TOKEN>
Content-Type: application/json
```

```json
{
  "auth_provider": "LOCAL",
  "username": "operator",
  "password": "operator-password",
  "display_name": "Field Operator",
  "email": "operator@example.com",
  "role": "field_operator",
  "is_active": true
}
```

For `LOCAL`, username/password and optional profile fields are supplied by the
administrator. Passwords must be at least eight characters and hashes are never
returned.

For `LDAP`, the administrator searches the directory, selects a result, then
creates the local application account using its stable subject:

```json
{
  "auth_provider": "LDAP",
  "directory_subject": "<selected-directory-subject>",
  "role": "field_operator",
  "is_active": true
}
```

The backend retrieves username, display name, and email from LDAP. LDAP password
and profile fields cannot be supplied in user create/update requests. Roles and
application enablement remain local. LDAP profile synchronization can update
the username, display name, and email, but not the local role or enabled state.
Authentication provider and directory identity cannot be changed after
provisioning. Directory username collisions with any local user are rejected.
Keep `LDAP_DIRECTORY_KEY` and the configured stable subject attribute/value
mapping unchanged for existing accounts; changing the directory key makes
previously provisioned identities unresolvable until they are explicitly
reprovisioned or migrated.

`GET /api/ldap/users` requires a search string of at least two characters and
returns only a bounded result set, without DNs. Configure directory attributes
to match the actual LLDAP schema or AD deployment; do not assume the development
and production schemas use identical names. AD uses `objectGUID` as its stable
identity and checks `userAccountControl`/`accountExpires`. For LLDAP, set
`LDAP_SUBJECT_ATTRIBUTE` to the verified stable UUID attribute; configure
`LDAP_ENABLED_ATTRIBUTE` to the deployed LLDAP enabled/disabled attribute (or
configure `LDAP_USER_FILTER` to exclude disabled accounts) so refresh can reject
disabled users. If neither is available, LDAP account disablement cannot be
reliably detected until the directory stops returning that identity.

The API protects the last enabled LOCAL administrator, and administrators
cannot delete or demote their own account. `password_hash` is null for LDAP
users.

Because access JWTs are short-lived, directory disablement is detected at LDAP
refresh rather than on every API request. Local account disablement and token
version changes are checked on every authenticated API request.

## LDAP Configuration and Transport

LDAP is disabled by default (`LDAP_ENABLED=false`). Configure one directory per
backend deployment using the `LDAP_*` environment variables in `.env.example`.
The adapter supports LLDAP and Active Directory with configurable attribute
mappings. LLDAP and AD attribute names and account-state capabilities must be
verified against the deployed directory/schema.

- Plain `ldap://` with `LDAP_STARTTLS=false` is accepted in every environment,
  including production. LDAPS and StartTLS are optional: use `ldaps://` or
  `ldap://` with `LDAP_STARTTLS=true` when encryption is desired. Certificate
  validation applies when either TLS mode is selected; `LDAP_CA_CERT_FILE`
  supports a custom CA.
- Keep `LDAP_BIND_DN` and `LDAP_BIND_PASSWORD` only in backend secret
  configuration. They are never returned or placed in JWTs.
- LDAP user passwords are bound only for login and never logged or persisted.
- `LDAP_ALLOW_INSECURE` is no longer required; existing values are ignored.
  Directory transport is selected by `LDAP_SERVER_URI` and `LDAP_STARTTLS`.
- If TLS terminates at a reverse proxy, configure `TRUSTED_PROXY_HOPS` only
  when Flask is reachable through that trusted proxy; Flask uses the proxy's
  forwarded scheme information for the request.
- If LDAP is unavailable, LDAP login/refresh fails with `503`; the app still
  starts and LOCAL login/refresh continues working.
- LDAP groups are not used for application authorization. Local `role` remains
  the sole source of application permissions.

API clients submit credentials to Flask over HTTP or HTTPS and use the returned
JWT for subsequent API calls. Preserve the refresh token after a transient
`503` to retry when LDAP recovers.

## Security

Configuration is loaded entirely from environment variables — no credentials are
hardcoded anywhere in the source.

**Environment setup**

- Copy the template and fill in your values: `cp .env.example .env`.
- **Never commit `.env`.** It is gitignored, along with `logs/` and `data/`
  (which can contain operational data such as device IDs, GPS coordinates, and
  raw payloads). After `git init`, run `git status` and confirm `.env`, `logs/`,
  and `data/` are **not** staged before your first commit.

**JWT and service credentials**

- Generate a strong JWT secret and set it as `JWT_SECRET_KEY`:

  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

- `API_KEY` is optional and should only be used for non-browser integrations.
- JWTs are sent in the `Authorization` header, so wildcard CORS does not require
  credentialed requests or browser cookies.

**Production hardening**

- Set `FLASK_ENV=production` to disable the debugger/reloader (avoids exposing
  stack traces and the interactive debugger).
- Do **not** run the Flask dev server in production. Use a WSGI server such as
  **gunicorn** behind a **TLS-terminating reverse proxy**; bind to localhost/the
  proxy rather than `0.0.0.0` when publicly exposed.
- Use **MQTT over TLS** (port 8883) and database TLS where supported; keep all
  broker/DB credentials in environment variables only.

**Recommended (not yet implemented)**

- Rate limiting on `/auth/login` to deter password brute forcing (e.g.
  `flask-limiter`).
- Security headers (e.g. `flask-talisman` or at the proxy). CORS is intentionally
  enabled for all origins; keep `JWT_SECRET_KEY` configured outside local development.
- Run a dependency vulnerability scan before each release: `pip-audit`.

## Docker deployment

A multi-stage `Dockerfile`, `uwsgi.ini`, and `docker-compose.yml` are included
for production-style deployment.

**Quick start**

```bash
# Ensure a .env file exists (copy from the example if you haven't already)
cp .env.example .env    # then edit with your JWT secret and broker settings

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
- Set a strong `JWT_SECRET_KEY`, create at least one local user, and configure
  real MQTT broker details in your `.env`.
- The `.env` file must contain at least the variables listed in
  [Configuration](#configuration) — the app will warn but start gracefully for
  optional values (e.g. missing MQTT broker).

## Roadmap

- **Done:** Flask scaffolding, MQTT monitoring, SQLite trap CRUD API, web UI,
  local-user JWT authentication, and permission enforcement.
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
