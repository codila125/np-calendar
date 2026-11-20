"""Shared requests-like fakes for the fetch and CLI tests."""

import json


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)


class FakeSession:
    """A requests-like session that serves canned responses and records every call.

    A route may be a single response (served forever) or a list consumed in order,
    which lets tests drive the retry loop (e.g. ``[500, 200]``). An exception in a
    route is raised by ``get`` to simulate a connection error.
    """

    def __init__(self, routes):
        self._remaining = {
            url: (list(v) if isinstance(v, list) else [v]) for url, v in routes.items()
        }
        self.calls = []

    def get(self, url, headers=None, timeout=None, **kwargs):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        seq = self._remaining[url]
        item = seq[0]
        if len(seq) > 1:
            seq.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item
