# Sunset DB

Personal multi-language programming quick-reference for **C**, **Go**, **Rust**, and **Python** on **Windows** and **Linux**.

Idiomatic, copy-pasteable snippets so common patterns stay one search away.

## Run

From the project root:

```bash
python -m http.server 8765
```

Then open:

| Page | URL |
|------|-----|
| Search (home) | http://127.0.0.1:8765/ |
| Catalog | http://127.0.0.1:8765/catalog.html |

`file://` will not load JSON — use the HTTP server. If `python` is missing on Windows: `py -3 -m http.server 8765`.

Syntax highlighting uses vendored [highlight.js](https://highlightjs.org/) under `assets/vendor/highlight/` (works offline).

## Pages

- `index.html` — search home with **language** and **OS** filters
- `catalog.html` — browse every topic
- `topic.html?id=…` — detail view with per-language snippets

## Add a topic

Edit `content/topics.json` (append an object; keep valid JSON):

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

`os` is `windows`, `linux`, or `both`. Skip a language only when it truly does not apply and say so in `notes`. Hard-refresh the browser after saving.

## Layout

```
sunset-db/
  index.html
  catalog.html
  topic.html
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
    topics.json
```

## License

MIT — see [LICENSE](LICENSE).
