"""Modelo de sesión del chatbot con máquina de estados (FSM).

La sesión es la unidad de conversación del chatbot bancario. Su estado
(``state``) rige qué puede pedir el usuario y qué puede responder el
bot. Las transiciones están definidas en §6 de ``AGENTS.md`` local:

    greeting → discovery → product_info → data_collection
             → review → signing → closed
                     ↑___________________|
                     (cambio de producto)

Toda transición pasa por ``_transition_to_<estado>()`` y valida contra
el mapa ``_ALLOWED_TRANSITIONS``. Intentar una transición no permitida
levanta ``UserError`` con un mensaje en español apto para mostrar al
usuario final.

El modelo es el único responsable del FSM: ni el controller ni Gemini
deben setear ``state`` directamente.
"""

import unicodedata

from odoo import _, fields, models
from odoo.exceptions import UserError


class ChatbotSession(models.Model):
    """Sesión de conversación del chatbot bancario."""

    _name = "chatbot.session"
    _description = "Chatbot Session"

    # Saludo inicial que se registra como primer ``chatbot.message``
    # (rol ``assistant``) al crear la sesión vía ``_create_with_greeting``.
    # El front lo muestra tal cual sin llamar a ``/message`` primero.
    _GREETING = (
        "Hola, soy el asistente virtual de Banco UMayor. "
        "Puedo ayudarte a contratar un SOAP o un Depósito a Plazo. "
        "¿Qué te interesa?"
    )

    # Número máximo de mensajes que ``_get_last_n`` devuelve por defecto.
    # Coincide con el N=10 documentado en §7 AGENTS local ("Envío de
    # contexto").
    _DEFAULT_HISTORY_LIMIT = 10

    # Mapa único de transiciones permitidas. Fuente de verdad del FSM.
    # Forma: {estado_actual: (estados_destino_permitidos, ...)}.
    _ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
        "greeting": ("discovery",),
        "discovery": ("product_info",),
        "product_info": ("discovery", "data_collection"),
        "data_collection": ("review",),
        "review": ("signing",),
        "signing": ("closed",),
        "closed": (),
    }

    state = fields.Selection(
        selection=[
            ("greeting", "Saludo"),
            ("discovery", "Descubrimiento"),
            ("product_info", "Información del producto"),
            ("data_collection", "Recolección de datos"),
            ("review", "Revisión"),
            ("signing", "Firma"),
            ("closed", "Cerrada"),
        ],
        string="Estado",
        default="greeting",
        required=True,
        copy=False,
        index=True,
        help="Estado actual de la conversación. Rige qué transiciones "
        "son válidas (ver _ALLOWED_TRANSITIONS).",
    )

    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Cliente",
        help="Cliente asociado a la sesión. Se completa cuando el "
        "usuario envía el formulario de datos (endpoint /submit_data).",
    )

    product_code = fields.Selection(
        selection=[
            ("soap", "SOAP"),
            ("deposit", "Depósito a Plazo"),
        ],
        string="Producto",
        help="Producto elegido por el cliente en la fase de descubrimiento.",
    )

    message_ids = fields.One2many(
        comodel_name="chatbot.message",
        inverse_name="session_id",
        string="Mensajes",
        help="Historial de mensajes de la conversación, ordenado "
        "cronológicamente.",
    )

    # ------------------------------------------------------------------
    # Motor genérico del FSM
    # ------------------------------------------------------------------

    def _assert_transition(self, target: str) -> None:
        """Valida que la transición del estado actual a ``target`` sea legal.

        Args:
            target: Estado destino al que se quiere transicionar.

        Raises:
            UserError: Si la transición no está en ``_ALLOWED_TRANSITIONS``.
        """
        self.ensure_one()
        allowed = self._ALLOWED_TRANSITIONS.get(self.state, ())
        if target not in allowed:
            raise UserError(
                _(
                    "No se puede pasar del estado %(current)s a %(target)s. "
                    "Transición inválida."
                )
                % {"current": self.state, "target": target}
            )

    def _do_transition(self, target: str) -> None:
        """Valida y aplica la transición al estado ``target``.

        Args:
            target: Estado destino.
        """
        self._assert_transition(target)
        self.state = target

    # ------------------------------------------------------------------
    # Transiciones públicas (una por estado destino)
    # ------------------------------------------------------------------

    def _transition_to_greeting(self) -> None:
        """Transiciona a ``greeting``. En la práctica nunca es válida."""
        self._do_transition("greeting")

    def _transition_to_discovery(self) -> None:
        """Transiciona a ``discovery``."""
        self._do_transition("discovery")

    def _transition_to_product_info(self) -> None:
        """Transiciona a ``product_info``."""
        self._do_transition("product_info")

    def _transition_to_data_collection(self) -> None:
        """Transiciona a ``data_collection``."""
        self._do_transition("data_collection")

    def _transition_to_review(self) -> None:
        """Transiciona a ``review``."""
        self._do_transition("review")

    def _transition_to_signing(self) -> None:
        """Transiciona a ``signing``."""
        self._do_transition("signing")

    def _transition_to_closed(self) -> None:
        """Transiciona a ``closed`` (estado terminal)."""
        self._do_transition("closed")

    # ------------------------------------------------------------------
    # Helpers de historial para el wrapper Gemini
    # ------------------------------------------------------------------

    def _get_last_n(self, n: int | None = None) -> list[dict]:
        """Devuelve los últimos ``n`` mensajes saneados para el LLM.

        El historial se entrega en orden cronológico ascendente (el
        ``_order`` del modelo ``chatbot.message`` ya lo garantiza).
        Cada ``content`` pasa por ``chatbot.message._sanitize_for_llm()``
        antes de salir del modelo, para que el wrapper de Gemini no
        tenga que conocer reglas de PII.

        Args:
            n: Límite de mensajes (los más recientes). ``None`` usa
                ``_DEFAULT_HISTORY_LIMIT`` (10, §7 AGENTS).

        Returns:
            Lista de dicts ``{"role": ..., "content": ...}`` en orden
            cronológico. Vacía si la sesión no tiene mensajes.
        """
        self.ensure_one()
        limit = self._DEFAULT_HISTORY_LIMIT if n is None else n
        messages = self.message_ids
        # ``messages`` ya viene ordenado asc por ``_order``; para
        # quedarnos con los últimos N recortamos desde el final.
        if limit is not None and len(messages) > limit:
            messages = messages[-limit:]
        return [
            {"role": msg.role, "content": msg._sanitize_for_llm()}
            for msg in messages
        ]

    # ------------------------------------------------------------------
    # Factory con greeting
    # ------------------------------------------------------------------

    def _create_with_greeting(self) -> "ChatbotSession":
        """Crea una sesión nueva y registra el saludo inicial.

        El saludo (``_GREETING``) se persiste como primer
        ``chatbot.message`` con ``role='assistant'`` para que quede en
        el historial y aparezca en la UI sin depender de una llamada
        extra a ``/message``.

        Returns:
            El recordset de la sesión recién creada.
        """
        session = self.sudo().create({})
        self.env["chatbot.message"].sudo().create(
            {
                "session_id": session.id,
                "role": "assistant",
                "content": self._GREETING,
            }
        )
        return session

    # ------------------------------------------------------------------
    # Clasificación de intención (heurística server-side)
    # ------------------------------------------------------------------

    # Palabras clave por estado. ``_classify_intent`` las busca tras
    # normalizar a minúsculas y quitar acentos. Limitación conocida:
    # heurística frágil ante sinónimos o errores ortográficos; se
    # reemplaza en PLAN 08 por respuesta estructurada de Gemini (JSON).
    _INTENT_KEYWORDS_DISCOVERY_SOAP = ("soap", "seguro obligatorio")
    _INTENT_KEYWORDS_DISCOVERY_DEPOSIT = ("deposito", "plazo", "ahorro")
    _INTENT_KEYWORDS_CONFIRM = ("si", "quiero", "contratar", "confirmo", "ok", "dale")
    _INTENT_KEYWORDS_CHANGE = ("otro", "cambiar", "cambio")
    _INTENT_KEYWORDS_NEGATION = ("no ", "no,", "nunca", "tampoco")

    @staticmethod
    def _normalize(text: str) -> str:
        """Pasa a minúsculas y quita acentos (NFD + drop combining).

        Uso interno de ``_classify_intent``.
        """
        if not text:
            return ""
        lower = text.strip().lower()
        nfd = unicodedata.normalize("NFD", lower)
        return "".join(ch for ch in nfd if not unicodedata.combining(ch))

    @classmethod
    def _classify_intent(cls, state: str, text: str) -> str | None:
        """Devuelve el estado destino sugerido por el mensaje del usuario.

        Heurística de keywords (normalizadas, sin acentos). Ver tabla
        D2 de PLAN 07. Es una **función pura**: no toca ORM ni tiene
        efectos. Si no hay transición clara, devuelve ``None``.

        Args:
            state: Estado actual de la sesión.
            text: Texto crudo del usuario.

        Returns:
            Estado destino (``"discovery"``, ``"product_info"``,
            ``"data_collection"``) o ``None`` si no hay que transicionar.
        """
        normalized = cls._normalize(text)
        if not normalized:
            return None

        # ``greeting``: cualquier mensaje no vacío abre la conversación.
        if state == "greeting":
            return "discovery"

        if state == "discovery":
            if any(k in normalized for k in cls._INTENT_KEYWORDS_DISCOVERY_SOAP):
                return "product_info"
            if any(k in normalized for k in cls._INTENT_KEYWORDS_DISCOVERY_DEPOSIT):
                return "product_info"
            return None

        if state == "product_info":
            # Negación tiene prioridad: "no quiero" no confirma aunque
            # contenga "quiero".
            if any(k in normalized for k in cls._INTENT_KEYWORDS_NEGATION):
                return None
            if any(k in normalized for k in cls._INTENT_KEYWORDS_CHANGE):
                return "discovery"
            if any(k in normalized for k in cls._INTENT_KEYWORDS_CONFIRM):
                return "data_collection"
            return None

        # data_collection, review, signing, closed: no avanzan por chat.
        return None

    @classmethod
    def _detect_product(cls, text: str) -> str | bool:
        """Devuelve ``'soap'``, ``'deposit'`` o ``False`` según el texto.

        Reutiliza las keywords de ``_classify_intent`` para decidir el
        ``product_code`` cuando el usuario transiciona de ``discovery``
        a ``product_info``. Pura; no toca ORM.
        """
        normalized = cls._normalize(text)
        if not normalized:
            return False
        if any(k in normalized for k in cls._INTENT_KEYWORDS_DISCOVERY_SOAP):
            return "soap"
        if any(k in normalized for k in cls._INTENT_KEYWORDS_DISCOVERY_DEPOSIT):
            return "deposit"
        return False
