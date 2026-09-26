#!/usr/bin/env python3
"""Sunset DB — stdlib HTTP server with SQLite storage."""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import sys
import tempfile
from contextlib import closing
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "sunset.db"
SEED_PATH = ROOT / "content" / "topics.json"
PORT = 8765
MAX_BODY_BYTES = 1024 * 1024
EDIT_TOKEN = secrets.token_urlsafe(32)
PUBLIC_PAGES = {"/", "/index.html", "/catalog.html", "/topic.html", "/add.html", "/delete.html"}
PUBLIC_ASSET_SUFFIXES = {".css", ".js", ".svg"}
LANGUAGES = {"c", "go", "rust", "python"}
ALLOWED_ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}

TOPIC_FIELDS = (
    "id", "title", "slug", "category", "tags", "languages",
    "os", "summary", "when_to_use", "snippets", "pitfalls", "references",
)
JSON_FIELDS = ("tags", "languages", "snippets", "pitfalls", "references")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    had_topics = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'topics'"
    ).fetchone() is not None
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS topics (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            slug TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            languages_json TEXT NOT NULL DEFAULT '[]',
            os TEXT NOT NULL DEFAULT 'both',
            summary TEXT NOT NULL DEFAULT '',
            when_to_use TEXT NOT NULL DEFAULT '',
            snippets_json TEXT NOT NULL DEFAULT '{}',
            pitfalls_json TEXT NOT NULL DEFAULT '[]',
            references_json TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    conn.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    if had_topics:
        conn.execute("INSERT OR IGNORE INTO app_meta VALUES ('seeded', '1')")
    conn.commit()


def row_to_topic(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "slug": row["slug"],
        "category": row["category"],
        "tags": json.loads(row["tags_json"] or "[]"),
        "languages": json.loads(row["languages_json"] or "[]"),
        "os": row["os"],
        "summary": row["summary"],
        "when_to_use": row["when_to_use"],
        "snippets": json.loads(row["snippets_json"] or "{}"),
        "pitfalls": json.loads(row["pitfalls_json"] or "[]"),
        "references": json.loads(row["references_json"] or "[]"),
    }


def validate_topic(topic: dict) -> dict:
    if not isinstance(topic, dict):
        raise ValueError("topic must be an object")
    unknown = set(topic) - set(TOPIC_FIELDS)
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(sorted(unknown))}")
    result = {}
    for field in ("id", "title", "slug", "category", "os", "summary", "when_to_use"):
        value = topic.get(field)
        if value is None and field not in ("id", "title"):
            value = ""
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        result[field] = value.strip() if field in ("id", "title", "slug", "category", "os") else value
    if not re.fullmatch(r"[a-z0-9-]{1,128}", result["id"]):
        raise ValueError("id must be 1-128 lowercase letters, digits, or hyphens")
    if not result["title"]:
        raise ValueError("title is required")
    result["slug"] = result["slug"] or result["id"]
    result["os"] = result["os"] or "both"
    if result["os"] not in {"both", "windows", "linux"}:
        raise ValueError("os must be both, windows, or linux")
    for field in ("tags", "languages", "pitfalls", "references"):
        value = topic.get(field, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(f"{field} must be an array of strings")
        result[field] = value
    if any(lang not in LANGUAGES for lang in result["languages"]):
        raise ValueError("languages contains an unsupported language")
    for ref in result["references"]:
        parsed = urlparse(ref)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("references must be HTTP or HTTPS URLs")
    snippets = topic.get("snippets", {})
    if not isinstance(snippets, dict) or any(lang not in LANGUAGES for lang in snippets):
        raise ValueError("snippets must be an object keyed by supported language")
    for lang, snippet in snippets.items():
        if (not isinstance(snippet, dict) or set(snippet) - {"code", "notes"}
                or not isinstance(snippet.get("code", ""), str)
                or not isinstance(snippet.get("notes", ""), str)):
            raise ValueError(f"snippets.{lang} must contain string code and notes")
    result["snippets"] = snippets
    return result


def topic_to_params(topic: dict) -> tuple:
    topic = validate_topic(topic)
    return (
        topic["id"], topic["title"], topic["slug"], topic["category"],
        json.dumps(topic["tags"], ensure_ascii=False),
        json.dumps(topic["languages"], ensure_ascii=False), topic["os"],
        topic["summary"], topic["when_to_use"],
        json.dumps(topic["snippets"], ensure_ascii=False),
        json.dumps(topic["pitfalls"], ensure_ascii=False),
        json.dumps(topic["references"], ensure_ascii=False),
    )


def insert_topic(conn: sqlite3.Connection, topic: dict) -> None:
    params = topic_to_params(topic)
    conn.execute(
        """
        INSERT INTO topics (
            id, title, slug, category, tags_json, languages_json, os,
            summary, when_to_use, snippets_json, pitfalls_json, references_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        params,
    )


def seed_if_empty(conn: sqlite3.Connection) -> int:
    if conn.execute("SELECT 1 FROM app_meta WHERE key = 'seeded'").fetchone():
        return 0
    topics = []
    if SEED_PATH.is_file():
        with SEED_PATH.open(encoding="utf-8") as f:
            topics = json.load(f)
        if not isinstance(topics, list):
            raise ValueError("content/topics.json must be a JSON array")
    with conn:
        for topic in topics:
            insert_topic(conn, topic)
        conn.execute("INSERT INTO app_meta VALUES ('seeded', '1')")
    return len(topics)


def list_topics(conn: sqlite3.Connection) -> list:
    rows = conn.execute("SELECT * FROM topics ORDER BY title COLLATE NOCASE").fetchall()
    return [row_to_topic(r) for r in rows]


def get_topic(conn: sqlite3.Connection, topic_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    return row_to_topic(row) if row else None


def create_topic(conn: sqlite3.Connection, topic: dict) -> dict:
    params = topic_to_params(topic)
    tid = params[0]
    try:
        insert_topic(conn, topic)
    except sqlite3.IntegrityError as exc:
        raise LookupError(f"topic id already exists: {tid}") from exc
    conn.commit()
    return get_topic(conn, tid)


def update_topic(conn: sqlite3.Connection, topic_id: str, topic: dict) -> dict:
    existing = get_topic(conn, topic_id)
    if existing is None:
        raise LookupError(f"topic not found: {topic_id}")
    # Keep path id authoritative; allow body id only if it matches
    body_id = topic.get("id", topic_id)
    if not isinstance(body_id, str):
        raise ValueError("id must be a string")
    if body_id != topic_id:
        raise ValueError("body id must match URL id (id is immutable)")
    merged = {**existing, **topic, "id": topic_id}
    params = topic_to_params(merged)
    # params[0] is id — skip it for SET
    conn.execute(
        """
        UPDATE topics SET
            title = ?, slug = ?, category = ?, tags_json = ?, languages_json = ?,
            os = ?, summary = ?, when_to_use = ?, snippets_json = ?,
            pitfalls_json = ?, references_json = ?
        WHERE id = ?
        """,
        params[1:] + (topic_id,),
    )
    conn.commit()
    return get_topic(conn, topic_id)


def delete_topic(conn: sqlite3.Connection, topic_id: str) -> bool:
    cur = conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
    conn.commit()
    return cur.rowcount > 0


def export_topics(path: Path) -> int:
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"database not found: {DB_PATH}")
    path = path.expanduser().resolve()
    if path == DB_PATH.resolve():
        raise ValueError("export path must not be the database file")
    with closing(connect()) as conn:
        topics = list_topics(conn)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".sunset-export-", suffix=".tmp", delete=False) as f:
            temp_path = Path(f.name)
            json.dump(topics, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return len(topics)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self) -> bool:
        if self.headers.get("Host") in {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}:
            return True
        self._json(403, {"error": "invalid host"})
        return False

    def _write_ok(self) -> bool:
        if not self._host_ok():
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in ALLOWED_ORIGINS:
            self._json(403, {"error": "invalid origin"})
            return False
        if self.headers.get("X-Sunset-DB-Token") != EDIT_TOKEN:
            self._json(403, {"error": "missing or invalid edit token"})
            return False
        return True

    def _public_path(self, path: str) -> bool:
        if path in PUBLIC_PAGES:
            return True
        if not path.startswith("/assets/") or "\\" in path:
            return False
        parts = path.split("/")[1:]
        if any(part in {"", ".", ".."} or part.startswith(".") for part in parts):
            return False
        target = (ROOT / path.lstrip("/")).resolve()
        return (target.is_relative_to((ROOT / "assets").resolve())
                and target.is_file() and target.suffix in PUBLIC_ASSET_SUFFIXES)

    def _read_json(self) -> dict:
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError as exc:
            raise ValueError("valid Content-Length is required") from exc
        if length < 1 or length > MAX_BODY_BYTES:
            raise ValueError(f"body must be 1-{MAX_BODY_BYTES} bytes")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"invalid JSON body: {e}") from e
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_OPTIONS(self) -> None:
        self._json(405, {"error": "CORS preflight is not supported"})

    def do_HEAD(self) -> None:
        if not self._host_ok():
            return
        path = unquote(urlparse(self.path).path)
        if not self._public_path(path):
            self.send_error(404, "not found")
            return
        super().do_HEAD()

    def do_GET(self) -> None:
        if not self._host_ok():
            return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/session":
            self._json(200, {"edit_token": EDIT_TOKEN})
            return
        m = re.fullmatch(r"/api/topics(?:/([^/]+))?", path)
        if not m:
            if not self._public_path(path):
                self.send_error(404, "not found")
                return
            return super().do_GET()
        topic_id = m.group(1)
        conn = connect()
        try:
            if topic_id is None:
                self._json(200, list_topics(conn))
            else:
                topic = get_topic(conn, topic_id)
                if topic is None:
                    self._json(404, {"error": "not found"})
                else:
                    self._json(200, topic)
        finally:
            conn.close()

    def do_POST(self) -> None:
        if not self._write_ok():
            return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path != "/api/topics":
            self._json(404, {"error": "not found"})
            return
        conn = connect()
        try:
            try:
                body = self._read_json()
                topic = create_topic(conn, body)
            except LookupError as e:
                self._json(409, {"error": str(e)})
                return
            except ValueError as e:
                self._json(400, {"error": str(e)})
                return
            self._json(201, topic)
        finally:
            conn.close()


    def do_PUT(self) -> None:
        if not self._write_ok():
            return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        m = re.fullmatch(r"/api/topics/([^/]+)", path)
        if not m:
            self._json(404, {"error": "not found"})
            return
        topic_id = m.group(1)
        conn = connect()
        try:
            try:
                body = self._read_json()
                topic = update_topic(conn, topic_id, body)
            except LookupError as e:
                self._json(404, {"error": str(e)})
                return
            except ValueError as e:
                self._json(400, {"error": str(e)})
                return
            self._json(200, topic)
        finally:
            conn.close()

    def do_DELETE(self) -> None:
        if not self._write_ok():
            return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        m = re.fullmatch(r"/api/topics/([^/]+)", path)
        if not m:
            self._json(404, {"error": "not found"})
            return
        topic_id = m.group(1)
        conn = connect()
        try:
            if delete_topic(conn, topic_id):
                self._json(200, {"ok": True, "id": topic_id})
            else:
                self._json(404, {"error": "not found"})
        finally:
            conn.close()


def main() -> None:
    if len(sys.argv) > 1:
        if len(sys.argv) != 3 or sys.argv[1] != "export":
            raise SystemExit("Usage: python server.py [export OUTPUT.json]")
        count = export_topics(Path(sys.argv[2]))
        print(f"Exported {count} topics to {sys.argv[2]}")
        return
    conn = connect()
    try:
        init_schema(conn)
        n = seed_if_empty(conn)
        total = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
    finally:
        conn.close()

    os.chdir(ROOT)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Sunset DB → http://127.0.0.1:{PORT}/", flush=True)
    print(f"SQLite: {DB_PATH} ({total} topics" + (f", seeded {n}" if n else "") + ")", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
