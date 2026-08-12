import copy
import json
import unittest
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from hypothesis import given, settings, strategies as st

from ecoguard.api import application
from ecoguard.cbam import calculate_exposure
from ecoguard.forest import evaluate_binary_mask
from ecoguard.preprocessing import _normalize


ROOT = Path(__file__).resolve().parents[1]
PROPERTY_SETTINGS = settings(max_examples=80, derandomize=True, deadline=None)


def _api_status(raw: bytes) -> str:
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
    return captured["status"]


class ParserPropertyTests(unittest.TestCase):
    @PROPERTY_SETTINGS
    @given(st.integers(min_value=1, max_value=100_000_000))
    def test_kg_and_metric_tonne_notation_normalize_to_same_mass(self, kilograms):
        kg_value, kg_unit, _ = _normalize("shipment_mass_t", f"{kilograms:,} kg")
        tonnes = Decimal(kilograms) / Decimal("1000")
        tonne_value, tonne_unit, _ = _normalize(
            "shipment_mass_t", f"{format(tonnes, 'f')} metric tonnes"
        )
        self.assertEqual((kg_value, kg_unit), (tonne_value, tonne_unit))

    @PROPERTY_SETTINGS
    @given(
        st.sampled_from(
            [
                "less than",
                "at most",
                "maximum",
                "under",
                "최대",
                "이하",
            ]
        ),
        st.integers(min_value=1, max_value=1_000_000),
    )
    def test_explicit_mass_bounds_never_become_exact_values(self, qualifier, value):
        with self.assertRaises(ValueError):
            _normalize("shipment_mass_t", f"{qualifier} {value} MT")

    @PROPERTY_SETTINGS
    @given(
        st.integers(min_value=1, max_value=1_000_000),
        st.sampled_from(["/day", "/일", " per hour", "⁄month", "∕%"]),
    )
    def test_compound_mass_units_never_become_absolute_values(self, value, suffix):
        with self.assertRaises(ValueError):
            _normalize("shipment_mass_t", f"{value} MT{suffix}")

    @PROPERTY_SETTINGS
    @given(st.binary(min_size=1, max_size=96))
    def test_arbitrary_non_json_bytes_never_escape_as_server_errors(self, raw):
        status = _api_status(raw)
        self.assertNotEqual(status.split()[0][0], "5")


class CalculationPropertyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.normalized = json.loads(
            (ROOT / "artifacts/examples/normalized_evidence.json").read_text(
                encoding="utf-8"
            )
        )

    @PROPERTY_SETTINGS
    @given(st.sampled_from(["m5", "m12"]), st.integers(min_value=1, max_value=9))
    def test_component_mutation_without_matching_lineage_is_always_rejected(
        self, item, tenths
    ):
        payload = copy.deepcopy(self.normalized)
        field = f"{item}_process_direct_intensity_tco2e_per_t"
        detail = payload["fields"][field]
        original = Decimal(detail["value"])
        replacement = original + Decimal(tenths) / Decimal("10")

        selected = next(row for row in detail["candidates"] if row["selected"])
        selected["raw_value"] = f"{replacement} tCO2e/t"
        # The integrity boundary intentionally rejects a normalized mutation that
        # does not also reproduce its retained source line and hashes.
        with self.assertRaises(ValueError):
            calculate_exposure(payload)

    @PROPERTY_SETTINGS
    @given(
        st.sets(st.integers(min_value=0, max_value=15), max_size=16),
        st.sets(st.integers(min_value=0, max_value=15), max_size=16),
    )
    def test_binary_mask_confusion_matrix_always_partitions_universe(
        self, predicted_indices, reference_indices
    ):
        universe = {(index // 4, index % 4) for index in range(16)}
        predicted = {(index // 4, index % 4) for index in predicted_indices}
        reference = {(index // 4, index % 4) for index in reference_indices}
        result = evaluate_binary_mask(predicted, reference, universe)
        confusion = result["confusion_matrix"]
        self.assertEqual(sum(confusion.values()), 16)
        self.assertEqual(confusion["tp"] + confusion["fp"], len(predicted_indices))
        self.assertEqual(confusion["tp"] + confusion["fn"], len(reference_indices))


if __name__ == "__main__":
    unittest.main()
