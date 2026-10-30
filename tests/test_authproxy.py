import importlib.util
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx

spec = importlib.util.spec_from_file_location("authproxy", Path(__file__).parent.parent / "gcp" / "authproxy.py")
authproxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(authproxy)


def serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_forwards_with_token_and_strips_client_auth():
    seen = []

    def upstream(req):
        seen.append(req)
        return httpx.Response(200, json={"ok": True})

    minted = []
    tokens = authproxy.TokenSource("https://svc.run.app", "sa@x", mint=lambda aud, sa: minted.append(aud) or "TKN")
    client = httpx.Client(transport=httpx.MockTransport(upstream), base_url="https://svc.run.app")
    server, url = serve(authproxy.make_handler(client, tokens, "judge"))
    try:
        r = httpx.post(f"{url}/api/chat", json={"m": 1}, headers={"Authorization": "Bearer user", "Host": "evil"})
        r2 = httpx.get(f"{url}/api/version")
    finally:
        server.shutdown()
    assert r.status_code == 200 and r.json() == {"ok": True} and r2.status_code == 200
    assert seen[0].headers["authorization"] == "Bearer TKN"
    assert seen[0].url.host == "svc.run.app" and seen[0].url.path == "/api/chat"
    assert seen[0].content == b'{"m":1}' or b'"m"' in seen[0].content
    assert minted == ["https://svc.run.app"]  # token cached across requests


def test_token_failure_becomes_502():
    def boom(aud, sa):
        raise RuntimeError("denied")

    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)), base_url="https://s")
    server, url = serve(authproxy.make_handler(client, authproxy.TokenSource("https://s", "sa", mint=boom), "pro"))
    try:
        r = httpx.get(f"{url}/api/version")
    finally:
        server.shutdown()
    assert r.status_code == 502 and b"denied" in r.content
