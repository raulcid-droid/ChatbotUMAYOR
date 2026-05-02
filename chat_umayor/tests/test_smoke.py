"""Tests de humo del módulo chat_umayor.

Verifican que el módulo instala y que la cadena de imports +
registro de controllers funciona de extremo a extremo, sin depender
de modelos ni servicios externos.
"""

import json

from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged("chat_umayor", "post_install", "-at_install")
class TestSmokePing(HttpCase):
    """Smoke test del endpoint /chat_umayor/ping."""

    def test_ping_returns_pong(self) -> None:
        """El endpoint /chat_umayor/ping devuelve shape {ok, data} con status=pong."""
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {},
            "id": 1,
        }
        response = self.url_open(
            "/chat_umayor/ping",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 200)

        envelope = response.json()
        self.assertIn("result", envelope, f"JSON-RPC sin 'result': {envelope}")

        result = envelope["result"]
        self.assertTrue(result["ok"], f"Respuesta no ok: {result}")
        self.assertEqual(result["data"]["status"], "pong")
        self.assertEqual(result["data"]["module"], "chat_umayor")
        self.assertIn("version", result["data"])
