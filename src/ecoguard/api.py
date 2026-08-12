"""Small dependency-free HTTP boundary for local EcoGuard verification.

This module deliberately exposes only deterministic, side-effect-free stages.  It is
an integration example for reviewers, not an authenticated production service.
"""

from __future__ import annotations

import argparse
import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Callable, Iterable, Sequence
from wsgiref.simple_server import make_server

from . import __version__
from .cbam import calculate_exposure
from .jsonio import strict_json_loads
from .legal import LegalRetriever, validate_source_manifest


API_VERSION = "1"
MAX_REQUEST_BYTES = 1_000_000
MAX_QUERY_CHARACTERS = 8_000
JSON_CONTENT_TYPE = "application/json; charset=utf-8"

StartResponse = Callable[[str, list[tuple[str, str]]], Any]


class UnsupportedMediaTypeError(Exception):
    """The request is not JSON."""


class RequestTooLargeError(Exception):
    """The request exceeds the local integration boundary."""


def _strict_json(raw: bytes) -> Any:
    return strict_json_loads(raw)


def _json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _response(
    start_response: StartResponse,
    status: str,
    payload: Any,
    *,
    extra_headers: Iterable[tuple[str, str]] = (),
) -> list[bytes]:
    body = _json_bytes(payload)
    headers = [
        ("Content-Type", JSON_CONTENT_TYPE),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"),
        *extra_headers,
    ]
    start_response(status, headers)
    return [body]


def _error(start_response: StartResponse, status: str, code: str, detail: str):
    return _response(
        start_response,
        status,
        {
            "api_version": API_VERSION,
            "error": {"code": code, "detail": detail},
        },
    )


def _request_json(environ: dict[str, Any]) -> Any:
    content_type = environ.get("CONTENT_TYPE", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise UnsupportedMediaTypeError("Content-Type must be application/json")

    raw_length = environ.get("CONTENT_LENGTH", "")
    if raw_length:
        try:
            content_length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Content-Length must be an integer") from exc
        if content_length < 0:
            raise ValueError("Content-Length must not be negative")
        if content_length > MAX_REQUEST_BYTES:
            raise RequestTooLargeError("request body exceeds 1000000 bytes")
        raw = environ["wsgi.input"].read(content_length)
    else:
        raw = environ["wsgi.input"].read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise RequestTooLargeError("request body exceeds 1000000 bytes")
    if not raw:
        raise ValueError("request body must not be empty")
    return _strict_json(raw)


def _resource_json(name: str) -> Any:
    resource = files("ecoguard.resources").joinpath(name)
    return _strict_json(resource.read_bytes())


@lru_cache(maxsize=1)
def _legal_retriever() -> LegalRetriever:
    corpus = _resource_json("legal_corpus.json")
    source_manifest = _resource_json("source_manifest.json")
    validate_source_manifest(corpus, source_manifest)
    return LegalRetriever(corpus)


def _legal_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("legal request must be a JSON object")
    if set(payload) - {"query", "limit"}:
        raise ValueError("legal request contains unsupported keys")
    query = payload.get("query")
    limit = payload.get("limit", 3)
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-blank string")
    if len(query) > MAX_QUERY_CHARACTERS:
        raise ValueError(f"query must not exceed {MAX_QUERY_CHARACTERS} characters")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
        raise ValueError("limit must be an integer from 1 to 10")
    return _legal_retriever().retrieve(query, limit=limit)


def application(environ: dict[str, Any], start_response: StartResponse):
    """Serve the local verification API as a PEP 3333 WSGI application."""
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "")

    if path == "/health":
        if method != "GET":
            return _error(
                start_response,
                "405 Method Not Allowed",
                "method_not_allowed",
                "use GET for /health",
            )
        return _response(
            start_response,
            "200 OK",
            {
                "api_version": API_VERSION,
                "package_version": __version__,
                "production_ready": False,
                "service": "ecoguard-local-verification-api",
                "status": "ok",
            },
        )

    routes = {
        "/v1/cbam/calculate": calculate_exposure,
        "/v1/legal/retrieve": _legal_payload,
    }
    handler = routes.get(path)
    if handler is None:
        return _error(
            start_response,
            "404 Not Found",
            "not_found",
            "unknown API path",
        )
    if method != "POST":
        return _error(
            start_response,
            "405 Method Not Allowed",
            "method_not_allowed",
            "use POST for this endpoint",
        )

    try:
        payload = _request_json(environ)
    except UnsupportedMediaTypeError as exc:
        return _error(
            start_response,
            "415 Unsupported Media Type",
            "unsupported_media_type",
            str(exc),
        )
    except RequestTooLargeError as exc:
        return _error(
            start_response,
            "413 Content Too Large",
            "request_too_large",
            str(exc),
        )
    except (RecursionError, UnicodeDecodeError, ValueError) as exc:
        return _error(
            start_response,
            "422 Unprocessable Content",
            "invalid_evidence",
            str(exc),
        )

    try:
        result = handler(payload)
    except (AttributeError, KeyError, RecursionError, TypeError, ValueError) as exc:
        return _error(
            start_response,
            "422 Unprocessable Content",
            "invalid_evidence",
            str(exc),
        )

    return _response(
        start_response,
        "200 OK",
        {
            "api_version": API_VERSION,
            "human_review_required": True,
            "result": result,
        },
    )


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be from 1 to 65535")
    return port


def _loopback_host(value: str) -> str:
    if value != "127.0.0.1":
        raise argparse.ArgumentTypeError(
            "the verification API only binds to a loopback host"
        )
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ecoguard-api",
        description="Run the local-only EcoGuard verification API.",
    )
    parser.add_argument("--host", default="127.0.0.1", type=_loopback_host)
    parser.add_argument("--port", default=8765, type=_port)
    args = parser.parse_args(argv)
    with make_server(args.host, args.port, application) as server:
        print(f"EcoGuard local API listening on http://{args.host}:{args.port}")
        print("This process has no authentication; do not expose it publicly.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("EcoGuard local API stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
