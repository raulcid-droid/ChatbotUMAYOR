"""Tests unitarios de los helpers de RUT chileno en ``chatbot.session``.

Cubren ``_normalize_rut_cl`` (canoniza 3 formatos de entrada) y
``_validate_rut_cl`` (módulo 11, casos válido / DV incorrecto / K).
"""

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("chat_umayor", "post_install", "-at_install")
class TestRutValidation(TransactionCase):
    """Normalización y validación de RUT chileno."""

    def setUp(self) -> None:
        super().setUp()
        self.Session = self.env["chatbot.session"]

    # ``12345678-5`` tiene DV correcto por módulo 11:
    #   8·2 + 7·3 + 6·4 + 5·5 + 4·6 + 3·7 + 2·2 + 1·3 = 138
    #   138 % 11 = 6; 11-6 = 5 → DV="5"
    VALID_RUT = "12345678-5"

    def test_valid_rut_formats(self) -> None:
        """Los 3 formatos habituales del mismo RUT son todos válidos."""
        for rut in (
            "12.345.678-5",
            "12345678-5",
            "123456785",
        ):
            self.assertTrue(
                self.Session._validate_rut_cl(rut),
                f"RUT '{rut}' debería ser válido",
            )

    def test_invalid_check_digit(self) -> None:
        """Cuerpo correcto con DV incorrecto falla la validación."""
        for bad_dv in ("12345678-0", "12345678-9", "12345678-K"):
            self.assertFalse(
                self.Session._validate_rut_cl(bad_dv),
                f"RUT '{bad_dv}' debería ser inválido",
            )

    def test_normalize_various_inputs(self) -> None:
        """Normaliza los 3 formatos al canónico ``NNNNNNNN-D``."""
        inputs = [
            ("12.345.678-5", "12345678-5"),
            ("12345678-5", "12345678-5"),
            ("123456785", "12345678-5"),
            ("  12.345.678-k  ", "12345678-K"),  # strip + upper
        ]
        for raw, expected in inputs:
            self.assertEqual(
                self.Session._normalize_rut_cl(raw),
                expected,
                f"Normalización incorrecta para '{raw}'",
            )
