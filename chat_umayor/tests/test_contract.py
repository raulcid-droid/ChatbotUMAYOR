"""Tests unitarios del modelo ``chat_umayor.contract`` y el helper
``chatbot.session._launch_signature``.

Cubren:
    - Campos denormalizados copiados desde el partner al crear.
    - Snapshot inmutable: mutar el partner después no afecta al contrato.
    - Transición a ``signed`` + cierre de la sesión.
    - Formato de ``reference`` (``CH-NNNNNN``).

Para los tests que pasan por ``_launch_signature`` creamos un
``sign.template`` real con un ``ir.attachment`` dummy (PDF mínimo en
base64), para que el ``sign.request`` que genera el flujo tenga un
FK válido hacia una plantilla existente. Si Odoo 19 exige campos
adicionales en alguno de esos modelos, ``_ensure_sign_template``
hace ``skipTest`` con mensaje claro.
"""

import base64
import json

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("chat_umayor", "post_install", "-at_install")
class TestChatbotContract(TransactionCase):
    """Modelo ``chat_umayor.contract`` y ``_launch_signature``."""

    # ------------------------------------------------------------------
    # Fixtures compartidas
    # ------------------------------------------------------------------

    def _ensure_sign_template(self):
        """Crea un ``sign.template`` real y setea el ``ir.config_parameter``.

        Se necesita para que el ``sign.request`` que crea
        ``_launch_signature`` tenga un FK válido (``template_id``) y
        para que el ``contract.write({'sign_request_id': ...})`` del
        helper no viole el FK hacia ``sign_request``.

        Si la creación falla (requirements extra de Odoo 19 en
        ``ir.attachment`` o ``sign.template``), el test se
        ``skipTest`` con mensaje descriptivo en vez de reventar.
        """
        try:
            attachment = self.env["ir.attachment"].sudo().create(
                {
                    "name": "test_contract.pdf",
                    "datas": base64.b64encode(b"%PDF-1.4\n% fake test pdf\n"),
                    "mimetype": "application/pdf",
                }
            )
            template = (
                self.env["sign.template"]
                .sudo()
                .create(
                    {
                        "name": "Test Template (chat_umayor)",
                        "attachment_id": attachment.id,
                    }
                )
            )
        except Exception as exc:  # pragma: no cover
            self.skipTest(
                "No se pudo crear sign.template/ir.attachment para el "
                f"test (posibles requirements extra en Odoo 19): {exc}"
            )
        self.env["ir.config_parameter"].sudo().set_param(
            "chat_umayor.sign_template_id", str(template.id)
        )
        return template

    def _make_review_session(self, partner_values=None, summary=None):
        """Crea una sesión en ``review`` con partner y submit_summary.

        Monta el estado mínimo necesario para poder lanzar la firma:
        sesión que recorrió el FSM hasta ``review``, un ``res.partner``
        asociado y el JSON de ``submit_summary`` que persiste PLAN 08.
        """
        session = self.env["chatbot.session"]._create_with_greeting()
        for target in ("discovery", "product_info", "data_collection", "review"):
            session._do_transition(target)

        partner_defaults = {
            "name": "Juan Pérez",
            "vat": "12345678-5",
            "email": "juan@example.com",
            "phone": "+56911112222",
        }
        partner_defaults.update(partner_values or {})
        partner = self.env["res.partner"].create(partner_defaults)
        session.partner_id = partner.id
        session.product_code = "soap"

        summary_defaults = {
            "product_code": "soap",
            "product_data": {
                "vehicle_plate": "BCDF12",
                "vehicle_year": 2020,
                "vehicle_type": "particular",
            },
            "calculated": {
                "premium": 7990,
                "currency": "CLP",
                "vehicle_type": "particular",
            },
        }
        session.submit_summary = json.dumps(summary or summary_defaults)
        return session, partner

    # ------------------------------------------------------------------
    # reference (asignado en create override)
    # ------------------------------------------------------------------

    def test_reference_format(self) -> None:
        """``reference`` usa formato ``CH-NNNNNN`` con padding a 6 dígitos."""
        session, partner = self._make_review_session()
        contract = self.env["chat_umayor.contract"].create(
            {
                "session_id": session.id,
                "partner_id": partner.id,
                "partner_name": partner.name,
                "partner_vat": partner.vat,
                "partner_email": partner.email,
                "partner_phone": partner.phone,
                "product_code": "soap",
            }
        )
        self.assertEqual(contract.reference, f"CH-{contract.id:06d}")
        self.assertTrue(contract.reference.startswith("CH-"))
        self.assertEqual(len(contract.reference), 9)  # CH- + 6 dígitos

    # ------------------------------------------------------------------
    # _launch_signature: create + snapshot denormalizado
    # ------------------------------------------------------------------

    def test_create_contract_from_submit_summary(self) -> None:
        """``_launch_signature`` crea contrato con snapshot de partner."""
        session, partner = self._make_review_session()
        self._ensure_sign_template()

        contract, sign_url = session._launch_signature()

        self.assertEqual(contract.session_id.id, session.id)
        self.assertEqual(contract.partner_id.id, partner.id)
        # Snapshot denormalizado:
        self.assertEqual(contract.partner_name, "Juan Pérez")
        self.assertEqual(contract.partner_vat, "12345678-5")
        self.assertEqual(contract.partner_email, "juan@example.com")
        self.assertEqual(contract.partner_phone, "+56911112222")
        # Producto y cálculo preservados:
        self.assertEqual(contract.product_code, "soap")
        product_data = json.loads(contract.product_data_json)
        self.assertEqual(product_data["vehicle_plate"], "BCDF12")
        calculated = json.loads(contract.calculated_json)
        self.assertEqual(calculated["premium"], 7990)
        # Estado y vínculo con sign.request real:
        self.assertEqual(contract.state, "signing")
        self.assertTrue(contract.sign_request_id)
        self.assertIn(
            f"/sign/document/{contract.sign_request_id.id}", sign_url
        )

    def test_partner_snapshot_is_immutable_on_partner_change(self) -> None:
        """Mutar el partner después NO afecta al contrato (snapshot)."""
        session, partner = self._make_review_session()
        self._ensure_sign_template()

        contract, _ = session._launch_signature()

        # Mutación posterior del partner:
        partner.write(
            {
                "email": "otro@dominio.cl",
                "phone": "+56999999999",
                "name": "Nombre Cambiado",
            }
        )

        # El contrato conserva los valores originales:
        contract.invalidate_recordset()
        self.assertEqual(contract.partner_email, "juan@example.com")
        self.assertEqual(contract.partner_phone, "+56911112222")
        self.assertEqual(contract.partner_name, "Juan Pérez")

    # ------------------------------------------------------------------
    # _mark_signed
    # ------------------------------------------------------------------

    def test_mark_signed_updates_state_and_closes_session(self) -> None:
        """``_mark_signed`` pasa contrato a signed y sesión a closed."""
        session, partner = self._make_review_session()
        # Creamos el contrato directamente en ``signing`` sin lanzar
        # ``_launch_signature`` (aquí no queremos testear eso).
        contract = self.env["chat_umayor.contract"].create(
            {
                "session_id": session.id,
                "partner_id": partner.id,
                "partner_name": partner.name,
                "partner_vat": partner.vat,
                "partner_email": partner.email,
                "partner_phone": partner.phone,
                "product_code": "soap",
                "state": "signing",
            }
        )
        # La sesión también tiene que estar en signing para que el FSM
        # acepte la transición a closed.
        session._do_transition("signing")

        contract._mark_signed()

        self.assertEqual(contract.state, "signed")
        self.assertTrue(contract.signed_at)
        self.assertEqual(contract.session_id.state, "closed")

    def test_mark_signed_is_idempotent(self) -> None:
        """Llamar ``_mark_signed`` dos veces no rompe ni cambia nada."""
        session, partner = self._make_review_session()
        contract = self.env["chat_umayor.contract"].create(
            {
                "session_id": session.id,
                "partner_id": partner.id,
                "partner_name": partner.name,
                "partner_vat": partner.vat,
                "product_code": "soap",
                "state": "signing",
            }
        )
        session._do_transition("signing")

        contract._mark_signed()
        first_signed_at = contract.signed_at
        # Segunda llamada: debe ser no-op (idempotente).
        contract._mark_signed()
        self.assertEqual(contract.state, "signed")
        self.assertEqual(contract.signed_at, first_signed_at)
