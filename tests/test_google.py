import html
from threading import Event

import pytest
import requests

from renpy_revisor.domain import Entry, RevisorError
from renpy_revisor.google import GoogleTranslator, translate_batch


class Session:
    def __init__(self, respond):
        self.respond = respond
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.respond(kwargs["params"]["q"])

    def close(self):
        self.closed = True


def response(body, status=200):
    r = requests.Response()
    r.status_code = status
    r._content = body.encode("utf-8")
    r.encoding = "utf-8"
    return r


def test_google_masks_and_restores_renpy_interpolation_and_tags():
    session = Session(lambda q: response('<div class="result-container">' + html.escape(q.replace("Hello", "Olá")) + '</div>'))
    translator = GoogleTranslator(session=session)
    assert translator.translate('Hello [inventory[0]!q] {b}friend{/b}\n%s') == 'Olá [inventory[0]!q] {b}friend{/b}\n%s'
    url, kwargs = session.calls[0]
    assert url.startswith("https://") and "[inventory" not in kwargs["params"]["q"]
    assert kwargs["timeout"] == (8, 20)


def test_changed_placeholder_and_consent_page_are_errors():
    translator = GoogleTranslator(session=Session(lambda q: response('<div class="result-container">Olá</div>')))
    with pytest.raises(RevisorError, match="marcador"):
        translator.translate("Hello [name]")
    translator = GoogleTranslator(session=Session(lambda q: response('<html>Accept cookies</html>')))
    with pytest.raises(RevisorError, match="não retornou"):
        translator.translate("Hello")


def test_batch_sequence_cap_cancel_and_partial_results():
    session = Session(lambda q: response('<div class="result-container">' + q + '</div>'))
    translator = GoogleTranslator(session=session)
    entries = [Entry(str(i), f"String {i}", "script.rpy", i, "string") for i in range(50)]
    results = []
    event = Event()
    def received(*args):
        results.append(args)
        if len(results) == 3: event.set()
    count = translate_batch(entries, translator, received, lambda *args: None, event, delay=0)
    assert count == 3 and len(session.calls) == 3 and session.closed
    with pytest.raises(RevisorError, match="50"):
        translate_batch(entries + [entries[0]], translator, received, lambda *args: None, Event())


def test_rate_limit_stops_batch_preserving_successful_results():
    count = 0
    def respond(q):
        nonlocal count
        count += 1
        return response('<div class="t0">Oi</div>') if count == 1 else response("Rate limit", 429)
    session = Session(respond)
    entries = [Entry(str(i), "Hello", "script.rpy", i, "string") for i in range(3)]
    results = []
    with pytest.raises(RevisorError, match="Google indisponível"):
        translate_batch(entries, GoogleTranslator(session=session), lambda *a: results.append(a), lambda *a: None, Event(), 0)
    assert len(session.calls) == 2 and results[0] == ("0", "Oi", "") and results[1][0] == "1"
    assert results[1][2] and session.closed
