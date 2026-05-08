"""Tests unitarios de la clasificación de intención y helpers auxiliares
del modelo ``chatbot.session``.

Cubre la tabla de decisiones D2 de PLAN 07:

    greeting       + cualquier texto            -> discovery
    discovery      + 'soap'                     -> product_info (+soap)
    discovery      + 'deposito'                 -> product_info (+deposit)
    discovery      + otro                       -> None
    product_info   + 'si|quiero|contratar'      -> data_collection
    product_info   + 'otro|cambiar'             -> discovery
    product_info   + otro                       -> None
    data_collection, review, signing, closed    -> None

Además cubre ``_get_last_n()`` (historial saneado) y
``_create_with_greeting()`` (factory de sesión con primer mensaje).

Todos los tests son ``TransactionCase`` puro: no tocan HTTP ni LLM.
"""

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("chat_umayor", "post_install", "-at_install")
class TestClassifyIntent(TransactionCase):
    """Función ``_classify_intent(state, text)``.

    La función es "pura" (no lee ORM), pero vive en el modelo por
    proximidad con el FSM. La invocamos vía el recordset vacío para
    no crear sesiones innecesarias.
    """

    def setUp(self) -> None:
        super().setUp()
        self.Session = self.env["chatbot.session"]

    # -----------------------------------------------------------------
    # Desde greeting
    # -----------------------------------------------------------------

    def test_greeting_any_text_goes_to_discovery(self) -> None:
        target = self.Session._classify_intent("greeting", "hola")
        self.assertEqual(target, "discovery")

    def test_greeting_empty_text_stays(self) -> None:
        target = self.Session._classify_intent("greeting", "   ")
        self.assertIsNone(target)

    # -----------------------------------------------------------------
    # Desde discovery
    # -----------------------------------------------------------------

    def test_discovery_soap_keyword_advances(self) -> None:
        target = self.Session._classify_intent(
            "discovery", "Quiero contratar un SOAP"
        )
        self.assertEqual(target, "product_info")

    def test_discovery_seguro_obligatorio_advances(self) -> None:
        target = self.Session._classify_intent(
            "discovery", "me interesa el seguro obligatorio"
        )
        self.assertEqual(target, "product_info")

    def test_discovery_deposito_keyword_advances(self) -> None:
        target = self.Session._classify_intent(
            "discovery", "Quiero un depósito a plazo"
        )
        self.assertEqual(target, "product_info")

    def test_discovery_ahorro_keyword_advances(self) -> None:
        target = self.Session._classify_intent(
            "discovery", "busco un ahorro"
        )
        self.assertEqual(target, "product_info")

    def test_discovery_unknown_stays(self) -> None:
        target = self.Session._classify_intent(
            "discovery", "cuánto cuesta un auto"
        )
        self.assertIsNone(target)

    def test_discovery_is_case_insensitive(self) -> None:
        target = self.Session._classify_intent("discovery", "SOAP")
        self.assertEqual(target, "product_info")

    def test_discovery_ignores_accents(self) -> None:
        # "depósito" con acento debe detectarse igual que "deposito".
        target = self.Session._classify_intent("discovery", "Depósito")
        self.assertEqual(target, "product_info")

    # -----------------------------------------------------------------
    # Desde product_info
    # -----------------------------------------------------------------

    def test_product_info_confirm_advances(self) -> None:
        target = self.Session._classify_intent(
            "product_info", "Sí, quiero contratarlo"
        )
        self.assertEqual(target, "data_collection")

    def test_product_info_quiero_advances(self) -> None:
        target = self.Session._classify_intent(
            "product_info", "quiero contratar"
        )
        self.assertEqual(target, "data_collection")

    def test_product_info_change_product_goes_back(self) -> None:
        target = self.Session._classify_intent(
            "product_info", "mejor quiero ver el otro"
        )
        self.assertEqual(target, "discovery")

    def test_product_info_cambiar_goes_back(self) -> None:
        target = self.Session._classify_intent(
            "product_info", "quiero cambiar de producto"
        )
        self.assertEqual(target, "discovery")

    def test_product_info_negation_does_not_advance(self) -> None:
        # "no quiero" no debe avanzar a data_collection aunque contenga
        # "quiero". Mitigación del riesgo de falso positivo por negación.
        target = self.Session._classify_intent(
            "product_info", "no, no quiero contratarlo aún"
        )
        self.assertIsNone(target)

    def test_product_info_unknown_stays(self) -> None:
        target = self.Session._classify_intent(
            "product_info", "dime más detalles"
        )
        self.assertIsNone(target)

    # -----------------------------------------------------------------
    # Estados terminales o sin acción
    # -----------------------------------------------------------------

    def test_data_collection_stays(self) -> None:
        self.assertIsNone(
            self.Session._classify_intent("data_collection", "lo que sea")
        )

    def test_review_stays(self) -> None:
        self.assertIsNone(
            self.Session._classify_intent("review", "listo")
        )

    def test_signing_stays(self) -> None:
        self.assertIsNone(
            self.Session._classify_intent("signing", "ok")
        )

    def test_closed_stays(self) -> None:
        self.assertIsNone(
            self.Session._classify_intent("closed", "hola")
        )


