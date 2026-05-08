"""Tests HTTP del endpoint ``POST /chat_umayor/session/<id>/sign``.

Creamos un ``sign.template`` real con un ``ir.attachment`` dummy para
que el ``sign.request`` generado por ``_launch_signature`` tenga un
FK válido. Si algún test requiere que **falle** la creación (caso
``SIGN_UNAVAILABLE``), se limpia explícitamente el parámetro
``chat_umayor.sign_template_id``.

La validación end-to-end con Sign real se hace manualmente (ver
``tests/manual/test_sign_integration.py``).
"""

import base64
import json

from odoo.tests import tagged
from odoo.tests.common import HttpCase
from odoo.tools import mute_logger


_CTRL_LOGGER = "odoo.addons.chat_umayor.controllers.main"
_SESSION_LOGGER = "odoo.addons.chat_umayor.models.chatbot_session"


def _jsonrpc_payload(params: dict | None = None) -> str:
    """Construye el body JSON-RPC 2.0 esperado por ``type='jsonrpc'``."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "call",
            "params": params or {},
            "id": 1,
        }
    )


@tagged("chat_umayor", "post_install", "-at_install")
class TestSessionSign(HttpCase):
    """Endpoint ``POST /chat_umayor/session/<id>/sign`` (PLAN 09)."""

    def _make_review_session_with_summary(self):
        """Sesión en ``review`` con partner y submit_summary listo."""
        session = self.env["chatbot.session"]._create_with_greeting()
        for target in (
            "discovery",
            "product_info",
            "data_collection",
            "review",
        ):
            session._do_transition(target)
        partner = self.env["res.partner"].create(
            {
                "name": "Juan Pérez",
                "vat": "12345678-5",
                "email": "juan@example.com",
                "phone": "+56911112222",
            }
        )
        session.partner_id = partner.id
        session.product_code = "soap"
        session.submit_summary = json.dumps(
            {
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
        )
        return session

    def _ensure_sign_template(self):
        """Crea ``sign.template`` + ``ir.attachment`` reales y fija config.

        Devuelve el recordset de la plantilla. Si Odoo 19 requiere
        campos adicionales, hace ``skipTest`` con mensaje claro.
        """
        try:
            attachment = self.env["ir.attachment"].sudo().create(
                {
                    "name": "test_sign_endpoint.pdf",
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
                "No se pudo crear sign.template/ir.attachment: "
                f"{exc}"
            )
        self.env["ir.config_parameter"].sudo().set_param(
            "chat_umayor.sign_template_id", str(template.id)
        )
        return template

    def _clear_sign_template(self) -> None:
        """Quita el parámetro para simular que no hay plantilla configurada."""
        self.env["ir.config_parameter"].sudo().set_param(
            "chat_umayor.sign_template_id", "0"
        )

    def _call(self, session_id: int) -> dict:
        response = self.url_open(
            f"/chat_umayor/session/{session_id}/sign",
            data=_jsonrpc_payload({}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        envelope = response.json()
        self.assertIn("result", envelope, f"JSON-RPC sin 'result': {envelope}")
        return envelope["result"]

    # -----------------------------------------------------------------
    # Happy path
    # -----------------------------------------------------------------

    def test_sign_happy_path_creates_contract_and_returns_url(self) -> None:
        """Sesión en review + plantilla OK → crea contract, devuelve url."""
        session = self._make_review_session_with_summary()
        self._ensure_sign_template()

        result = self._call(session.id)

        self.assertTrue(result["ok"], f"no ok: {result}")
        data = result["data"]
        self.assertIsInstance(data["contract_id"], int)
        self.assertTrue(data["sign_url"].startswith("/sign/document/"))
        self.assertEqual(data["state"], "signing")

        session.invalidate_recordset()
        self.assertEqual(session.state, "signing")
        contract = self.env["chat_umayor.contract"].search(
            [("session_id", "=", session.id)], limit=1
        )
        self.assertTrue(contract)
        self.assertEqual(contract.state, "signing")
        self.assertTrue(contract.sign_request_id)

    # -----------------------------------------------------------------
    # Errores
    # -----------------------------------------------------------------

    @mute_logger(_SESSION_LOGGER, _CTRL_LOGGER)
    def test_sign_unavailable_when_template_not_configured(self) -> None:
        """Sin ``ir.config_parameter`` → SIGN_UNAVAILABLE."""
        session = self._make_review_session_with_summary()
        self._clear_sign_template()

        result = self._call(session.id)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "SIGN_UNAVAILABLE")
        session.invalidate_recordset()
        self.assertEqual(session.state, "review")  # no avanza

    def test_sign_idempotent_returns_same_url(self) -> None:
        """2 llamadas consecutivas devuelven el mismo contract_id y URL."""
        session = self._make_review_session_with_summary()
        self._ensure_sign_template()

        first = self._call(session.id)
        second = self._call(session.id)

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(
            first["data"]["contract_id"], second["data"]["contract_id"]
        )
        self.assertEqual(first["data"]["sign_url"], second["data"]["sign_url"])

    def test_sign_invalid_state_when_not_in_review(self) -> None:
        """Sesión en ``greeting`` → INVALID_STATE (no transición)."""
        session = self.env["chatbot.session"]._create_with_greeting()
        # Sesión en greeting, sin review.

        result = self._call(session.id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_STATE")

    @mute_logger(_SESSION_LOGGER, _CTRL_LOGGER)
    def test_sign_missing_contract_data_when_no_submit_summary(self) -> None:
        """Sesión en review sin ``submit_summary`` → MISSING_CONTRACT_DATA."""
        session = self.env["chatbot.session"]._create_with_greeting()
        for target in (
            "discovery",
            "product_info",
            "data_collection",
            "review",
        ):
            session._do_transition(target)
        # Forzamos a review sin haber pasado por /submit_data real.
        # session.submit_summary sigue falsy.
        self._ensure_sign_template()

        result = self._call(session.id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "MISSING_CONTRACT_DATA")
