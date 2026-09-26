"""HTTP and storage regression tests using a temporary database."""

import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "sunset.db"
        for item in (patch.object(server, "DATA_DIR", Path(self.temp.name)),
                     patch.object(server, "DB_PATH", self.db_path)):
            item.start()
            self.addCleanup(item.stop)
        with closing(server.connect()) as conn:
            server.init_schema(conn)
            server.seed_if_empty(conn)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.http.server_port
        port_patch = patch.object(server, "PORT", self.port)
        port_patch.start()
        self.addCleanup(port_patch.stop)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.http.shutdown()
        self.thread.join()
        self.http.server_close()

    def request(self, path, method="GET", body=None, headers=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                      method=method, headers=headers or {})
        try:
            with urlopen(req, timeout=3) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    def test_static_allowlist_hides_private_files(self):
        for path in ("/", "/index.html", "/assets/style.css"):
            self.assertEqual(self.request(path)[0], 200)
        for path in ("/server.py", "/data/sunset.db", "/content/topics.json",
                     "/.git/config", "/assets/../server.py", "/assets/%2e%2e/server.py"):
            self.assertEqual(self.request(path)[0], 404, path)

    def test_write_requires_token_and_same_origin(self):
        topic = {"id": "new-topic", "title": "New topic", "languages": ["python"]}
        self.assertEqual(self.request("/api/topics", "POST", topic,
                                      {"Content-Type": "application/json"})[0], 403)
        token = json.loads(self.request("/api/session")[1])["edit_token"]
        headers = {"Content-Type": "application/json", "X-Sunset-DB-Token": token}
        self.assertEqual(self.request("/api/topics", "POST", topic,
                                      {**headers, "Origin": "https://example.org"})[0], 403)
        self.assertEqual(self.request("/api/topics", "POST", topic, headers)[0], 201)
        self.assertEqual(self.request("/api/topics/new-topic")[0], 200)
        self.assertEqual(self.request("/api/topics/new-topic", "PUT",
                                      {"title": "Updated"}, headers)[0], 200)
        self.assertEqual(self.request("/api/topics/new-topic", "DELETE",
                                      headers={"X-Sunset-DB-Token": token})[0], 200)
        self.assertEqual(self.request("/api/topics/new-topic")[0], 404)

    def test_invalid_data_returns_400_without_writing(self):
        token = json.loads(self.request("/api/session")[1])["edit_token"]
        headers = {"Content-Type": "application/json", "X-Sunset-DB-Token": token}
        invalid = (
            {"id": 7, "title": "Bad"},
            {"id": "bad", "title": "Bad", "tags": "wrong"},
            {"id": "bad", "title": "Bad", "languages": {"python": 1}},
            {"id": "bad", "title": "Bad", "os": "other"},
            {"id": "bad", "title": "Bad", "references": ["javascript:alert(1)"]},
        )
        for topic in invalid:
            self.assertEqual(self.request("/api/topics", "POST", topic, headers)[0], 400, topic)
        self.assertEqual(self.request("/api/topics/bad")[0], 404)

    def test_seed_only_once_even_when_empty(self):
        with closing(server.connect()) as conn:
            conn.execute("DELETE FROM topics")
            conn.commit()
            self.assertEqual(server.seed_if_empty(conn), 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0], 0)
        with closing(server.connect()) as conn:
            server.init_schema(conn)
            self.assertEqual(server.seed_if_empty(conn), 0)

    def test_export_reflects_database(self):
        output = Path(self.temp.name) / "backup.json"
        count = server.export_topics(output)
        exported = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(count, 32)
        self.assertEqual(len(exported), 32)
        with self.assertRaises(ValueError):
            server.export_topics(self.db_path)


class MigrationTests(unittest.TestCase):
    def test_existing_empty_database_does_not_reseed(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "sunset.db"
            with closing(sqlite3.connect(db)) as conn:
                conn.execute("CREATE TABLE topics (id TEXT PRIMARY KEY)")
                conn.commit()
            with patch.object(server, "DATA_DIR", Path(directory)), patch.object(server, "DB_PATH", db):
                with closing(server.connect()) as conn:
                    server.init_schema(conn)
                    self.assertEqual(server.seed_if_empty(conn), 0)


if __name__ == "__main__":
    unittest.main()
