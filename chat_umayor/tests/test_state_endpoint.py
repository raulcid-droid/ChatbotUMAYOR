"""Tests HTTP del endpoint ``POST /chat_umayor/session/<id>/state``.

Endpoint ligero de polling (PLAN 09). No requiere estado específico
de la sesión; acepta incluso sesiones ``closed`` (para que el front
pueda confirmar el cierre tras la firma).
"""

import json

from odoo.tests import tagged
from odoo.tests.common import HttpCase


def _jsonrpc_payload(params: dict | None = None) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "call",
            "params": params or {},
            "id": 1,
        }
    )


@tagged("chat_umayor", "post_install", "-at_install")
class TestSessionState(HttpCase):
    """Endpoint ``POST /chat_umayor/session/<id>/state`` (PLAN 09)."""

    def _call(self, session_id: int) -> dict:
        response = self.url_open(
            f"/chat_umayor/session/{session_id}/state",
            data=_jsonrpc_payload({}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        envelope = response.json()
        self.assertIn("result", envelope, f"JSON-RPC sin 'result': {envelope}")
        return envelope["result"]

    def test_state_without_contract(self) -> None:
        """Sesión en ``greeting`` sin contrato → ``contract: null``."""
        session = self.env["chatbot.session"]._create_with_greeting()

        result = self._call(session.id)

        self.assertTrue(result["ok"], f"no ok: {result}")
        data = result["data"]
        self.assertEqual(data["state"], "greeting")
        self.assertIsNone(data["product_code"])
        self.assertIsNone(data["contract"])

    def test_state_with_signing_contract(self) -> None:
        """Sesión en signing con contrato → shape completo con reference."""
        session = self.env["chatbot.session"]._create_with_greeting()
        for target in (
            "discovery",
            "product_info",
            "data_collection",
            "review",
            "signing",
        ):
            session._do_transition(target)
        session.product_code = "soap"
        partner = self.env["res.partner"].create(
            {"name": "Juan Pérez", "vat": "12345678-5"}
        )
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

        result = self._call(session.id)

        self.assertTrue(result["ok"])
        data = result["data"]
        self.assertEqual(data["state"], "signing")
        self.assertEqual(data["product_code"], "soap")
        self.assertIsNotNone(data["contract"])
        self.assertEqual(data["contract"]["state"], "signing")
        self.assertIsNone(data["contract"]["signed_at"])
        self.assertEqual(data["contract"]["reference"], contract.reference)
        self.assertTrue(data["contract"]["reference"].startswith("CH-"))
