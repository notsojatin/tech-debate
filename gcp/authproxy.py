"""Authenticated local tunnels to private Cloud Run services.

    python gcp/authproxy.py --sa INVOKER_SA pro=11441=https://... con=11442=https://... judge=11443=https://...

Each mapping listens on 127.0.0.1:<port> and forwards every request to <url> with an ID token for
`--sa` whose audience is that URL, minted by `gcloud auth print-identity-token --impersonate-service-account`.
Tokens stay in this process (never printed or logged) and are refreshed before they expire.

Used instead of `gcloud run services proxy`, whose helper cannot use impersonated credentials, and because
Cloud Run rejected plain user ID tokens for this project.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

import httpx

TOKEN_TTL_S = 45 * 60  # Google ID tokens live 1 h; refresh well before that
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
              "transfer-encoding", "upgrade", "host", "content-length", "content-encoding", "authorization"}


class TokenSource:
    def __init__(self, audience: str, service_account: str, mint: Callable[[str, str], str] | None = None):
        self.audience = audience
        self.service_account = service_account
        self._mint = mint or gcloud_id_token
        self._lock = threading.Lock()
        self._token = ""
        self._expires = 0.0

    def get(self) -> str:
        with self._lock:
            if time.monotonic() >= self._expires:
                self._token = self._mint(self.audience, self.service_account)
                self._expires = time.monotonic() + TOKEN_TTL_S
            return self._token


def gcloud_id_token(audience: str, service_account: str) -> str:
    out = subprocess.run(
        ["gcloud", "auth", "print-identity-token", f"--impersonate-service-account={service_account}",
         f"--audiences={audience}", "--include-email", "--verbosity=error"],
        capture_output=True, text=True,
    )
    if out.returncode != 0 or not out.stdout.strip():
        # stderr names the missing permission; it never contains the token.
        raise RuntimeError(f"could not mint an ID token as {service_account}: {out.stderr.strip()[-400:]}")
    return out.stdout.strip()


def make_handler(upstream: httpx.Client, tokens: TokenSource, name: str):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _forward(self) -> None:
            t0 = time.monotonic()
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
            try:
                headers["Authorization"] = f"Bearer {tokens.get()}"
                r = upstream.request(self.command, self.path, content=body, headers=headers)
                status, payload, out_headers = r.status_code, r.content, r.headers
            except (httpx.HTTPError, RuntimeError) as e:
                status, payload, out_headers = 502, f"authproxy: {e}".encode(), {}
            self.send_response(status)
            for k, v in out_headers.items():
                if k.lower() not in HOP_BY_HOP:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            print(f"[{name}] {self.command} {self.path} -> {status} in {time.monotonic() - t0:.1f}s", flush=True)

        do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = _forward

        def log_message(self, *args) -> None:  # one line per request is printed by _forward
            pass

    return Handler


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--sa", required=True, help="service account to impersonate (has run.invoker)")
    p.add_argument("--timeout", type=float, default=900)
    p.add_argument("mappings", nargs="+", help="name=port=https://service-url")
    args = p.parse_args(argv)

    servers = []
    for m in args.mappings:
        name, port, url = m.split("=", 2)
        tokens = TokenSource(url, args.sa)
        try:
            tokens.get()  # fail fast, before anything listens
        except RuntimeError as e:
            sys.exit(str(e))
        upstream = httpx.Client(base_url=url, timeout=args.timeout)
        server = ThreadingHTTPServer(("127.0.0.1", int(port)), make_handler(upstream, tokens, name))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        print(f"{name}: http://localhost:{port} -> {url}", flush=True)
    print("authproxy ready", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        for s in servers:
            s.shutdown()


if __name__ == "__main__":
    main()
