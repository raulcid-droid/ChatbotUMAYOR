"""Tests de ``_get_or_create_partner`` (idempotencia por RUT).

Dos llamadas con el mismo RUT deben devolver el mismo ``res.partner``,
actualizando campos si llegan nuevos.
"""

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("chat_umayor", "post_install", "-at_install")
class TestPartnerIdempotency(TransactionCase):
    """Creación y actualización idempotente de ``res.partner``."""

    def setUp(self) -> None:
        super().setUp()
        self.session = self.env["chatbot.session"]._create_with_greeting()

    def test_create_new_partner(self) -> None:
        """RUT inexistente → crea partner con vat normalizado."""
        partner = self.session._get_or_create_partner(
            {
                "name": "Juan Pérez",
                "document_id": "12.345.678-5",
                "email": "juan@example.com",
                "phone": "+56 9 1234 5678",
            }
        )
        self.assertTrue(partner.id)
        self.assertEqual(partner.vat, "12345678-5")  # normalizado
        self.assertEqual(partner.name, "Juan Pérez")
        self.assertEqual(partner.email, "juan@example.com")

    def test_updates_existing_partner_by_rut(self) -> None:
        """Segunda llamada con mismo RUT → mismo id, campos actualizados."""
        first = self.session._get_or_create_partner(
            {
                "name": "Juan Pérez",
                "document_id": "12345678-5",
                "email": "juan@example.com",
            }
        )
        second = self.session._get_or_create_partner(
            {
                "name": "Juan P. Actualizado",
                "document_id": "12.345.678-5",  # mismo RUT, otro formato
                "email": "juan.nuevo@example.com",
                "phone": "+56911112222",
            }
        )
        self.assertEqual(first.id, second.id, "Debe ser el mismo partner")
        # Refresca desde BD para no depender de la cache.
        second.invalidate_recordset()
        self.assertEqual(second.name, "Juan P. Actualizado")
        self.assertEqual(second.email, "juan.nuevo@example.com")
        self.assertEqual(second.phone, "+56911112222")
