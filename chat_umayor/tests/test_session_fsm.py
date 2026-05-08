"""Tests de la máquina de estados de ``chatbot.session``.

Cubre las transiciones declaradas en §6 de ``AGENTS.md`` local:

    greeting → discovery → product_info → data_collection
             → review → signing → closed
                     ↑___________________|
                     (cambio de producto)

Los métodos públicos probados son ``_transition_to_<estado>()`` del
modelo ``chatbot.session``. Estos tests son unitarios puros: no
llaman a Gemini ni tocan el controller HTTP.
"""

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("chat_umayor", "post_install", "-at_install")
class TestSessionFSM(TransactionCase):
    """Transiciones válidas e inválidas del FSM de ``chatbot.session``."""

    def setUp(self) -> None:
        super().setUp()
        self.Session = self.env["chatbot.session"]

    # ---------------------------------------------------------------
    # Creación y estado inicial
    # ---------------------------------------------------------------

    def test_new_session_starts_in_greeting(self) -> None:
        """Una sesión recién creada arranca en ``state='greeting'``."""
        session = self.Session.create({})
        self.assertEqual(session.state, "greeting")

    # ---------------------------------------------------------------
    # Cadena feliz completa
    # ---------------------------------------------------------------

    def test_happy_path_full_flow(self) -> None:
        """Recorre greeting → … → closed sin saltos."""
        session = self.Session.create({})

        session._transition_to_discovery()
        self.assertEqual(session.state, "discovery")

        session._transition_to_product_info()
        self.assertEqual(session.state, "product_info")

        session._transition_to_data_collection()
        self.assertEqual(session.state, "data_collection")

        session._transition_to_review()
        self.assertEqual(session.state, "review")

        session._transition_to_signing()
        self.assertEqual(session.state, "signing")

        session._transition_to_closed()
        self.assertEqual(session.state, "closed")

    # ---------------------------------------------------------------
    # Transiciones inválidas
    # ---------------------------------------------------------------

    def test_cannot_skip_states(self) -> None:
        """Saltar de ``greeting`` directo a ``signing`` levanta UserError."""
        session = self.Session.create({})
        with self.assertRaises(UserError):
            session._transition_to_signing()

    def test_cannot_go_backwards_from_review_to_discovery(self) -> None:
        """No se permite volver de ``review`` a ``discovery`` (ya hay datos)."""
        session = self.Session.create({})
        session._transition_to_discovery()
        session._transition_to_product_info()
        session._transition_to_data_collection()
        session._transition_to_review()
        with self.assertRaises(UserError):
            session._transition_to_discovery()

    # ---------------------------------------------------------------
    # Cambio de producto: única excepción no lineal
    # ---------------------------------------------------------------

    def test_product_info_can_go_back_to_discovery(self) -> None:
        """Desde ``product_info`` se puede volver a ``discovery`` (cambio de producto)."""
        session = self.Session.create({})
        session._transition_to_discovery()
        session._transition_to_product_info()
        session._transition_to_discovery()
        self.assertEqual(session.state, "discovery")

    # ---------------------------------------------------------------
    # Estado terminal
    # ---------------------------------------------------------------

    def test_closed_is_terminal(self) -> None:
        """Desde ``closed`` no hay transiciones posibles."""
        session = self.Session.create({})
        session._transition_to_discovery()
        session._transition_to_product_info()
        session._transition_to_data_collection()
        session._transition_to_review()
        session._transition_to_signing()
        session._transition_to_closed()

        # Ninguna transición debe salir de closed.
        for method_name in (
            "_transition_to_greeting",
            "_transition_to_discovery",
            "_transition_to_product_info",
            "_transition_to_data_collection",
            "_transition_to_review",
            "_transition_to_signing",
        ):
            with self.assertRaises(UserError, msg=f"{method_name} no debió permitirse desde closed"):
                getattr(session, method_name)()

    # ---------------------------------------------------------------
    # Mensaje de error en español
    # ---------------------------------------------------------------

    def test_invalid_transition_error_message_is_in_spanish(self) -> None:
        """El mensaje del UserError está en español y es apto para usuario final."""
        session = self.Session.create({})
        try:
            session._transition_to_signing()
        except UserError as exc:
            message = str(exc)
            # Heurística: contiene alguna palabra en español del dominio.
            lowered = message.lower()
            self.assertTrue(
                any(word in lowered for word in ("no se puede", "estado", "transición", "inválida")),
                f"Mensaje no parece estar en español: {message!r}",
            )
        else:
            self.fail("Se esperaba UserError pero no se levantó.")
