"""verify_deployment.py against a real local HTTP server (no external network)."""
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import verify_deployment as vd


class Handler(BaseHTTPRequestHandler):
    status = 200

    def do_GET(self):
        code = self.server.status_code if self.path == "/healthz" else 404
        self.send_response(code)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):  # keep test output clean
        pass


@pytest.fixture()
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    httpd.status_code = 200
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def base(server):
    return f"http://127.0.0.1:{server.server_address[1]}"


def test_healthy_endpoint_passes(server):
    healthy, message = vd.check_health(base(server) + "/healthz", timeout=2)
    assert healthy and "HTTP 200" in message


@pytest.mark.parametrize("code", [500, 503])
def test_error_status_fails(server, code):
    server.status_code = code
    healthy, message = vd.check_health(base(server) + "/healthz", timeout=2)
    assert not healthy and f"HTTP {code}" in message


def test_unknown_path_fails(server):
    healthy, message = vd.check_health(base(server) + "/other", timeout=2)
    assert not healthy and "HTTP 404" in message


def test_unreachable_host_fails():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # port is free again once the socket closes
    healthy, message = vd.check_health(f"http://127.0.0.1:{port}/healthz", timeout=1)
    assert not healthy and "could not reach" in message


def test_verify_uses_url_from_config(repo, edit_config, server, capsys):
    edit_config(repo, "development", lambda d: d["app"].update(base_url=base(server)))
    assert vd.main(["--environment", "development", "--root", str(repo), "--retries", "1"]) == 0
    assert "verification passed" in capsys.readouterr().out


def test_verify_retries_then_fails(repo, edit_config, server, capsys):
    server.status_code = 503
    edit_config(repo, "development", lambda d: d["app"].update(base_url=base(server)))
    code = vd.main(["--environment", "development", "--root", str(repo), "--retries", "2", "--interval", "0"])
    out = capsys.readouterr().out
    assert code == 1
    assert "attempt 1/2" in out and "attempt 2/2" in out
    assert "development" in out and "docs/rollback.md" not in out  # no rollback hint for development


def test_verify_suggests_rollback_for_production(repo, server, capsys):
    server.status_code = 503
    # production config forbids local URLs, so point the check at the test server with --url
    code = vd.main(["--environment", "production", "--root", str(repo), "--url", base(server) + "/healthz", "--retries", "1"])
    assert code == 1 and "docs/rollback.md" in capsys.readouterr().out


def test_verify_fails_cleanly_on_invalid_config(repo, capsys):
    (repo / "config" / "staging" / "app.yaml").write_text("app: [oops", encoding="utf-8")
    assert vd.main(["--environment", "staging", "--root", str(repo)]) == 1
    assert "invalid YAML format" in capsys.readouterr().out


def test_url_override(server):
    assert vd.verify("production", vd.default_root(), base(server) + "/healthz", retries=1, interval=0) == 0
