# Sunset DB

Personal multi-language programming quick-reference for **C**, **Go**, **Rust**, and **Python** on **Windows** and **Linux**.

Idiomatic, copy-pasteable snippets so common patterns stay one search away.

Live store is **SQLite** (`data/sunset.db`). `content/topics.json` is the initial seed; it is imported only on first database creation.

## Run

From the project root:

```bash
python server.py
```

On Windows if `python` is missing: `py -3 server.py`.

Then open:

| Page | URL |
|------|-----|
| Search (home) | http://127.0.0.1:8765/ |
| Catalog | http://127.0.0.1:8765/catalog.html |
| Add / Edit | http://127.0.0.1:8765/add.html |
| Delete | http://127.0.0.1:8765/delete.html |

Requires `server.py` (not bare `http.server`) so `/api/topics` and SQLite work. Syntax highlighting uses vendored [highlight.js](https://highlightjs.org/) under `assets/vendor/highlight/` (works offline).

The server listens on `127.0.0.1` only. It serves the app pages and assets, not the database, seed file, or repository files. Browser edits use a token issued to the app page; cross-origin requests cannot use the edit API. This is a local personal app, so other processes running under your account can still access its loopback API.

To back up your current topics as JSON:

```bash
python server.py export data/topics-export.json
```

The export includes edits made in the app. Copy it somewhere safe; `data/*.json` is ignored by Git. To use an export as a fresh seed, copy it to `content/topics.json` before creating a new database.

## API

| Method | Path | Action |
|--------|------|--------|
| `GET` | `/api/topics` | List all topics (JSON array) |
| `GET` | `/api/topics/<id>` | One topic |
| `POST` | `/api/topics` | Create (409 if id exists) |
| `PUT` | `/api/topics/<id>` | Update existing |
| `DELETE` | `/api/topics/<id>` | Delete |

Writes require the `X-Sunset-DB-Token` header, obtained from same-origin `GET /api/session`. Requests with a foreign `Origin` are rejected. Topic payloads must match the schema below; request bodies are limited to 1 MiB.

## Pages

- `index.html` — search home with **language** and **OS** filters
- `catalog.html` — browse every topic
- `topic.html?id=…` — detail view with per-language snippets
- `add.html` — create a new topic or load an id and update it
- `delete.html` — search and delete topics

## Storage

- **SQLite path:** `data/sunset.db` (created on first run)
- On first database creation, import `content/topics.json` and record that seeding has happened. An empty database stays empty after later restarts.
- Existing databases are migrated without reseeding. Local DBs and exports in `data/` are gitignored.
- Nested fields (`tags`, `languages`, `snippets`, `pitfalls`, `references`) are stored as JSON columns

Topic object shape (same as the seed file):

```json
{
  "id": "my-slug",
  "title": "Short Title",
  "slug": "my-slug",
  "category": "io",
  "tags": ["example"],
  "languages": ["c", "go", "rust", "python"],
  "os": "both",
  "summary": "One or two sentences.",
  "when_to_use": "When this pattern applies.",
  "snippets": {
    "go": { "code": "package main\n", "notes": "Optional note." }
  },
  "pitfalls": ["Common mistake"],
  "references": ["https://go.dev/doc/"]
}
```

`os` is `windows`, `linux`, or `both`.

## Layout

```
sunset-db/
  server.py
  tests/
  index.html
  catalog.html
  topic.html
  add.html
  delete.html
  README.md
  LICENSE
  .gitignore
  assets/
    style.css
    app.js
    logo.svg
    logo-mark.svg
    vendor/highlight/…
  content/
    topics.json          # seed / export only
  data/
    .gitkeep
    sunset.db            # local SQLite (gitignored)
```

## License

MIT — see [LICENSE](LICENSE).
