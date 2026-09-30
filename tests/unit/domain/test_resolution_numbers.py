from __future__ import annotations

import unittest

from document_processing.domain.resolution import parse_flexible_number


class ResolutionNumbersTest(unittest.TestCase):
    """Caracteriza a normalização usada pela DAG 2 sem depender do Docling."""

    def test_parses_brazilian_thousands_for_units(self) -> None:
        self.assertEqual(parse_flexible_number("1.234", column_name="unidades"), 1234.0)

    def test_rejects_semantic_label_as_number(self) -> None:
        self.assertIsNone(parse_flexible_number("2T 2026"))

    def test_parses_currency_millions(self) -> None:
        self.assertEqual(parse_flexible_number("R$ 1,5 mi"), 1_500_000.0)

    def test_parentheses_are_the_accounting_minus_sign(self) -> None:
        """Prejuizo publicado entre parenteses nao pode virar lucro.

        Regressao: a MGLU 2T26 publicou "(50,4)" e a resolucao gravou +50,4 --
        numero plausivel, gate aprovado, sinal invertido.
        """
        self.assertEqual(parse_flexible_number("(50,4)"), -50.4)
        self.assertEqual(parse_flexible_number("(794.123)"), -794123.0)
        self.assertEqual(parse_flexible_number("(3,1%)"), -3.1)
        self.assertEqual(
            parse_flexible_number("(1.234)", column_name="unidades"), -1234.0
        )

    def test_parentheses_without_digits_are_not_numbers(self) -> None:
        self.assertIsNone(parse_flexible_number("(vazio)"))

    def test_keeps_explicit_minus_sign(self) -> None:
        self.assertEqual(parse_flexible_number("-50,4"), -50.4)

    def test_parses_ratio_with_times_suffix(self) -> None:
        """Alavancagem em "numero de vezes" e o formato do grupo indicadores_razao."""
        self.assertEqual(parse_flexible_number("3,49x"), 3.49)
        self.assertEqual(parse_flexible_number("0,69x"), 0.69)
        self.assertEqual(parse_flexible_number("1.5X"), 1.5)
        self.assertEqual(parse_flexible_number("(1,2x)"), -1.2)

    def test_still_rejects_unknown_alphabetic_tokens(self) -> None:
        """O "x" abriu excecao so para razao; o resto do filtro continua valendo."""
        self.assertIsNone(parse_flexible_number("n.a"))
        self.assertIsNone(parse_flexible_number("3,49 vezes"))


if __name__ == "__main__":
    unittest.main()
