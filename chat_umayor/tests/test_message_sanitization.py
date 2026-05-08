"""Tests del modelo ``chatbot.message`` y de ``_sanitize_for_llm()``.

Cubre:
    - CRUD básico y vínculo con ``chatbot.session``.
    - ``ondelete='cascade'`` borra mensajes al borrar la sesión.
    - Orden cronológico estable (``_order = 'create_date asc, id asc'``).
    - Sanitización de 4 tipos de PII chilena: RUT, email, teléfono, tarjeta.
    - Preservación del texto original en BD tras sanear.

No llama a Gemini ni al controller HTTP: son tests unitarios puros.
"""

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("chat_umayor", "post_install", "-at_install")
class TestMessageSanitization(TransactionCase):
    """CRUD, orden, cascade y sanitización de ``chatbot.message``."""

    def setUp(self) -> None:
        super().setUp()
        self.Session = self.env["chatbot.session"]
        self.Message = self.env["chatbot.message"]
        self.session = self.Session.create({})

    # ------------------------------------------------------------------
    # CRUD y relación con chatbot.session
    # ------------------------------------------------------------------

    def test_create_message_linked_to_session(self) -> None:
        """Un mensaje creado aparece en ``session.message_ids``."""
        msg = self.Message.create(
            {
                "session_id": self.session.id,
                "role": "user",
                "content": "Hola",
            }
        )
        self.assertIn(msg, self.session.message_ids)
        self.assertEqual(msg.session_id, self.session)

    def test_cascade_delete(self) -> None:
        """Borrar la sesión borra sus mensajes en cascada."""
        msg = self.Message.create(
            {
                "session_id": self.session.id,
                "role": "user",
                "content": "Test",
            }
        )
        msg_id = msg.id
        self.session.unlink()
        self.assertFalse(self.Message.browse(msg_id).exists())

    def test_order_is_chronological(self) -> None:
        """Dos mensajes creados en orden se leen en orden cronológico."""
        first = self.Message.create(
            {"session_id": self.session.id, "role": "user", "content": "1"}
        )
        second = self.Message.create(
            {"session_id": self.session.id, "role": "assistant", "content": "2"}
        )
        messages = self.session.message_ids
        self.assertEqual(list(messages), [first, second])

    # ------------------------------------------------------------------
    # Sanitización de RUT chileno
    # ------------------------------------------------------------------

    def test_sanitize_rut_with_dots_and_dash(self) -> None:
        """RUT formato ``12.345.678-5`` se reemplaza por ``[DOCUMENTO]``."""
        msg = self.Message.create(
            {
                "session_id": self.session.id,
                "role": "user",
                "content": "Mi RUT es 12.345.678-5 gracias",
            }
        )
        self.assertEqual(msg._sanitize_for_llm(), "Mi RUT es [DOCUMENTO] gracias")

    def test_sanitize_rut_without_separators(self) -> None:
        """RUT pegado ``123456785`` (8+DV) se reemplaza por ``[DOCUMENTO]``."""
        msg = self.Message.create(
            {
                "session_id": self.session.id,
                "role": "user",
                "content": "RUT 123456785 listo",
            }
        )
        self.assertEqual(msg._sanitize_for_llm(), "RUT [DOCUMENTO] listo")

    def test_sanitize_rut_with_k_dv(self) -> None:
        """RUT con DV = K (``7.654.321-K``) se sanea."""
        msg = self.Message.create(
            {
                "session_id": self.session.id,
                "role": "user",
                "content": "Documento: 7.654.321-K",
            }
        )
        self.assertEqual(msg._sanitize_for_llm(), "Documento: [DOCUMENTO]")

    # ------------------------------------------------------------------
    # Sanitización de email
    # ------------------------------------------------------------------

    def test_sanitize_email(self) -> None:
        """Emails se reemplazan por ``[EMAIL]``."""
        msg = self.Message.create(
            {
                "session_id": self.session.id,
                "role": "user",
                "content": "Escríbeme a juan@example.com gracias",
            }
        )
        self.assertEqual(
            msg._sanitize_for_llm(), "Escríbeme a [EMAIL] gracias"
        )

    # ------------------------------------------------------------------
    # Sanitización de teléfono chileno
    # ------------------------------------------------------------------

    def test_sanitize_phone_chilean(self) -> None:
        """Teléfono ``+56 9 1234 5678`` se reemplaza por ``[TELEFONO]``."""
        msg = self.Message.create(
            {
                "session_id": self.session.id,
                "role": "user",
                "content": "Mi fono +56 9 1234 5678 llámame",
            }
        )
        self.assertEqual(msg._sanitize_for_llm(), "Mi fono [TELEFONO] llámame")

    # ------------------------------------------------------------------
    # Sanitización de tarjeta de crédito
    # ------------------------------------------------------------------

    def test_sanitize_credit_card(self) -> None:
        """Tarjeta ``4111 1111 1111 1111`` se reemplaza por ``[TARJETA]``."""
        msg = self.Message.create(
            {
                "session_id": self.session.id,
                "role": "user",
                "content": "Paga con 4111 1111 1111 1111 OK",
            }
        )
        self.assertEqual(msg._sanitize_for_llm(), "Paga con [TARJETA] OK")

    # ------------------------------------------------------------------
    # Caso combinado
    # ------------------------------------------------------------------

    def test_sanitize_multiple_in_one_message(self) -> None:
        """RUT + email + teléfono en un mismo mensaje se reemplazan todos."""
        content = (
            "Soy Juan, RUT 12.345.678-5, email juan@example.com, "
            "fono +56 9 1234 5678."
        )
        msg = self.Message.create(
            {
                "session_id": self.session.id,
                "role": "user",
                "content": content,
            }
        )
        sanitized = msg._sanitize_for_llm()
        self.assertIn("[DOCUMENTO]", sanitized)
        self.assertIn("[EMAIL]", sanitized)
        self.assertIn("[TELEFONO]", sanitized)
        # Y no debe quedar PII visible.
        self.assertNotIn("12.345.678", sanitized)
        self.assertNotIn("juan@example.com", sanitized)
        self.assertNotIn("+56", sanitized)

    # ------------------------------------------------------------------
    # Invariantes
    # ------------------------------------------------------------------

    def test_sanitize_preserves_original_in_db(self) -> None:
        """Tras sanear, ``content`` en BD sigue siendo el texto original."""
        original = "Mi RUT es 12.345.678-5"
        msg = self.Message.create(
            {
                "session_id": self.session.id,
                "role": "user",
                "content": original,
            }
        )
        msg._sanitize_for_llm()
        # Invalidamos cache y releemos desde BD.
        msg.invalidate_recordset(["content"])
        self.assertEqual(msg.content, original)

    def test_sanitize_whitespace_only_content(self) -> None:
        """Contenido con solo espacios se devuelve tal cual, sin fallar.

        ``content`` es ``required=True``, así que el caso realmente vacío
        no ocurre en la práctica. Probamos el borde más cercano: un
        string con sólo espacios debe atravesar la sanitización sin
        excepciones y sin cambios.
        """
        msg = self.Message.create(
            {
                "session_id": self.session.id,
                "role": "user",
                "content": "   ",
            }
        )
        self.assertEqual(msg._sanitize_for_llm(), "   ")

    def test_sanitize_no_pii_returns_same_text(self) -> None:
        """Texto sin PII no se modifica."""
        original = "Hola, ¿cómo estás hoy?"
        msg = self.Message.create(
            {
                "session_id": self.session.id,
                "role": "user",
                "content": original,
            }
        )
        self.assertEqual(msg._sanitize_for_llm(), original)
