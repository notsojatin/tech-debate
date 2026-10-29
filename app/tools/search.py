"""SearXNG search, page fetching and extraction, with an on-disk cache and a replay mode."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.config import Config
from app.ledger import domain_of

USER_AGENT = "tech-debate/0.1 (+https://github.com/; local research bot)"
_WORD_RE = re.compile(r"[a-z0-9]+")


class CacheMiss(RuntimeError):
    pass


class DiskCache:
    """JSON-file cache keyed by (kind, key). In replay mode a miss is an error."""

    def __init__(self, root: Path, replay: bool = False):
        self.root = root
        self.replay = replay
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, kind: str, key: str) -> Path:
        h = hashlib.sha256(f"{kind}\x00{key}".encode()).hexdigest()
        return self.root / kind / f"{h}.json"

    def get(self, kind: str, key: str) -> Any | None:
        p = self._path(kind, key)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))["value"]
        if self.replay:
            raise CacheMiss(f"replay mode: no cached {kind} for {key!r}")
        return None

    def put(self, kind: str, key: str, value: Any) -> None:
        p = self._path(kind, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"key": key, "value": value}, ensure_ascii=False), encoding="utf-8")


@dataclass
class Found:
    query: str
    url: str
    title: str
    snippet: str


class Researcher(Protocol):
    def research(self, topic: str, queries: list[str], exclude_urls: set[str]) -> list[Found]: ...


def clean_snippet(text: str) -> str:
    # Angle brackets would let a page close our <evidence> wrapper; drop them.
    text = text.replace("<", " ").replace(">", " ")
    return re.sub(r"\s+", " ", text).strip()


def best_passage(text: str, terms: set[str], max_chars: int) -> str:
    """Pick the paragraphs that share the most terms with the query, keeping page order."""
    paras = [p.strip() for p in text.split("\n") if len(p.strip()) > 40]
    if not paras:
        return clean_snippet(text)[:max_chars]
    scored = sorted(
        range(len(paras)),
        key=lambda i: -len(terms & set(_WORD_RE.findall(paras[i].lower()))),
    )
    chosen: list[int] = []
    total = 0
    for i in scored:
        if total >= max_chars:
            break
        chosen.append(i)
        total += len(paras[i]) + 1
    out = clean_snippet(" ".join(paras[i] for i in sorted(chosen)))
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0] + " …"
    return out


class SearxResearcher:
    def __init__(self, cfg: Config, cache: DiskCache, http: httpx.Client | None = None):
        self.cfg = cfg
        self.rc = cfg.research
        self.cache = cache
        self.http = http or httpx.Client(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=self.rc.fetch_timeout_s
        )

    # -- search

    def search(self, query: str) -> list[dict]:
        cached = self.cache.get("search", query)
        if cached is not None:
            return cached
        url = f"{self.cfg.services.searxng_url}/search"
        params = {"q": query, "format": "json", "language": "en", "safesearch": 1}
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = self.http.get(url, params=params, timeout=self.rc.search_timeout_s)
                r.raise_for_status()
                results = [
                    {"url": x["url"], "title": x.get("title", ""), "content": x.get("content", "")}
                    for x in r.json().get("results", [])
                    if x.get("url", "").startswith("http")
                ]
                if results:
                    self.cache.put("search", query, results)
                    return results
                last = RuntimeError("no results (engines may be rate-limited)")
            except (httpx.HTTPError, ValueError) as e:
                last = e
            time.sleep(1.5 * (attempt + 1))
        print(f"  ! search failed for {query!r}: {last}")
        return []

    # -- fetch

    def fetch_text(self, url: str) -> str | None:
        cached = self.cache.get("page", url)
        if cached is not None:
            return cached.get("text")
        text = self._fetch_uncached(url)
        self.cache.put("page", url, {"text": text})
        return text

    def _fetch_uncached(self, url: str) -> str | None:
        import trafilatura

        try:
            with self.http.stream("GET", url) as r:
                if r.status_code != 200:
                    return None
                ctype = r.headers.get("content-type", "")
                if "html" not in ctype and "text" not in ctype:
                    return None
                chunks: list[bytes] = []
                size = 0
                for chunk in r.iter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > self.rc.max_page_bytes:
                        break
                html = b"".join(chunks).decode(r.encoding or "utf-8", errors="replace")
        except httpx.HTTPError:
            return None
        text = trafilatura.extract(html, include_comments=False, include_tables=False, favor_precision=True)
        return text[:20000] if text else None

    # -- research

    def research(self, topic: str, queries: list[str], exclude_urls: set[str]) -> list[Found]:
        found: list[Found] = []
        seen = set(exclude_urls)
        for q in queries:
            terms = set(_WORD_RE.findall(f"{q} {topic}".lower()))
            domains: set[str] = set()
            fetched = 0
            for res in self.search(q)[: self.rc.results_per_query]:
                url, dom = res["url"], domain_of(res["url"])
                if url in seen or dom in domains:
                    continue
                seen.add(url)
                domains.add(dom)
                snippet = ""
                if fetched < self.rc.fetch_per_query:
                    fetched += 1
                    text = self.fetch_text(url)
                    if text:
                        snippet = best_passage(text, terms, self.rc.snippet_chars)
                if not snippet:
                    snippet = clean_snippet(res.get("content", ""))[: self.rc.snippet_chars]
                if len(snippet) < 40:
                    continue
                found.append(Found(query=q, url=url, title=clean_snippet(res.get("title", "")), snippet=snippet))
        return found
