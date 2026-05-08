"""Tests HTTP de los endpoints del módulo ``chat_umayor``.

Cubre los 3 endpoints reales (``/session/new``, ``/session/<id>/message``,
``/session/<id>/submit_data``) y el único stub restante (``/sign``,
hasta PLAN 09). El wrapper ``GeminiClient`` se mockea en los tests
que lo requieren para no depender de ``google-genai`` ni hacer
llamadas reales.

Todos los tests son ``HttpCase`` porque los endpoints son
``type='jsonrpc'`` y el envoltorio JSON-RPC solo se ejercita vía HTTP.
"""

import json
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import HttpCase
from odoo.tools import mute_logger

from odoo.addons.chat_umayor.services.gemini_client import LLMUnavailable


# Target del mock: la clase real, no una instancia. ``patch.object``
# sobre la clase afecta a todas las instancias creadas durante el test.
_GENERATE_REPLY = (
    "odoo.addons.chat_umayor.services.gemini_client.GeminiClient.generate_reply"
)
# Logger del controller; algunos tests ejercen ramas con
# ``_logger.exception(...)`` y queremos el output limpio.
_CTRL_LOGGER = "odoo.addons.chat_umayor.controllers.main"


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
class TestSessionNew(HttpCase):
    """Endpoint ``POST /chat_umayor/session/new``."""

    def _call(self) -> dict:
        response = self.url_open(
            "/chat_umayor/session/new",
            data=_jsonrpc_payload({}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        envelope = response.json()
        self.assertIn("result", envelope, f"JSON-RPC sin 'result': {envelope}")
        return envelope["result"]

    def test_creates_session_and_greeting(self) -> None:
        """Devuelve session_id + estado greeting + mensaje inicial en BD."""
        result = self._call()
        self.assertTrue(result["ok"], f"no ok: {result}")
        data = result["data"]
        self.assertIsInstance(data["session_id"], int)
        self.assertEqual(data["state"], "greeting")
        self.assertIn("UMayor", data["greeting_message"])
        self.assertIn("created_at", data)

        # El mensaje inicial está en BD con rol assistant.
        session = self.env["chatbot.session"].browse(data["session_id"])
        self.assertEqual(len(session.message_ids), 1)
        self.assertEqual(session.message_ids[0].role, "assistant")


@tagged("chat_umayor", "post_install", "-at_install")
class TestSessionMessage(HttpCase):
    """Endpoint ``POST /chat_umayor/session/<id>/message``."""

    def setUp(self) -> None:
        super().setUp()
        self.session = self.env["chatbot.session"]._create_with_greeting()

    def _call(self, content, session_id=None) -> dict:
        sid = self.session.id if session_id is None else session_id
        response = self.url_open(
            f"/chat_umayor/session/{sid}/message",
            data=_jsonrpc_payload({"content": content}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        envelope = response.json()
        self.assertIn("result", envelope, f"JSON-RPC sin 'result': {envelope}")
        return envelope["result"]

    # -----------------------------------------------------------------
    # Happy path y transiciones de FSM
    # -----------------------------------------------------------------

    def test_happy_path_greeting_to_discovery(self) -> None:
        """El primer mensaje desde greeting avanza a discovery."""
        with patch(_GENERATE_REPLY, return_value="¿En qué te ayudo?"):
            result = self._call("hola")
        self.assertTrue(result["ok"], f"no ok: {result}")
        data = result["data"]
        self.assertEqual(data["reply"], "¿En qué te ayudo?")
        self.assertEqual(data["state"], "discovery")
        self.assertIsNone(data["product_code"])

    def test_soap_keyword_advances_to_product_info(self) -> None:
        """Desde discovery, mención de SOAP avanza y setea product_code."""
        self.session._transition_to_discovery()
        with patch(_GENERATE_REPLY, return_value="SOAP es..."):
            result = self._call("quiero un SOAP")
        data = result["data"]
        self.assertEqual(data["state"], "product_info")
        self.assertEqual(data["product_code"], "soap")

    def test_deposit_keyword_advances_to_product_info(self) -> None:
        """Desde discovery, mención de depósito setea product_code='deposit'."""
        self.session._transition_to_discovery()
        with patch(_GENERATE_REPLY, return_value="Un depósito..."):
            result = self._call("me interesa un depósito a plazo")
        data = result["data"]
        self.assertEqual(data["state"], "product_info")
        self.assertEqual(data["product_code"], "deposit")

    def test_confirm_advances_to_data_collection_with_product_code(self) -> None:
        """Desde product_info, confirmación avanza y devuelve product_code."""
        self.session._transition_to_discovery()
        self.session.product_code = "soap"
        self.session._transition_to_product_info()
        with patch(_GENERATE_REPLY, return_value="Genial, te pido tus datos."):
            result = self._call("sí, quiero contratarlo")
        data = result["data"]
        self.assertEqual(data["state"], "data_collection")
        self.assertEqual(data["product_code"], "soap")

    def test_change_product_goes_back_to_discovery(self) -> None:
        """Desde product_info, 'el otro' vuelve a discovery y limpia producto."""
        self.session._transition_to_discovery()
        self.session.product_code = "soap"
        self.session._transition_to_product_info()
        with patch(_GENERATE_REPLY, return_value="Ok, el otro producto..."):
            result = self._call("quiero el otro")
        data = result["data"]
        self.assertEqual(data["state"], "discovery")
        self.assertIsNone(data["product_code"])

    def test_product_code_null_when_not_selected(self) -> None:
        """En estados sin producto, product_code viaja como null."""
        with patch(_GENERATE_REPLY, return_value="..."):
            result = self._call("hola")
        # Tras el mensaje, sesión está en discovery sin producto.
        self.assertIsNone(result["data"]["product_code"])

    # -----------------------------------------------------------------
    # Sanitización del historial enviado al wrapper
    # -----------------------------------------------------------------

    def test_sanitized_content_sent_to_gemini(self) -> None:
        """El RUT del usuario llega a GeminiClient como [DOCUMENTO]."""
        captured = {}

        def fake_reply(self, messages):
            captured["messages"] = messages
            return "ok"

        with patch(_GENERATE_REPLY, autospec=True, side_effect=fake_reply):
            self._call("mi rut es 12.345.678-5")

        self.assertIn("messages", captured)
        last_user = [
            m for m in captured["messages"] if m["role"] == "user"
        ][-1]
        self.assertEqual(last_user["content"], "mi rut es [DOCUMENTO]")

    # -----------------------------------------------------------------
    # Errores controlados
    # -----------------------------------------------------------------

    @mute_logger(_CTRL_LOGGER)
    def test_llm_unavailable_returns_error_code(self) -> None:
        """Si el wrapper levanta LLMUnavailable, error.code es LLM_UNAVAILABLE.

        Además el error lleva ``reply`` (canned), ``state`` y
        ``product_code`` para que la UI pueda seguir renderizando sin
        bloquear la conversación (contrato v0.3 §4.2).
        """
        with patch(_GENERATE_REPLY, side_effect=LLMUnavailable("boom")):
            result = self._call("hola")
        self.assertFalse(result["ok"])
        err = result["error"]
        self.assertEqual(err["code"], "LLM_UNAVAILABLE")
        self.assertIn("reply", err)
        self.assertTrue(err["reply"])  # canned no vacío
        self.assertEqual(err["state"], "greeting")
        self.assertIsNone(err["product_code"])
        # La sesión no debe avanzar de estado tras el error.
        self.session.invalidate_recordset()
        self.assertEqual(self.session.state, "greeting")
        # El canned debe quedar persistido como turno assistant.
        roles = self.session.message_ids.mapped("role")
        self.assertEqual(roles[-1], "assistant")

    def test_session_not_found(self) -> None:
        """Un session_id inexistente devuelve SESSION_NOT_FOUND."""
        with patch(_GENERATE_REPLY, return_value="no debería llamarse"):
            result = self._call("hola", session_id=999999)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "SESSION_NOT_FOUND")

    def test_empty_content_validation_error(self) -> None:
        """Content vacío devuelve VALIDATION_ERROR con fields."""
        with patch(_GENERATE_REPLY, return_value="no debería llamarse"):
            result = self._call("   ")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("content", result["error"]["fields"])

    def test_too_long_content_validation_error(self) -> None:
        """Content > 2000 chars devuelve VALIDATION_ERROR."""
        long_text = "a" * 2001
        with patch(_GENERATE_REPLY, return_value="no debería llamarse"):
            result = self._call(long_text)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")

    def test_closed_session_returns_session_closed(self) -> None:
        """Una sesión cerrada rechaza mensajes con SESSION_CLOSED."""
        # Fuerza la sesión a closed pasando por todos los estados.
        for target in (
            "discovery",
            "product_info",
            "data_collection",
            "review",
            "signing",
            "closed",
        ):
            self.session._do_transition(target)
        with patch(_GENERATE_REPLY, return_value="no debería llamarse"):
            result = self._call("hola")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "SESSION_CLOSED")


@tagged("chat_umayor", "post_install", "-at_install")
class TestSessionSubmitData(HttpCase):
    """Endpoint ``POST /chat_umayor/session/<id>/submit_data`` (PLAN 08)."""

    # RUT chileno válido por módulo 11 (ver test_rut_validation).
    VALID_RUT = "12.345.678-5"
    VALID_PARTNER = {
        "name": "Juan Pérez",
        "document_id": VALID_RUT,
        "email": "juan@example.com",
        "phone": "+56 9 1234 5678",
    }
    VALID_SOAP_DATA = {
        "vehicle_plate": "BCDF12",
        "vehicle_year": 2020,
        "vehicle_type": "particular",
    }
    VALID_DEPOSIT_DATA = {"amount": 1_000_000, "term_days": 90}

    def _make_session_in_state(self, state: str, product_code=None):
        """Crea una sesión y la lleva al estado pedido a través del FSM.

        ``product_code`` se setea en el momento adecuado (tras
        ``discovery``) para reflejar el flujo real.
        """
        session = self.env["chatbot.session"]._create_with_greeting()
        chain = [
            "discovery",
            "product_info",
            "data_collection",
            "review",
            "signing",
            "closed",
        ]
        for target in chain:
            session._do_transition(target)
            if target == "discovery" and product_code:
                session.product_code = product_code
            if target == state:
                break
        return session

    def setUp(self) -> None:
        super().setUp()
        self.session = self._make_session_in_state(
            "data_collection", product_code="soap"
        )

    def _call(self, params: dict, session_id=None) -> dict:
        sid = self.session.id if session_id is None else session_id
        response = self.url_open(
            f"/chat_umayor/session/{sid}/submit_data",
            data=_jsonrpc_payload(params),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        envelope = response.json()
        self.assertIn("result", envelope, f"JSON-RPC sin 'result': {envelope}")
        return envelope["result"]

    # -----------------------------------------------------------------
    # Happy paths
    # -----------------------------------------------------------------

    def test_submit_data_soap_happy_path(self) -> None:
        """SOAP válido transiciona a review y devuelve summary."""
        result = self._call(
            {
                "product_code": "soap",
                "partner": self.VALID_PARTNER,
                "product_data": self.VALID_SOAP_DATA,
            }
        )
        self.assertTrue(result["ok"], f"no ok: {result}")
        data = result["data"]
        self.assertEqual(data["state"], "review")
        summary = data["summary"]
        self.assertEqual(summary["product_name"], "SOAP")
        self.assertEqual(summary["partner_name"], "Juan Pérez")
        self.assertEqual(summary["calculated"]["premium"], 7990)
        self.assertEqual(summary["calculated"]["currency"], "CLP")

        self.session.invalidate_recordset()
        self.assertEqual(self.session.state, "review")
        self.assertTrue(self.session.submit_summary)

    def test_submit_data_deposit_happy_path(self) -> None:
        """Depósito válido calcula interés simple y avanza a review."""
        # La sesión de setUp está con product_code='soap'; aquí
        # el payload trae 'deposit' y debe ganar.
        result = self._call(
            {
                "product_code": "deposit",
                "partner": self.VALID_PARTNER,
                "product_data": self.VALID_DEPOSIT_DATA,
            }
        )
        self.assertTrue(result["ok"], f"no ok: {result}")
        data = result["data"]
        self.assertEqual(data["state"], "review")
        calc = data["summary"]["calculated"]
        self.assertEqual(calc["principal"], 1_000_000)
        self.assertEqual(calc["interest"], 10_000)
        self.assertEqual(calc["total_at_maturity"], 1_010_000)

        self.session.invalidate_recordset()
        self.assertEqual(self.session.product_code, "deposit")

    # -----------------------------------------------------------------
    # Errores
    # -----------------------------------------------------------------

    def test_submit_data_validation_error_multiple_fields(self) -> None:
        """Email mal + monto fuera de rango devuelve ambos campos en fields."""
        bad_partner = dict(self.VALID_PARTNER, email="no-es-email")
        bad_deposit = {"amount": 10, "term_days": 90}  # 10 < 50.000
        result = self._call(
            {
                "product_code": "deposit",
                "partner": bad_partner,
                "product_data": bad_deposit,
            }
        )
        self.assertFalse(result["ok"])
        err = result["error"]
        self.assertEqual(err["code"], "VALIDATION_ERROR")
        self.assertIn("partner.email", err["fields"])
        self.assertIn("product_data.amount", err["fields"])

        # La sesión no debe avanzar.
        self.session.invalidate_recordset()
        self.assertEqual(self.session.state, "data_collection")

    def test_submit_data_invalid_state_when_in_review(self) -> None:
        """Resubmit en ``review`` devuelve INVALID_STATE con mensaje específico."""
        self.session = self._make_session_in_state(
            "review", product_code="soap"
        )
        result = self._call(
            {
                "product_code": "soap",
                "partner": self.VALID_PARTNER,
                "product_data": self.VALID_SOAP_DATA,
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_STATE")
        self.assertIn("ya fueron enviados", result["error"]["message"])

    def test_submit_data_partner_created_in_db(self) -> None:
        """Tras submit, res.partner existe con el RUT normalizado."""
        self._call(
            {
                "product_code": "soap",
                "partner": self.VALID_PARTNER,
                "product_data": self.VALID_SOAP_DATA,
            }
        )
        partner = self.env["res.partner"].search(
            [("vat", "=", "12345678-5")], limit=1
        )
        self.assertTrue(partner, "Debe existir res.partner con vat normalizado")
        self.assertEqual(partner.name, "Juan Pérez")


@tagged("chat_umayor", "post_install", "-at_install")
class TestStubs(HttpCase):
    """Endpoint stub restante en v0.4: ``/sign`` (real en PLAN 09)."""

    def setUp(self) -> None:
        super().setUp()
        self.session = self.env["chatbot.session"]._create_with_greeting()

    def _call(self, path_suffix: str, params: dict | None = None) -> dict:
        response = self.url_open(
            f"/chat_umayor/session/{self.session.id}/{path_suffix}",
            data=_jsonrpc_payload(params or {}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["result"]

    def test_sign_stub_returns_invalid_state(self) -> None:
        result = self._call("sign")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_STATE")
