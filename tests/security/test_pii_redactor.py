import unittest

from edge_runtime.types import DecodedField, DecodedRecord, DecodedSource
from edge_security.pii_redactor import DeterministicRedactor, RedactionBlocked


class DeterministicRedactorTests(unittest.TestCase):
    def setUp(self):
        self.redactor = DeterministicRedactor(
            b"test-key-that-is-at-least-thirty-two-bytes"
        )

    def test_tokenizes_classified_values_and_preserves_public_values(self):
        source = DecodedSource(
            "jde",
            "F0101",
            (
                DecodedRecord(
                    0,
                    (
                        DecodedField("address_number", 1001),
                        DecodedField("alpha_name", "Example Person", "name"),
                        DecodedField("tax_id", "000-11-2222", "governmentId"),
                    ),
                ),
            ),
        )

        result = self.redactor.sanitize(source)
        values = result.sanitized.as_candidate()["records"][0]["values"]

        self.assertEqual(values[0]["value"], 1001)
        self.assertEqual(values[0]["protection"], "sanitized")
        self.assertTrue(values[1]["value"].startswith("tok_"))
        self.assertTrue(values[2]["value"].startswith("tok_"))
        self.assertNotIn("Example Person", repr(result))
        self.assertNotIn("000-11-2222", repr(result))
        self.assertEqual(result.finding_count, 2)
        self.assertEqual(result.category_counts["name"], 1)
        self.assertEqual(result.category_counts["governmentId"], 1)

    def test_tokens_are_stable_and_domain_separated(self):
        first = DecodedSource(
            "maxdb",
            "KNA1",
            (DecodedRecord(0, (DecodedField("name", "Same", "name"),)),),
        )
        second = DecodedSource(
            "maxdb",
            "KNA1",
            (DecodedRecord(0, (DecodedField("city", "Same", "address"),)),),
        )

        first_values = self.redactor.sanitize(first).sanitized.as_candidate()["records"]
        repeated_values = self.redactor.sanitize(first).sanitized.as_candidate()["records"]
        second_values = self.redactor.sanitize(second).sanitized.as_candidate()["records"]
        first_token = first_values[0]["values"][0]["value"]
        repeated_token = repeated_values[0]["values"][0]["value"]
        second_token = second_values[0]["values"][0]["value"]

        self.assertEqual(first_token, repeated_token)
        self.assertNotEqual(first_token, second_token)

    def test_blocks_residual_pii_mislabeled_as_public_without_echo(self):
        source = DecodedSource(
            "jde",
            "F0101",
            (DecodedRecord(0, (DecodedField("unsafe", "000-11-2222"),)),),
        )
        with self.assertRaises(RedactionBlocked) as caught:
            self.redactor.sanitize(source)
        self.assertNotIn("000-11-2222", str(caught.exception))

    def test_rejects_short_token_key(self):
        with self.assertRaises(ValueError):
            DeterministicRedactor(b"too short")


if __name__ == "__main__":
    unittest.main()
