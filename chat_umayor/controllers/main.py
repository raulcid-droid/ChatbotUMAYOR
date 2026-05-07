"""Controllers HTTP del módulo ``chat_umayor``.

Expone los endpoints JSON-RPC documentados en ``docs/api.md``.
Estado en v0.3 (PLAN 07):

- ``/chat_umayor/ping``                              — smoke check (PLAN 03).
- ``/chat_umayor/session/new``                       — crea sesión + greeting.
- ``/chat_umayor/session/<id>/message``              — turno de chat con Gemini.
- ``/chat_umayor/session/<id>/submit_data``          — **stub** v0.3 (PLAN 08).
- ``/chat_umayor/session/<id>/sign``                 — **stub** v0.3 (PLAN 09).

Shape de respuesta (dentro del ``result`` JSON-RPC)::

    {"ok": True,  "data":  {...}}
    {"ok": False, "error": {"code": "...", "message": "..."}}

Las transiciones del FSM se deciden server-side con
``chatbot.session._classify_intent`` (heurística de keywords). El
wrapper Gemini solo genera el texto de respuesta; no interpreta
intención en esta versión (se migra a JSON estructurado en PLAN 08).
"""

import logging

from odoo.exceptions import UserError
from odoo.http import Controller, request, route

from odoo.addons.chat_umayor.services.gemini_client import (
    GeminiClient,
    LLMUnavailable,
)

_logger = logging.getLogger(__name__)


MODULE_VERSION = "19.0.1.0.0"
MAX_MESSAGE_LENGTH = 2000
CANNED_LLM_FALLBACK = (
    "Disculpa, tuve un problema para responder. ¿Podrías intentarlo de nuevo?"
)


# ---------------------------------------------------------------------
# Helpers de shape {ok, data|error}
# ---------------------------------------------------------------------


def _ok(data: dict) -> dict:
    """Envoltorio de éxito."""
    return {"ok": True, "data": data}


def _err(code: str, message: str, **extra) -> dict:
    """Envoltorio de error de negocio.

    Extra se fusiona dentro de ``error`` (por ejemplo ``fields`` en
    ``VALIDATION_ERROR``).
    """
    error = {"code": code, "message": message}
    error.update(extra)
    return {"ok": False, "error": error}


