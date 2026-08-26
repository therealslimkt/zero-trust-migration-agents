import unittest

from control_plane.canonical import (
    SOURCE_ORDER,
    canonical_json_bytes,
    document_digest,
    portfolio_plan_digest,
    require_digest,
    require_run_id,
    stable_id,
)


class CanonicalTests(unittest.TestCase):
    def test_canonical_json_and_document_digest_ignore_mapping_order(self):
        first = {"b": 2, "a": {"d": 4, "c": 3}}
        second = {"a": {"c": 3, "d": 4}, "b": 2}
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
        self.assertEqual(document_digest(first), document_digest(second))

    def test_document_digest_can_omit_self_digest(self):
        first = {"planId": "plan_one", "planDigest": "old"}
        second = {"planId": "plan_one", "planDigest": "changed"}
        self.assertEqual(
            document_digest(first, omit=("planDigest",)),
            document_digest(second, omit=("planDigest",)),
        )

    def test_stable_id_is_deterministic_and_domain_separated(self):
        self.assertEqual(stable_id("plan_", "run", "jde"), stable_id("plan_", "run", "jde"))
        self.assertNotEqual(stable_id("plan_", "run", "jde"), stable_id("plan_", "run", "maxdb"))
        self.assertTrue(stable_id("plan_", "run", "jde").startswith("plan_"))

    def test_requires_contract_run_ids_and_digests(self):
        self.assertEqual(require_run_id("mig_123456789012"), "mig_123456789012")
        self.assertEqual(require_digest("sha256:" + "a" * 64), "sha256:" + "a" * 64)
        for invalid in ("mig_short", "run_123456789012", ""):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    require_run_id(invalid)
        with self.assertRaises(ValueError):
            require_digest("a" * 64)

    def test_portfolio_digest_is_source_ordered_and_complete(self):
        plans = [
            {"sourceId": source_id, "planDigest": "sha256:" + character * 64}
            for source_id, character in zip(SOURCE_ORDER, "abc")
        ]
        self.assertEqual(portfolio_plan_digest(plans), portfolio_plan_digest(reversed(plans)))
        with self.assertRaises(ValueError):
            portfolio_plan_digest(plans[:2])
        with self.assertRaises(ValueError):
            portfolio_plan_digest(plans + [plans[0]])


if __name__ == "__main__":
    unittest.main()
