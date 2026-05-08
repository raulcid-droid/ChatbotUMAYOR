"""Tests unitarios del modelo ``chat_umayor.product.soap``.

Cubren ``_validate`` (casos OK y fallos por campo) y ``_calculate``
(tarifa plana por tipo de vehículo).
"""

import datetime

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("chat_umayor", "post_install", "-at_install")
class TestProductSoap(TransactionCase):
    """Validación y cálculo del producto SOAP."""

    def setUp(self) -> None:
        super().setUp()
        self.product = self.env.ref("chat_umayor.product_soap_singleton")

    # ------------------------------------------------------------------
    # _validate
    # ------------------------------------------------------------------

    def test_validate_ok(self) -> None:
        """Payload válido → dict vacío (sin errores)."""
        errors = self.product._validate(
            {
                "vehicle_plate": "BCDF12",
                "vehicle_year": 2020,
                "vehicle_type": "particular",
            }
        )
        self.assertEqual(errors, {})

    def test_validate_invalid_plate(self) -> None:
        """Patente fuera del regex devuelve error solo en ese campo."""
        errors = self.product._validate(
            {
                "vehicle_plate": "XX",  # demasiado corta
                "vehicle_year": 2020,
                "vehicle_type": "particular",
            }
        )
        self.assertIn("vehicle_plate", errors)
        self.assertNotIn("vehicle_year", errors)
        self.assertNotIn("vehicle_type", errors)

    def test_validate_year_out_of_range(self) -> None:
        """Año fuera de [1950, actual+1] devuelve error."""
        too_old = self.product._validate(
            {
                "vehicle_plate": "BCDF12",
                "vehicle_year": 1920,
                "vehicle_type": "particular",
            }
        )
        self.assertIn("vehicle_year", too_old)

        too_new = self.product._validate(
            {
                "vehicle_plate": "BCDF12",
                "vehicle_year": datetime.date.today().year + 5,
                "vehicle_type": "particular",
            }
        )
        self.assertIn("vehicle_year", too_new)

    # ------------------------------------------------------------------
    # _calculate
    # ------------------------------------------------------------------

    def test_calculate_premium_by_type(self) -> None:
        """Cada tipo de vehículo devuelve la tarifa documentada."""
        expected = {
            "particular": 7990,
            "moto": 3990,
            "comercial": 14990,
            "taxi": 24990,
        }
        for vtype, premium in expected.items():
            result = self.product._calculate(
                {
                    "vehicle_plate": "BCDF12",
                    "vehicle_year": 2020,
                    "vehicle_type": vtype,
                }
            )
            self.assertEqual(
                result["premium"],
                premium,
                f"Tarifa incorrecta para {vtype}",
            )
            self.assertEqual(result["currency"], "CLP")
            self.assertEqual(result["vehicle_type"], vtype)