@tagged("chat_umayor", "post_install", "-at_install")
class TestGetLastN(TransactionCase):
    """``session._get_last_n(n)`` devuelve historial saneado.

    Requisitos:
        - Orden cronológico ascendente (ya garantizado por ``_order``).
        - ``content`` pasa por ``_sanitize_for_llm()``.
        - Limita a los últimos ``n`` mensajes.
    """

    def setUp(self) -> None:
        super().setUp()
        self.session = self.env["chatbot.session"].create({})
        self.Message = self.env["chatbot.message"]

    def _add(self, role: str, content: str):
        return self.Message.create(
            {"session_id": self.session.id, "role": role, "content": content}
        )

    def test_empty_session_returns_empty_list(self) -> None:
        self.assertEqual(self.session._get_last_n(), [])

    def test_returns_dicts_with_role_and_content(self) -> None:
        self._add("user", "hola")
        self._add("assistant", "buenas")
        history = self.session._get_last_n()
        self.assertEqual(len(history), 2)
        self.assertEqual(
            history[0], {"role": "user", "content": "hola"}
        )
        self.assertEqual(
            history[1], {"role": "assistant", "content": "buenas"}
        )

    def test_returns_in_chronological_order(self) -> None:
        self._add("user", "primero")
        self._add("assistant", "segundo")
        self._add("user", "tercero")
        history = self.session._get_last_n()
        self.assertEqual(
            [m["content"] for m in history],
            ["primero", "segundo", "tercero"],
        )

    def test_sanitizes_pii_before_returning(self) -> None:
        self._add("user", "mi rut es 12.345.678-5")
        history = self.session._get_last_n()
        self.assertEqual(history[0]["content"], "mi rut es [DOCUMENTO]")

    def test_limits_to_last_n(self) -> None:
        for i in range(15):
            self._add("user", f"m{i}")
        history = self.session._get_last_n(n=10)
        self.assertEqual(len(history), 10)
        # Los últimos 10, de m5 a m14.
        self.assertEqual(history[0]["content"], "m5")
        self.assertEqual(history[-1]["content"], "m14")


@tagged("chat_umayor", "post_install", "-at_install")
class TestCreateWithGreeting(TransactionCase):
    """Factory ``_create_with_greeting()`` crea sesión + primer mensaje."""

    def setUp(self) -> None:
        super().setUp()
        self.Session = self.env["chatbot.session"]

    def test_returns_session_in_greeting_state(self) -> None:
        session = self.Session._create_with_greeting()
        self.assertEqual(session.state, "greeting")

    def test_creates_initial_assistant_message(self) -> None:
        session = self.Session._create_with_greeting()
        self.assertEqual(len(session.message_ids), 1)
        msg = session.message_ids[0]
        self.assertEqual(msg.role, "assistant")
        self.assertIn("UMayor", msg.content)

    def test_greeting_content_matches_constant(self) -> None:
        session = self.Session._create_with_greeting()
        self.assertEqual(session.message_ids[0].content, self.Session._GREETING)
