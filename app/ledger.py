"""Evidence ledger: every snippet a debater may cite, with a stable ID (E1, E2, ...)."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel

Side = Literal["pro", "con"]

_CITE_RE = re.compile(r"E\d+")


class Evidence(BaseModel):
    id: str
    side: Side
    query: str
    url: str
    title: str
    snippet: str

    @property
    def domain(self) -> str:
        return domain_of(self.url)


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def normalize_cite(raw: str) -> str:
    """'[e3]', '(E3)', 'E3' -> 'E3'; anything else is returned stripped."""
    m = _CITE_RE.search(raw.strip().upper())
    return m.group(0) if m else raw.strip()


class Ledger(BaseModel):
    items: list[Evidence] = []

    def add(self, side: Side, query: str, url: str, title: str, snippet: str) -> Evidence:
        ev = Evidence(id=f"E{len(self.items) + 1}", side=side, query=query, url=url,
                      title=title, snippet=snippet)
        self.items.append(ev)
        return ev

    def ids(self) -> set[str]:
        return {e.id for e in self.items}

    def get(self, eid: str) -> Evidence | None:
        return next((e for e in self.items if e.id == eid), None)

    def has_url(self, url: str) -> bool:
        return any(e.url == url for e in self.items)

    def for_side(self, side: Side, limit: int) -> list[Evidence]:
        return [e for e in self.items if e.side == side][:limit]
