# Surf-TG Backend API

Surf-TG is a **JSON-only backend service** for Telegram-backed file indexing and delivery. It runs a Python/aiohttp server plus Telegram bot clients that can:

- index files from configured Telegram channels;
- browse indexed Telegram channels and database playlist folders;
- search channel files and playlist files;
- manage playlist folders and file metadata as an admin;
- serve thumbnails;
- stream or download Telegram files with HTTP byte-range support;
- serve on-demand HLS (`.m3u8`) playback for compatible video files;
- report service health via `GET /healthz`;
- rate-limit and CORS-restrict access to a configured frontend origin;
- balance streaming load across worker bots, optionally shared across instances via Redis.

Treat the server as an authenticated backend/API surface that a separate web, mobile, or desktop frontend can call. See [Response object shapes](#response-object-shapes) for the exact JSON shape of files, folders, and channels.

## Environment variables

Surf-TG reads environment variables directly and also loads a local `config.env` file when present. For local development, create `config.env` in the project root and set the variables you need.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `API_ID` | Yes | `0` | Telegram `api_id` from <https://my.telegram.org/apps>. |
| `API_HASH` | Yes | empty | Telegram `api_hash` from <https://my.telegram.org/apps>. |
| `BOT_TOKEN` | Yes | empty | Telegram bot token from BotFather. The bot must be able to access indexed channels. |
| `AUTH_CHANNEL` | Yes | empty | Comma-separated Telegram channel IDs used as source indexes, for example `-1001234567890,-1009876543210`. |
| `DATABASE_URL` | Yes | empty | MongoDB connection string used for playlist folders/files and runtime configuration. |
| `BASE_URL` | Yes | empty | Public base URL for the deployed service, without a trailing slash. |
| `PORT` | No | `8080` | TCP port used by the aiohttp server. |
| `SESSION_STRING` | No | empty | Optional Pyrogram user session string. When set, the user client is started alongside the bot client. |
| `USERNAME` | No | `admin` | Standard authenticated username for browsing/searching/watching. |
| `PASSWORD` | No | `admin` | Password for `USERNAME`. Change this in every deployment. |
| `ADMIN_USERNAME` | No | `surfTG` | Admin username. Required for playlist/config mutation routes. Make it different from `USERNAME`. |
| `ADMIN_PASSWORD` | No | `surfTG` | Password for `ADMIN_USERNAME`. Change this in every deployment. |
| `THEME` | No | `vapor` | Legacy configuration value retained for compatibility; it is not used by JSON responses. |
| `SLEEP_THRESHOLD` | No | `60` | Pyrogram flood-wait sleep threshold. |
| `WORKERS` | No | `10` | Maximum concurrent worker count for incoming Telegram updates. |
| `MULTI_CLIENT` | No | `False` | Set to `true`/`false`. Automatically becomes `true` at runtime once any `MULTI_TOKEN*` client starts successfully; you don't need to set it by hand. |
| `MULTI_TOKEN1`, `MULTI_TOKEN2`, ... | No | unset | Optional additional bot tokens for multi-client streaming/indexing. Add each worker bot to `AUTH_CHANNEL`. |
| `HIDE_CHANNEL` | No | `False` | Set to `true`/`false`. Legacy configuration value retained for compatibility. |
| `TMDB_API_KEY` | No | empty | TMDb API key used to add `tmdb_id`, `tmdb_type`, and `poster_url` to indexed and user-session file results. Without it, `tmdb_id` is `null` and the fallback poster is returned. |
| `FRONTEND_URL` | No | empty | Comma-separated list of frontend origins allowed to call this API from a browser, e.g. `https://app.example.com,https://staging.example.com`. Leave empty to disable CORS restriction entirely (default; matches previous behavior). See [CORS and allowed frontend origins](#cors-and-allowed-frontend-origins). |
| `RATE_LIMIT_REQUESTS` | No | `120` | Max requests per client IP per `RATE_LIMIT_WINDOW` seconds, applied to every route. Set to `0` to disable. |
| `RATE_LIMIT_WINDOW` | No | `60` | Window size in seconds for `RATE_LIMIT_REQUESTS`. |
| `LOGIN_RATE_LIMIT_REQUESTS` | No | `10` | Stricter max requests per client IP per `LOGIN_RATE_LIMIT_WINDOW` seconds, applied only to `POST /login`, to slow down credential brute-forcing. Set to `0` to disable. |
| `LOGIN_RATE_LIMIT_WINDOW` | No | `60` | Window size in seconds for `LOGIN_RATE_LIMIT_REQUESTS`. |
| `REDIS_URL` | No | empty | Optional, e.g. `redis://localhost:6379/0`. When set, worker-bot load balancing and rate limiting are shared across every running instance of this service instead of tracked per-process. Safe to leave empty for a single-instance deployment. |

## Local, Docker, and Heroku deployment

### Local development

```sh
git clone https://github.com/weebzone/Surf-TG
cd Surf-TG
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp sample_config.env config.env 2>/dev/null || touch config.env
# edit config.env with your Telegram, MongoDB, and auth settings
python3 -m bot
```

The server binds to `0.0.0.0:$PORT` and defaults to port `8080`.

### Docker

```sh
git clone https://github.com/weebzone/Surf-TG
cd Surf-TG
# create config.env or pass environment variables with -e/--env-file
docker build -t surf-tg .
docker run --env-file config.env -p 8080:8080 surf-tg
```

You can also use Compose:

```sh
docker compose up --build
```

### Heroku

The repository includes both `Procfile` and `heroku.yml` definitions that run `bash surf-tg.sh`. Configure all required environment variables as Heroku config vars before starting the app.

```sh
heroku create your-surf-tg-app
heroku stack:set container
heroku config:set API_ID=... API_HASH=... BOT_TOKEN=... AUTH_CHANNEL=... DATABASE_URL=... BASE_URL=https://your-surf-tg-app.herokuapp.com
heroku config:set USERNAME=... PASSWORD=... ADMIN_USERNAME=... ADMIN_PASSWORD=...
git push heroku HEAD:main
```

## Authentication flow

Surf-TG uses cookie-backed aiohttp sessions.

1. Protected browse, search, and watch routes return `401 Unauthorized` JSON until a session is authenticated.
2. `POST /login` accepts form fields `username` and `password`.
3. If the submitted credentials match either `USERNAME`/`PASSWORD` or `ADMIN_USERNAME`/`ADMIN_PASSWORD`, the server stores `session['user'] = username` and returns JSON confirming the authentication state.
4. Admin-only routes require `session['user'] == ADMIN_USERNAME` and return `{"msg":"Who the hell you are"}` when called by a non-admin or anonymous session.
5. `POST /logout` removes `session['user']` and returns JSON confirming the session is unauthenticated.

### Auth categories used below

- **Public**: no login session required.
- **User**: requires either standard or admin login.
- **Admin**: requires admin login.

## Response object shapes

Every list/search/browse endpoint returns objects built from three canonical shapes. Every object has a `kind` field telling you which one you're looking at, and only the fields needed to identify, display, and stream/download it — no duplicate or aliased fields.

**File** (`kind: "file"`) — returned by `/channel/{chat_id}`, `/search/{chat_id}`, `/playlist`, and `/search/db/{parent}`:

```json
{
  "id": 42,
  "kind": "file",
  "chat_id": "1234567890",
  "title": "Movie Name (2020)",
  "size": "700.00MB",
  "mime_type": "video/mp4",
  "hash": "abcdef",
  "tmdb_id": 262838,
  "tmdb_type": "movie",
  "season": null,
  "episode": null,
  "poster_url": "https://image.tmdb.org/t/p/w500/...",
  "parent_folder": null,
  "stream_url": "/1234567890/stream?id=42&hash=abcdef",
  "watch_url": "/watch/1234567890?id=42&hash=abcdef"
}
```

`id` is a Telegram message ID for channel-listed files, or a database document ID (string) for files placed into a playlist folder via `POST /send`. `parent_folder` is only non-null for the latter. `tmdb_id`/`tmdb_type`/`season`/`episode` are `null` when no TMDb match is available.

**Folder** (`kind: "folder"`) — returned by `GET /`, `GET /playlist`, and `GET /searchDbFol`:

```json
{
  "id": "665f1a2b3c4d5e6f7a8b9c0d",
  "kind": "folder",
  "title": "TV Shows",
  "thumbnail": "https://example.com/thumb.jpg",
  "parent_folder": "root",
  "url": "/playlist?db=665f1a2b3c4d5e6f7a8b9c0d"
}
```

**Channel** (`kind: "channel"`) — returned by `GET /`:

```json
{
  "id": "1234567890",
  "kind": "channel",
  "title": "My Movie Channel",
  "chat_type": "CHANNEL",
  "thumbnail": "/api/thumb/-1001234567890",
  "url": "/channel/1234567890"
}
```

`id`/`chat_id` in every object above is always the **public** channel ID (no `-100` prefix) — the same form used in URLs. The server never returns its internal `-100...` representation; there's nothing you need it for.

> **Changed from earlier versions:** file/folder/channel objects previously duplicated several fields under two names (`size`/`file_size`, `mime_type`/`file_type`, `thumbnail`/`poster_url`, `id`/`chat_id`/`public_chat_id`) and overloaded a single `type` field to mean three different things (object kind, MIME type, and Pyrogram chat type) depending on the endpoint. If your frontend reads any of the old duplicate/aliased field names, update it to the single canonical name shown above.

## API endpoint reference

All non-streaming endpoints return `application/json`. Protected endpoints return `401` with `{"error": "Authentication required"}` when no authenticated session is present. Unhandled server errors return `500` with `{"error": "internal_error"}` — full details are logged server-side, not exposed in the response.

### `GET /healthz`

- **Auth**: Public.
- **Purpose**: Liveness/readiness probe for load balancers and orchestrators (Kubernetes, Docker Swarm, Render, etc.).
- **Success**: `200 OK application/json` when Mongo and at least the primary Telegram client are reachable.
- **Degraded**: `503 Service Unavailable application/json` when either check fails.

Example response:

```json
{
  "status": "ok",
  "checks": {"mongo": true, "telegram": true},
  "worker_clients": 3
}
```

### `POST /login`

- **Auth**: Public.
- **Body**: `application/x-www-form-urlencoded` or multipart form.

| Field | Required | Description |
| --- | --- | --- |
| `username` | Yes | Either `USERNAME` or `ADMIN_USERNAME`. |
| `password` | Yes | Matching password. |

- **Success**: `200 OK application/json` with `{"authenticated": true, "is_admin": false}` (or `true` for an admin); sets a session cookie.
- **Failure**: `401 Unauthorized application/json` with `{"authenticated": false, "error": "Invalid username or password"}`.

Example request:

```sh
curl -i -c cookies.txt -X POST http://localhost:8080/login \
  -d 'username=admin' \
  -d 'password=admin'
```

### `POST /logout`

- **Auth**: Public, but only affects the current session.
- **Body**: none.
- **Success**: `200 OK application/json` with `{"authenticated": false}`; removes the logged-in session user.

Example response: `{"authenticated": false}`.

### `GET /`

- **Auth**: User.
- **Query parameters**: none.
- **Success**: `200 OK application/json` containing channel cards and root playlist folders. Admin sessions receive `is_admin: true`.
- **Unauthenticated**: `401 Unauthorized application/json`.

### `GET /playlist?db={folder_id}&page={page}`

- **Auth**: User.
- **Query parameters**:

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `db` | Yes | none | Database playlist folder ID to open. |
| `page` | No | `1` | Pagination page. |

- **Success**: `200 OK application/json` containing child folders and files for `folder_id`.
- **Unauthenticated**: `401 Unauthorized application/json`.

### `GET /search/db/{parent}?q={query}&page={page}`

- **Auth**: User.
- **Path parameters**:

| Parameter | Description |
| --- | --- |
| `parent` | Playlist folder ID to search within. |

- **Query parameters**:

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `q` | Yes | none | Search query. |
| `page` | No | `1` | Pagination page. |

- **Success**: `200 OK application/json` playlist search results for the parent folder.

### `GET /channel/{chat_id}?page={page}`

- **Auth**: User.
- **Path parameters**:

| Parameter | Description |
| --- | --- |
| `chat_id` | Telegram channel ID without the `-100` prefix. The server adds `-100` internally. |

- **Query parameters**:

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `page` | No | `1` | Pagination page. |

- **Success**: `200 OK application/json` channel file listing.

### `GET /search/{chat_id}?q={query}&page={page}`

- **Auth**: User.
- **Path parameters**:

| Parameter | Description |
| --- | --- |
| `chat_id` | Telegram channel ID without the `-100` prefix. |

- **Query parameters**:

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `q` | Yes | none | Search query. |
| `page` | No | `1` | Pagination page. |

- **Success**: `200 OK application/json` channel search results.

### `GET /api/thumb/{chat_id}?id={message_id}`

- **Auth**: Public.
- **Path parameters**:

| Parameter | Description |
| --- | --- |
| `chat_id` | Telegram chat/channel ID as expected by thumbnail lookup. |

- **Query parameters**:

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `id` | No | none | Telegram message ID. If omitted, the route returns the chat/channel image when available. |

- **Success**: `200 OK image/jpeg` file response.

Example response headers:

```http
HTTP/1.1 200 OK
Content-Type: image/jpeg
```

### `GET /watch/{chat_id}?id={message_id}&hash={hash}`

- **Auth**: User.
- **Path parameters**:

| Parameter | Description |
| --- | --- |
| `chat_id` | Telegram channel ID without the `-100` prefix. |

- **Query parameters**:

| Parameter | Required | Description |
| --- | --- | --- |
| `id` | Yes | Telegram message ID for the file. |
| `hash` | Yes | First six characters of the Telegram file unique ID. Used as a lightweight access/integrity check by the stream route. |

- **Success**: `200 OK application/json` with the validated file ID, hash, and `stream_url`.
- **Errors**: `401 Unauthorized` if unauthenticated.

Example response:

```json
{
  "id": "42",
  "chat_id": "1234567890",
  "hash": "abcdef",
  "stream_url": "/1234567890/stream?id=42&hash=abcdef"
}
```

### `GET /{chat_id}/{message_id}/hls.m3u8?hash={hash}`

- **Auth**: Public (same hash-based check as the stream route).
- **Purpose**: Returns an HLS playlist for the file, remuxing it into `.ts` segments on first request (via `ffmpeg -c copy`, cached afterward). Only works for HLS-compatible codecs (H.264/AAC); other codecs need a re-encode, which this route does not currently do.
- **Path parameters**:

| Parameter | Description |
| --- | --- |
| `chat_id` | Telegram channel ID without the `-100` prefix. |
| `message_id` | Telegram message ID for the file. |

- **Query parameters**:

| Parameter | Required | Description |
| --- | --- | --- |
| `hash` | Yes | First six characters of the Telegram file's unique ID. |

- **Success**: `200 OK application/vnd.apple.mpegurl` with the playlist body.
- **Errors**: `403 Forbidden` for invalid hash, `404 Not Found` for missing Telegram file, `500 Internal Server Error` if `ffmpeg` isn't installed or remuxing fails.
- **Note**: the first request for a given file blocks until remuxing finishes, which can take noticeably longer than the file's own transfer time for large files. Subsequent requests are served from cache.

### `GET /{chat_id}/{message_id}/hls/{segment}?hash={hash}`

- **Auth**: Public.
- **Purpose**: Serves one `.ts` segment referenced by the playlist above.
- **Success**: `200 OK video/mp2t` with the segment body.
- **Errors**: `404 Not Found` if the segment doesn't exist, `400 Bad Request` for a malformed segment name.

### `GET /{chat_id}/{encoded_name}?id={message_id}&hash={hash}`

- **Auth**: Public.
- **Purpose**: Streams or downloads the Telegram file.
- **Path parameters**:

| Parameter | Description |
| --- | --- |
| `chat_id` | Telegram channel ID without the `-100` prefix. |
| `encoded_name` | Filename slug used in the URL. The handler does not currently use it to locate the file. |

- **Query parameters**:

| Parameter | Required | Description |
| --- | --- | --- |
| `id` | Yes | Telegram message ID for the file. |
| `hash` | Yes | First six characters of the Telegram file unique ID. |

- **Request headers**:

| Header | Required | Description |
| --- | --- | --- |
| `Range` | No | Byte range such as `bytes=0-1048575`. |

- **Success**: `200 OK` for full responses when no `Range` header is sent, or `206 Partial Content` when `Range` is present.
- **Response headers**: `Content-Type`, `Content-Range`, `Content-Length`, `Content-Disposition: attachment; filename="..."`, and `Accept-Ranges: bytes`.
- **Errors**: `400 Bad Request` if `id`/`hash` are missing or `id` isn't numeric, `403 Forbidden` for invalid hash, `404 Not Found` for missing Telegram file (also prunes the stale index entry so it stops appearing in future listings), `416 Range Not Satisfiable` for invalid byte ranges.

Example partial response:

```http
HTTP/1.1 206 Partial Content
Content-Type: video/mp4
Content-Range: bytes 0-1048575/734003200
Content-Length: 1048576
Content-Disposition: attachment; filename="movie.mp4"
Accept-Ranges: bytes
```

### `POST /create`

- **Auth**: Admin.
- **Body**: form data.

| Field | Required | Description |
| --- | --- | --- |
| `folderName` | Yes | New folder name. |
| `thumbnail` | No | Thumbnail URL/path stored with the folder. |
| `parent_dir` | Yes | Parent folder reference. Values containing `db=` are normalized to the ID after `db=`; otherwise the parent becomes `root`. |

- **Success**: `200 OK application/json` with `created: true` and `parent_folder`.
- **Non-admin**: JSON `{"msg":"Who the hell you are"}`.

### `POST /delete`

- **Auth**: Admin.
- **Body**: JSON.

| Field | Required | Description |
| --- | --- | --- |
| `delete_id` | Yes | Folder/file database ID to delete. |
| `parent` | Yes | Parent folder ID or `root`. |

- **Success**: `200 OK application/json` with `deleted: true` and `parent_folder`.
- **Failure**: `500 Internal Server Error` if database deletion fails.

### `POST /edit`

- **Auth**: Admin.
- **Body**: form data.

| Field | Required | Description |
| --- | --- | --- |
| `folder_id` | Yes | Folder database ID to edit. |
| `folderName` | Yes | Replacement folder name. |
| `thumbnail` | No | Replacement thumbnail. |
| `parent` | Yes | Parent folder ID or `root`. |

- **Success**: `200 OK application/json` with `updated: true` and `parent_folder`.
- **Failure**: `500 Internal Server Error` if update fails.

### `POST /edit_post`

- **Auth**: Admin.
- **Body**: form data.

| Field | Required | Description |
| --- | --- | --- |
| `file_id` | Yes | File database ID to edit. |
| `fileName` | Yes | Replacement file name. |
| `filethumbnail` | No | Replacement thumbnail. |
| `file_folder_id` | Yes | Parent folder ID or `root`. |

- **Success**: `200 OK application/json` with `updated: true` and `parent_folder`.
- **Failure**: `500 Internal Server Error` if update fails.

### `GET /searchDbFol?query={query}`

- **Auth**: Admin.
- **Query parameters**:

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `query` | No | empty string | Folder search text. |

- **Success**: `200 OK application/json` array/object returned by the database folder search helper.
- **Non-admin**: JSON `{"msg":"Who the hell you are"}`.

Example response shape:

```json
[
  {"id": "folder-id", "name": "Movies"}
]
```

The exact object fields depend on the database helper implementation.

### `POST /send`

- **Auth**: Admin (previously had no auth check at all — this was a real gap; it's now protected the same way as the other mutation routes).
- **Body**: form data.

| Field | Required | Description |
| --- | --- | --- |
| `chatId` | Yes | Telegram channel ID without `-100`; the route prepends `-100`. |
| `folderId` | Yes | Destination playlist folder ID or `root`. |
| `selectedIds` | Yes | Comma-separated entries. Each entry must be `file_id|hash|filename|size|file_type|thumbnail`. |

- **Success**: `200 OK application/json` with the number of created records and `parent_folder`.
- **Non-admin**: JSON `{"msg":"Who the hell you are"}`.
- **Validation failure**: `400 Bad Request application/json` if required form data is missing, or if any `selectedIds` entry doesn't have exactly 6 `|`-separated fields.

Example `selectedIds` value:

```text
123|abcdef|movie.mp4|734003200|video|https://example.com/thumb.jpg
```

### `GET /reload?chatId={chat_id}`

- **Auth**: Admin.
- **Query parameters**:

| Parameter | Required | Description |
| --- | --- | --- |
| `chatId` | Yes | Use `home` to clear global cache, or a channel ID without `-100` to clear that channel cache. |

- **Success**: `200 OK application/json` with the reloaded target.
- **Non-admin**: JSON `{"msg":"Who the hell you are"}`.

### `POST /config`

- **Auth**: Admin.
- **Body**: form data.

| Field | Required | Description |
| --- | --- | --- |
| `channel` | No | Replacement configured auth channel value stored in the database config. |
| `theme` | No | Replacement theme value stored in the database config. |

- **Success**: `200 OK application/json` with `updated: true`.
- **Failure**: `500 Internal Server Error` if config update fails.
- **Note**: when `channel` is provided, every running Telegram client (the main bot, every worker bot, and the optional user session) immediately re-resolves the new channel list, so a live channel change takes effect without a redeploy.

## Streaming and download behavior

The download endpoint is `GET /{chat_id}/{encoded_name}?id={message_id}&hash={hash}`. The route uses the Telegram `chat_id`, `message_id`, and `hash` to load file metadata through `ByteStreamer`, validate the file hash, and stream bytes from Telegram to the HTTP client.

Important behavior for frontend/client implementers:

- `chat_id` values in URLs omit the `-100` prefix. The server prepends it internally.
- `hash` must equal the first six characters of the Telegram file's `unique_id`; otherwise the response is `403 Forbidden`.
- `encoded_name` is used for readable URLs but is not used to fetch the file.
- The server sends `Content-Disposition: attachment`, so browsers normally download the file. A separate frontend can still place the URL in media elements if the browser accepts the MIME type and headers.
- The response includes `Accept-Ranges: bytes`.
- Sending a `Range` request such as `Range: bytes=1048576-2097151` returns `206 Partial Content` with the requested byte window.
- Invalid ranges return `416 Range Not Satisfiable` with `Content-Range: bytes */{file_size}`.
- Without a `Range` header, the route returns status `200 OK` and streams the whole file while still including `Content-Range` and `Content-Length`.

Example range request:

```sh
curl -L -b cookies.txt \
  -H 'Range: bytes=0-1048575' \
  'http://localhost:8080/1234567890/movie.mp4?id=42&hash=abcdef' \
  -o movie.part
```

## CORS and allowed frontend origins

By default (`FRONTEND_URL` unset), the server adds no CORS headers at all — a separate-origin browser frontend cannot read responses via `fetch`/`XHR`, same as before this feature existed. Non-browser clients (native apps, curl, video players, server-to-server calls) are unaffected either way, since they aren't subject to CORS.

Set `FRONTEND_URL` to enable it:

```env
FRONTEND_URL = "https://app.example.com"
# or multiple origins:
FRONTEND_URL = "https://app.example.com,https://staging.example.com"
```

Once set:

- Requests from an allowed `Origin` get `Access-Control-Allow-Origin` echoed back (with credentials enabled), so browser `fetch` calls with cookies work normally.
- `OPTIONS` preflight requests are answered directly.
- A request whose `Origin` header is present but **not** in the allow-list gets `403 Forbidden` — this is a server-side rejection on top of the browser's own CORS enforcement, so a disallowed origin can't trigger side effects (like a mutation route) even with a crafted request, not just fail to read the response.
- Requests with no `Origin` header at all (native apps, curl, media players) pass through unaffected regardless of this setting.

## Rate limiting

Every route is limited per client IP using a fixed-window counter: `RATE_LIMIT_REQUESTS` requests per `RATE_LIMIT_WINDOW` seconds (default `120`/`60`). `POST /login` has its own, stricter window (`LOGIN_RATE_LIMIT_REQUESTS`/`LOGIN_RATE_LIMIT_WINDOW`, default `10`/`60`) to slow down credential brute-forcing. Set either `*_REQUESTS` value to `0` to disable that limit.

Exceeding a limit returns:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 60
Content-Type: application/json

{"error": "rate_limited", "retry_after_seconds": 60}
```

By default, counters are kept in memory per-process — correct for a single instance. Set `REDIS_URL` to share counters (and worker-bot load balancing, see below) across every instance running behind your load balancer.

## Scalability and production notes

- **Health checks**: point your load balancer / orchestrator at `GET /healthz` for liveness and readiness.
- **Horizontal scaling**: worker-bot load balancing and rate limiting both default to in-memory, per-process state, which is correct for one instance but means multiple instances won't coordinate with each other. Set `REDIS_URL` when running more than one instance so they share both.
- **Peer resolution**: every Telegram client (main bot, worker bots, and the optional user session) eagerly resolves all configured channels on startup, and again immediately if you change the channel list via `POST /config`. This avoids `PeerIdInvalid` errors that would otherwise appear the first time a freshly-started or newly-added client is asked to serve a channel it hasn't received a live update from yet.
- **HLS caching**: generated `.m3u8`/`.ts` files are cached to local disk under `cache/hls/`. On a platform with an ephemeral filesystem (e.g. most container platforms' default storage), this cache is lost on every restart and regenerated on next request. For multi-instance or persistent deployments, put a CDN in front of the `hls/*` routes or move the cache to shared/object storage.
- **Error responses**: unhandled server errors always return a generic `{"error": "internal_error"}` body with `500` — the full exception and traceback are logged server-side (not returned to the client), so check your logs rather than the response body when debugging a `500`.

## Notes for building a separate frontend

- Use the backend as a session-cookie service. Log in with `POST /login`, store the returned cookie, and include it on User/Admin routes.
- Public media and thumbnail URLs can be fetched without a login session in the current implementation, but watch/list/search pages require login.
- Browse, search, login, watch, and mutation endpoints return JSON; thumbnail and streaming endpoints return the requested media bytes.
- `POST /send` now requires an admin session, like the other mutation routes.
- If your frontend runs on a different origin than the API, set `FRONTEND_URL` (see [CORS and allowed frontend origins](#cors-and-allowed-frontend-origins)) — otherwise the browser will block the frontend's `fetch`/`XHR` calls from reading the response.
- Every object returned by list/search/browse endpoints follows the shapes in [Response object shapes](#response-object-shapes) — look there instead of guessing field names from an endpoint's example.
- Normalize channel IDs consistently: route URLs and all response objects use the numeric channel ID without `-100`; only Telegram client calls internally use `-100...`.
- Use the JSON authentication status and HTTP status codes directly; no redirect handling is required for API requests.
- For video players and resumable downloaders, prefer the direct `/{chat_id}/{encoded_name}` URL with `Range` requests and handle `206`, `416`, `403`, and `404` explicitly. For broader player compatibility (native HLS support, adaptive players), use `/{chat_id}/{message_id}/hls.m3u8` instead, keeping in mind the first request per file pays a one-time remuxing cost.
