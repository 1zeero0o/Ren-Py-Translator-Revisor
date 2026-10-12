from __future__ import annotations

import re
from html.parser import HTMLParser
from threading import Event

import requests

from .domain import Cancelled, RevisorError, TOKEN, validate_translation


class TranslationHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.found = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if self.depth:
            if tag not in ("br", "img", "input", "hr", "meta", "link"):
                self.depth += 1
            return
        if set(dict(attrs).get("class", "").split()) & {"result-container", "t0"}:
            self.depth = 1
            self.found = True

    def handle_endtag(self, tag):
        if self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)


class GoogleTranslator:
    """Google's public mobile translator, one request per string, HTTPS only."""

    def __init__(self, source="auto", target="pt", session=None):
        self.source = source
        self.target = target
        self.session = session or requests.Session()

    def close(self):
        self.session.close()

    def translate(self, text: str, cancel: Event | None = None) -> str:
        if cancel and cancel.is_set():
            raise Cancelled("Tradução cancelada.")
        tokens = []

        def mask(m):
            tokens.append(m[0])
            return f"ZXQPH{len(tokens) - 1:04d}QXZ"

        masked = TOKEN.sub(mask, text)
        if len(masked) > 4500:
            raise RevisorError("Esta string ultrapassa 4.500 caracteres. Traduza-a manualmente.")
        try:
            r = self.session.get("https://translate.google.com/m", params={"sl": self.source, "tl": self.target, "q": masked},
                                 headers={"User-Agent": "Mozilla/5.0"}, timeout=(8, 20))
            r.raise_for_status()
        except requests.RequestException as exc:
            raise RevisorError(f"Google indisponível: {exc}. O lote foi interrompido; os resultados anteriores foram preservados.") from exc
        if cancel and cancel.is_set():
            raise Cancelled("Tradução cancelada.")
        parser = TranslationHTML()
        parser.feed(r.text)
        result = "".join(parser.parts).strip()
        if not parser.found or not result:
            raise RevisorError("O Google não retornou uma tradução. Pode haver bloqueio, limite de uso ou mudança no serviço.")
        for index, token in enumerate(tokens):
            pattern = re.compile(rf"ZXQPH\s*{index:04d}\s*QXZ", re.IGNORECASE)
            if len(pattern.findall(result)) != 1:
                raise RevisorError("O Google alterou um marcador protegido. A string original foi preservada; revise manualmente.")
            result = pattern.sub(lambda _: token, result)
        validate_translation(text, result)
        return result


def translate_batch(entries, translator, on_result, on_progress, cancel: Event, delay: float = 0.8):
    if not 1 <= len(entries) <= 50:
        raise RevisorError("Marque de 1 a 50 strings por lote.")
    completed = 0
    try:
        for entry in entries:
            if cancel.is_set():
                break
            try:
                target = translator.translate(entry.source, cancel)
            except Cancelled:
                break
            except RevisorError as exc:
                on_result(entry.id, "", str(exc))
                raise
            on_result(entry.id, target, "")
            completed += 1
            on_progress(completed, len(entries), "Traduzindo strings pelo Google…")
            if completed < len(entries) and cancel.wait(delay):
                break
    finally:
        translator.close()
    return completed
