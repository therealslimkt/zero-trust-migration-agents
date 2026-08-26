import unittest

from edge_runtime.types import DecodedField, DecodedRecord, DecodedSource


class DecodedTypesTests(unittest.TestCase):
    def test_repr_does_not_expose_edge_only_values(self):
        field = DecodedField("tax_id", "000-11-2222", "governmentId")
        record = DecodedRecord(0, (field,))
        source = DecodedSource("jde", "F0101", (record,))

        self.assertNotIn("000-11-2222", repr(field))
        self.assertNotIn("000-11-2222", repr(record))
        self.assertNotIn("000-11-2222", repr(source))

    def test_rejects_unknown_category(self):
        with self.assertRaises(ValueError):
            DecodedField("tax_id", "value", "unclassified")

    def test_rejects_duplicate_fields(self):
        with self.assertRaises(ValueError):
            DecodedRecord(
                0,
                (
                    DecodedField("customer_id", 1),
                    DecodedField("customer_id", 2),
                ),
            )


if __name__ == "__main__":
    unittest.main()
