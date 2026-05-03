"""Controllers HTTP del módulo chat_umayor.

Expone los endpoints JSON-RPC documentados en ``docs/api.md``. Por ahora
solo existe un endpoint de salud (``/chat_umayor/ping``) usado como smoke
check y referencia del shape de respuesta ``{ok, data|error}``.

Los 4 endpoints del contrato (``/session/new``, ``/session/<id>/message``,
``/session/<id>/submit_data``, ``/session/<id>/sign``) se implementan en
PLAN 07, una vez que existan los modelos y el wrapper de Gemini.
"""

from odoo.http import Controller, route

MODULE_VERSION = "19.0.1.0.0"


class ChatUmayorController(Controller):
    """Endpoints HTTP públicos del chatbot bancario."""

    @route("/chat_umayor/ping", type="jsonrpc", auth="public", methods=["POST"])
    def ping(self) -> dict:
        """Smoke check del módulo.

        Returns:
            Shape ``{ok, data}`` documentado en ``docs/api.md §1``.
            ``data`` incluye un ``status="pong"`` y la versión del módulo
            para verificación rápida en despliegues.
        """
        return {
            "ok": True,
            "data": {
                "status": "pong",
                "module": "chat_umayor",
                "version": MODULE_VERSION,
            },
        }
