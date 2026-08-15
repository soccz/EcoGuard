import argparse
import json
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from ecoguard import __version__
from ecoguard.api import (
    MAX_QUERY_CHARACTERS,
    MAX_REQUEST_BYTES,
    _loopback_host,
    application,
    main,
)

ROOT = Path(__file__).resolve().parents[1]


def call_api(method, path, payload=None, *, content_type="application/json"):
    raw = b"" if payload is None else json.dumps(payload).encode("utf-8")
    environ = {
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": content_type,
        "PATH_INFO": path,
        "REQUEST_METHOD": method,
        "wsgi.input": BytesIO(raw),
    }
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(application(environ, start_response))
    captured["json"] = json.loads(body)
    return captured


class LocalApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.normalized = json.loads(
            (ROOT / "artifacts/examples/normalized_evidence.json").read_text(
                encoding="utf-8"
            )
        )

    def test_health_identifies_non_production_package_version(self):
        response = call_api("GET", "/health")
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(response["json"]["package_version"], __version__)
        self.assertFalse(response["json"]["production_ready"])
        self.assertEqual(response["headers"]["Cache-Control"], "no-store")

    def test_server_host_is_restricted_to_loopback(self):
        self.assertEqual(_loopback_host("127.0.0.1"), "127.0.0.1")
        for host in ("0.0.0.0", "::1", "localhost"):
            with self.subTest(host=host), self.assertRaises(argparse.ArgumentTypeError):
                _loopback_host(host)

    def test_cbam_endpoint_reuses_validated_calculation_boundary(self):
        response = call_api("POST", "/v1/cbam/calculate", self.normalized)
        self.assertEqual(response["status"], "200 OK")
        self.assertTrue(response["json"]["human_review_required"])
        result = response["json"]["result"]
        self.assertEqual(
            result["technical_inventory"]["embedded_emissions_tco2e"],
            "1111.36",
        )
        self.assertFalse(result["statutory_calculator"])

    def test_legal_endpoint_returns_citation_or_explicit_abstention(self):
        supported = call_api(
            "POST",
            "/v1/legal/retrieve",
            {"query": "CBAM 신고인의 검증 의무는 어느 조문인가?", "limit": 2},
        )
        self.assertEqual(supported["status"], "200 OK")
        self.assertIn(
            supported["json"]["result"]["decision"]["status"],
            {"supported", "review"},
        )
        self.assertTrue(supported["json"]["result"]["results"])

        abstained = call_api(
            "POST",
            "/v1/legal/retrieve",
            {"query": "주말 여행 숙소를 추천해줘"},
        )
        self.assertEqual(abstained["status"], "200 OK")
        self.assertEqual(abstained["json"]["result"]["decision"]["status"], "abstained")
        self.assertEqual(abstained["json"]["result"]["results"], [])

    def test_boundary_rejects_bad_media_json_size_path_and_method(self):
        media = call_api(
            "POST",
            "/v1/legal/retrieve",
            {"query": "CBAM"},
            content_type="text/plain",
        )
        self.assertEqual(media["status"], "415 Unsupported Media Type")

        invalid = {
            "CONTENT_LENGTH": "1",
            "CONTENT_TYPE": "application/json",
            "PATH_INFO": "/v1/legal/retrieve",
            "REQUEST_METHOD": "POST",
            "wsgi.input": BytesIO(b"{"),
        }
        captured = {}

        def start_response(status, headers):
            captured["status"] = status

        list(application(invalid, start_response))
        self.assertEqual(captured["status"], "422 Unprocessable Content")

        too_large = {
            "CONTENT_LENGTH": str(MAX_REQUEST_BYTES + 1),
            "CONTENT_TYPE": "application/json",
            "PATH_INFO": "/v1/legal/retrieve",
            "REQUEST_METHOD": "POST",
            "wsgi.input": BytesIO(b""),
        }
        list(application(too_large, start_response))
        self.assertEqual(captured["status"], "413 Content Too Large")

        self.assertEqual(call_api("GET", "/missing")["status"], "404 Not Found")
        self.assertEqual(
            call_api("GET", "/v1/legal/retrieve")["status"],
            "405 Method Not Allowed",
        )

    def test_legal_request_shape_is_fail_closed(self):
        extra = call_api(
            "POST",
            "/v1/legal/retrieve",
            {"query": "CBAM 검증", "debug": True},
        )
        self.assertEqual(extra["status"], "422 Unprocessable Content")
        invalid_limit = call_api(
            "POST",
            "/v1/legal/retrieve",
            {"query": "CBAM 검증", "limit": 0},
        )
        self.assertEqual(invalid_limit["status"], "422 Unprocessable Content")

        oversized_query = call_api(
            "POST",
            "/v1/legal/retrieve",
            {"query": "CBAM " + "a" * MAX_QUERY_CHARACTERS},
        )
        self.assertEqual(oversized_query["status"], "422 Unprocessable Content")

        cbam_array = call_api("POST", "/v1/cbam/calculate", [])
        self.assertEqual(cbam_array["status"], "422 Unprocessable Content")

    def test_deep_json_is_rejected_without_escaping_as_server_error(self):
        raw = ("[" * 100_000 + "0" + "]" * 100_000).encode("ascii")
        environ = {
            "CONTENT_LENGTH": str(len(raw)),
            "CONTENT_TYPE": "application/json",
            "PATH_INFO": "/v1/legal/retrieve",
            "REQUEST_METHOD": "POST",
            "wsgi.input": BytesIO(raw),
        }
        captured = {}

        def start_response(status, _headers):
            captured["status"] = status

        list(application(environ, start_response))
        self.assertEqual(captured["status"], "422 Unprocessable Content")

        for raw in (b'{"query":"CBAM","query":"EUDR"}', b'{"limit":1e999}'):
            environ["CONTENT_LENGTH"] = str(len(raw))
            environ["wsgi.input"] = BytesIO(raw)
            list(application(environ, start_response))
            self.assertEqual(captured["status"], "422 Unprocessable Content")

    def test_cli_stops_cleanly_on_keyboard_interrupt(self):
        server = MagicMock()
        server.__enter__.return_value = server
        server.serve_forever.side_effect = KeyboardInterrupt
        with patch("ecoguard.api.make_server", return_value=server):
            self.assertEqual(main(["--host", "127.0.0.1", "--port", "8765"]), 0)


if __name__ == "__main__":
    unittest.main()
