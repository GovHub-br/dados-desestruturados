from __future__ import annotations

import unittest

from document_intelligence.domain.resolution import parse_flexible_number


class ResolutionNumbersTest(unittest.TestCase):
    """Caracteriza a normalização usada pela DAG 2 sem depender do Docling."""

    def test_parses_brazilian_thousands_for_units(self) -> None:
        self.assertEqual(parse_flexible_number("1.234", column_name="unidades"), 1234.0)

    def test_rejects_semantic_label_as_number(self) -> None:
        self.assertIsNone(parse_flexible_number("2T 2026"))

    def test_parses_currency_millions(self) -> None:
        self.assertEqual(parse_flexible_number("R$ 1,5 mi"), 1_500_000.0)


if __name__ == "__main__":
    unittest.main()