class ChatUmayorController(Controller):
    """Endpoints HTTP públicos del chatbot bancario."""

    # ------------------------------------------------------------------
    # Smoke
    # ------------------------------------------------------------------

    @route("/chat_umayor/ping", type="jsonrpc", auth="public", methods=["POST"])
    def ping(self) -> dict:
        """Smoke check del módulo.

        Returns:
            Shape ``{ok, data}`` con ``status="pong"``, nombre del
            módulo y versión. Útil para validar despliegues.
        """
        return _ok(
            {
                "status": "pong",
                "module": "chat_umayor",
                "version": MODULE_VERSION,
            }
        )

    # ------------------------------------------------------------------
    # Helpers privados
    # ------------------------------------------------------------------

    @staticmethod
    def _get_session_or_error(session_id: int):
        """Busca la sesión y devuelve (session, None) o (None, err).

        Valida existencia y que no esté cerrada. El controller
        normalmente hace::

            session, err = self._get_session_or_error(session_id)
            if err: return err

        Returns:
            Tupla ``(recordset_sesion, None)`` si todo OK, o
            ``(None, dict_error)`` si la sesión no existe o está cerrada.
        """
        session = (
            request.env["chatbot.session"].sudo().browse(session_id).exists()
        )
        if not session:
            return None, _err(
                "SESSION_NOT_FOUND",
                "La sesión indicada no existe o expiró.",
            )
        if session.state == "closed":
            return None, _err(
                "SESSION_CLOSED",
                "La sesión ya está cerrada.",
            )
        return session, None

    @staticmethod
    def _serialize_message_data(session, reply: str) -> dict:
        """Construye el ``data`` de la respuesta de ``/message``.

        ``product_code`` viaja **siempre** (``null`` si no aplica),
        según decisión D1 de PLAN 07. ``suggestions`` queda vacío en
        v0.3; se rellena en PLAN 08 con chips dinámicos.
        """
        return {
            "reply": reply,
            "state": session.state,
            "product_code": session.product_code or None,
            "suggestions": [],
        }

    @staticmethod
    def _apply_transition(session, user_text: str) -> None:
        """Clasifica la intención y aplica la transición si procede.

        Además ajusta ``product_code`` cuando la heurística detecta que
        el usuario eligió o cambió de producto. Si la transición resulta
        inválida contra ``_ALLOWED_TRANSITIONS`` (no debería pasar con
        la tabla actual), se logea y se deja la sesión intacta para no
        romper la respuesta al cliente.
        """
        target = session._classify_intent(session.state, user_text)
        if not target:
            return

        # Ajuste de producto según keywords (solo cuando la transición
        # sale desde discovery a product_info, o vuelve a discovery).
        if session.state == "discovery" and target == "product_info":
            session.product_code = session._detect_product(user_text)
        elif session.state == "product_info" and target == "discovery":
            # Cambio de producto: limpiamos para que el siguiente turno
            # vuelva a elegir.
            session.product_code = False

        try:
            session._do_transition(target)
        except UserError:
            _logger.warning(
                "Transición sugerida %s -> %s rechazada por el FSM; "
                "se mantiene el estado.",
                session.state,
                target,
            )

    # ------------------------------------------------------------------
    # /session/new
    # ------------------------------------------------------------------

    @route(
        "/chat_umayor/session/new",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
    )
    def session_new(self) -> dict:
        """Crea una nueva sesión de chat y devuelve su greeting inicial.

        Returns:
            ``{ok, data}`` con ``session_id``, ``state='greeting'``,
            ``greeting_message`` y ``created_at`` ISO-8601.
        """
        try:
            Session = request.env["chatbot.session"].sudo()
            session = Session._create_with_greeting()
            return _ok(
                {
                    "session_id": session.id,
                    "state": session.state,
                    "greeting_message": Session._GREETING,
                    "created_at": session.create_date.isoformat(),
                }
            )
        except Exception:
            _logger.exception("Error creando sesión")
            return _err("INTERNAL_ERROR", "Ocurrió un problema interno.")

    # ------------------------------------------------------------------
    # /session/<id>/message
    # ------------------------------------------------------------------

    @route(
        "/chat_umayor/session/<int:session_id>/message",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
    )
    def session_message(self, session_id: int, content: str | None = None) -> dict:
        """Recibe un mensaje del usuario y devuelve la respuesta del bot.

        Args:
            session_id: Id de la sesión (viene en la URL).
            content: Texto del usuario. 1–2000 caracteres.

        Returns:
            Shape ``{ok, data|error}``. ``data`` incluye ``reply``,
            ``state``, ``product_code`` (null si no aplica) y
            ``suggestions``. Ante ``LLM_UNAVAILABLE`` también devuelve
            un ``reply`` canned para que la UI pueda mostrarlo.
        """
        # 1. Validación de input.
        if not content or not isinstance(content, str) or not content.strip():
            return _err(
                "VALIDATION_ERROR",
                "El mensaje está vacío.",
                fields={"content": "El mensaje no puede estar vacío."},
            )
        if len(content) > MAX_MESSAGE_LENGTH:
            return _err(
                "VALIDATION_ERROR",
                f"El mensaje supera los {MAX_MESSAGE_LENGTH} caracteres.",
                fields={"content": f"Máximo {MAX_MESSAGE_LENGTH} caracteres."},
            )

        # 2. Sesión válida y no cerrada.
        session, err = self._get_session_or_error(session_id)
        if err:
            return err

        try:
            Message = request.env["chatbot.message"].sudo()

            # 3. Persistir mensaje del usuario (texto original, no saneado).
            Message.create(
                {
                    "session_id": session.id,
                    "role": "user",
                    "content": content,
                }
            )

            # 4. Llamar a Gemini con historial saneado (últimos N=10).
            history = session._get_last_n()
            try:
                reply = GeminiClient(request.env).generate_reply(history)
            except LLMUnavailable:
                # Guardamos el canned como turno del asistente para que
                # el historial no quede "desbalanceado" (user sin
                # assistant). El estado no avanza.
                Message.create(
                    {
                        "session_id": session.id,
                        "role": "assistant",
                        "content": CANNED_LLM_FALLBACK,
                    }
                )
                return _err(
                    "LLM_UNAVAILABLE",
                    "El asistente no está disponible en este momento. "
                    "Intenta de nuevo en unos segundos.",
                    reply=CANNED_LLM_FALLBACK,
                    state=session.state,
                    product_code=session.product_code or None,
                )

            # 5. Persistir respuesta del asistente.
            Message.create(
                {
                    "session_id": session.id,
                    "role": "assistant",
                    "content": reply,
                }
            )

            # 6. FSM: clasificar intención y transicionar si corresponde.
            self._apply_transition(session, content)

            # 7. Armar response.
            return _ok(self._serialize_message_data(session, reply))

        except Exception:
            _logger.exception(
                "Error no controlado en /message sesión %s", session_id
            )
            return _err("INTERNAL_ERROR", "Ocurrió un problema interno.")

    # ------------------------------------------------------------------
    # /session/<id>/submit_data — STUB en v0.3
    # ------------------------------------------------------------------

    @route(
        "/chat_umayor/session/<int:session_id>/submit_data",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
    )
    def session_submit_data(self, session_id: int, **kwargs) -> dict:
        """Stub del endpoint ``/submit_data``.

        La implementación real llega en PLAN 08 (crear/actualizar
        ``res.partner``, productos SOAP/Depósito, cálculos, transición
        ``data_collection → review``). En v0.3 devuelve
        ``INVALID_STATE`` para que el front pueda cablearse sin
        romperse.
        """
        return _err(
            "INVALID_STATE",
            "Operación aún no disponible en esta versión.",
        )

    # ------------------------------------------------------------------
    # /session/<id>/sign — STUB en v0.3
    # ------------------------------------------------------------------

    @route(
        "/chat_umayor/session/<int:session_id>/sign",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
    )
    def session_sign(self, session_id: int, **kwargs) -> dict:
        """Stub del endpoint ``/sign``.

        La implementación real llega en PLAN 09 (Odoo Sign, contrato,
        plantilla, callback). En v0.3 devuelve ``INVALID_STATE``.
        """
        return _err(
            "INVALID_STATE",
            "Operación aún no disponible en esta versión.",
        )


