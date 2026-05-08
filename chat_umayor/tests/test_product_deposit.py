"""Tests unitarios del modelo ``chat_umayor.product.deposit``.

Cubren ``_validate`` (OK y fallos) y ``_calculate`` (interés simple
con año comercial de 360 días).
"""

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("chat_umayor", "post_install", "-at_install")
class TestProductDeposit(TransactionCase):
    """Validación y cálculo del producto Depósito a Plazo."""

    def setUp(self) -> None:
        super().setUp()
        self.product = self.env.ref("chat_umayor.product_deposit_singleton")

    # ------------------------------------------------------------------
    # _validate
    # ------------------------------------------------------------------

    def test_validate_ok(self) -> None:
        """Payload válido (100.000 CLP, 90 días) → sin errores."""
        errors = self.product._validate(
            {"amount": 100_000, "term_days": 90}
        )
        self.assertEqual(errors, {})

    def test_validate_amount_below_min(self) -> None:
        """Monto menor al mínimo (49.999) devuelve error en amount."""
        errors = self.product._validate(
            {"amount": 49_999, "term_days": 90}
        )
        self.assertIn("amount", errors)
        self.assertNotIn("term_days", errors)

    def test_validate_invalid_term_days(self) -> None:
        """Plazo fuera del set permitido devuelve error."""
        errors = self.product._validate(
            {"amount": 100_000, "term_days": 45}
        )
        self.assertIn("term_days", errors)
        self.assertNotIn("amount", errors)

    # ------------------------------------------------------------------
    # _calculate
    # ------------------------------------------------------------------

    def test_calculate_interest_simple(self) -> None:
        """1.000.000 CLP × 4% × 90/360 = 10.000 interés; total 1.010.000.

        Caso escogido con números redondos para evitar problemas de
        redondeo en el assert (la fórmula es exacta aquí).
        """
        result = self.product._calculate(
            {"amount": 1_000_000, "term_days": 90}
        )
        self.assertEqual(result["principal"], 1_000_000)
        self.assertEqual(result["interest"], 10_000)
        self.assertEqual(result["total_at_maturity"], 1_010_000)
        self.assertEqual(result["rate"], 0.04)
        self.assertEqual(result["term_days"], 90)
        self.assertEqual(result["currency"], "CLP")
