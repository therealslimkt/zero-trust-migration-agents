import json
import subprocess
import unittest

from edge_runtime.types import DecodedField, DecodedRecord, DecodedSource
from edge_security.local_gemma_agent import LocalGemmaError, TailscaleGemmaReviewer
from edge_security.pii_redactor import DeterministicRedactor


class FakeRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return self.responses.pop(0)


def completed(returncode=0, stdout=b""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=b"")


class TailscaleGemmaReviewerTests(unittest.TestCase):
    def sanitized(self):
        raw = DecodedSource(
            "jde",
            "F0101",
            (
                DecodedRecord(
                    0,
                    (
                        DecodedField("address_number", 1001),
                        DecodedField("tax_id", "000-11-2222", "governmentId"),
                    ),
                ),
            ),
        )
        return DeterministicRedactor(
            b"test-key-that-is-at-least-thirty-two-bytes"
        ).sanitize(raw).sanitized

    def test_reviews_only_sanitized_candidate_over_magicdns(self):
        runner = FakeRunner(
            [completed(), completed(stdout=b'{"status":"passed","findings":[]}')]
        )
        review = TailscaleGemmaReviewer(runner=runner).review(self.sanitized())

        self.assertEqual(review.status, "passed")
        self.assertEqual(review.finding_count, 0)
        command = runner.calls[1][0]
        prompt = runner.calls[1][1]["input"].decode("utf-8")
        self.assertIn("ohallaatme@sparky-sid-411116", command)
        self.assertNotIn("100.", " ".join(command))
        self.assertNotIn("000-11-2222", prompt)
        self.assertIn("tok_", prompt)

    def test_accepts_strict_blocked_verdict_without_values(self):
        verdict = {
            "status": "blocked",
            "findings": [{"field": "address_number", "category": "other"}],
        }
        runner = FakeRunner(
            [completed(), completed(stdout=json.dumps(verdict).encode("utf-8"))]
        )
        review = TailscaleGemmaReviewer(runner=runner).review(self.sanitized())
        self.assertEqual(review.status, "blocked")
        self.assertEqual(review.category_counts["other"], 1)

    def test_fails_closed_on_unreachable_host(self):
        with self.assertRaises(LocalGemmaError):
            TailscaleGemmaReviewer(
                runner=FakeRunner([completed(returncode=1)])
            ).review(self.sanitized())

    def test_fails_closed_on_invalid_or_inconsistent_verdict(self):
        invalid_outputs = (
            b"not-json",
            b'{"status":"passed","findings":[{"field":"tax_id","category":"governmentId"}]}',
            b'{"status":"blocked","findings":[]}',
            b'{"status":"passed","findings":[],"raw":"forbidden"}',
        )
        for output in invalid_outputs:
            with self.subTest(output=output):
                runner = FakeRunner([completed(), completed(stdout=output)])
                with self.assertRaises(LocalGemmaError):
                    TailscaleGemmaReviewer(runner=runner).review(self.sanitized())


if __name__ == "__main__":
    unittest.main()
