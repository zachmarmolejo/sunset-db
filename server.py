#!/usr/bin/env python3
"""Sunset DB — stdlib HTTP server with SQLite storage."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "sunset.db"
SEED_PATH = ROOT / "content" / "topics.json"
PORT = 8765

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


def topic_to_params(topic: dict) -> tuple:
    tid = (topic.get("id") or "").strip()
    if not tid:
        raise ValueError("topic id is required")
    slug = (topic.get("slug") or tid).strip()
    return (
        tid,
        topic.get("title") or "",
        slug,
        topic.get("category") or "",
        json.dumps(topic.get("tags") or [], ensure_ascii=False),
        json.dumps(topic.get("languages") or [], ensure_ascii=False),
        topic.get("os") or "both",
        topic.get("summary") or "",
        topic.get("when_to_use") or "",
        json.dumps(topic.get("snippets") or {}, ensure_ascii=False),
        json.dumps(topic.get("pitfalls") or [], ensure_ascii=False),
        json.dumps(topic.get("references") or [], ensure_ascii=False),
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
    count = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
    if count > 0:
        return count
    if not SEED_PATH.is_file():
        return 0
    with SEED_PATH.open(encoding="utf-8") as f:
        topics = json.load(f)
    if not isinstance(topics, list):
        raise ValueError("content/topics.json must be a JSON array")
    for t in topics:
        insert_topic(conn, t)
    conn.commit()
    return len(topics)


def list_topics(conn: sqlite3.Connection) -> list:
    rows = conn.execute("SELECT * FROM topics ORDER BY title COLLATE NOCASE").fetchall()
    return [row_to_topic(r) for r in rows]


def get_topic(conn: sqlite3.Connection, topic_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    return row_to_topic(row) if row else None


def create_topic(conn: sqlite3.Connection, topic: dict) -> dict:
    tid = (topic.get("id") or "").strip()
    if not tid:
        raise ValueError("topic id is required")
    existing = get_topic(conn, tid)
    if existing:
        raise LookupError(f"topic id already exists: {tid}")
    insert_topic(conn, topic)
    conn.commit()
    return get_topic(conn, tid)


def update_topic(conn: sqlite3.Connection, topic_id: str, topic: dict) -> dict:
    existing = get_topic(conn, topic_id)
    if existing is None:
        raise LookupError(f"topic not found: {topic_id}")
    # Keep path id authoritative; allow body id only if it matches
    body_id = (topic.get("id") or topic_id).strip()
    if body_id != topic_id:
        raise ValueError("body id must match URL id (id is immutable)")
    merged = {**existing, **topic, "id": topic_id}
    if not merged.get("slug"):
        merged["slug"] = topic_id
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


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON body: {e}") from e
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        m = re.fullmatch(r"/api/topics(?:/([^/]+))?", path)
        if not m:
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
