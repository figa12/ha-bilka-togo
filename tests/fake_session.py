"""A stand-in for aiohttp.ClientSession that answers from a script and records each call.

aioresponses does not work with aiohttp 3.14, which Home Assistant 2026.9 ships. The client
only ever uses `session.get` and `session.post` as context managers, so this is enough.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from yarl import URL


@dataclass
class Call:
    method: str
    url: str
    params: dict[str, str]
    headers: dict[str, str]
    data: Any


@dataclass
class _Route:
    method: str
    pattern: re.Pattern[str]
    payload: Any
    status: int
    repeat: bool


class _Response:
    def __init__(self, url: str, payload: Any, status: int) -> None:
        self.url = URL(url)
        self.status = status
        self._payload = payload

    async def json(self, content_type: str | None = None) -> Any:
        return json.loads(json.dumps(self._payload))

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@dataclass
class FakeSession:
    calls: list[Call] = field(default_factory=list)
    _routes: list[_Route] = field(default_factory=list)

    def answer(self, method: str, url: str, payload: Any, *, status: int = 200, repeat: bool = False) -> None:
        """Answer the next matching call; routes are used in the order they were added."""
        self._routes.append(_Route(method, re.compile(url), payload, status, repeat))

    def get(self, url: str, **kwargs: Any) -> _Response:
        return self._call("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> _Response:
        return self._call("POST", url, **kwargs)

    def to(self, fragment: str) -> list[Call]:
        """The calls whose URL contains a fragment."""
        return [call for call in self.calls if fragment in call.url]

    def _call(self, method: str, url: str, *, params=None, headers=None, data=None, timeout=None) -> _Response:
        self.calls.append(Call(method, url, dict(params or {}), dict(headers or {}), data))
        for route in self._routes:
            if route.method == method and route.pattern.search(url):
                if not route.repeat:
                    self._routes.remove(route)
                return _Response(url, route.payload, route.status)
        raise AssertionError(f"Unexpected {method} {url}")
