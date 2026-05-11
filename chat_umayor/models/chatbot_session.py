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

import json
import logging
import unicodedata

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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
        "review": ("signing", "closed"),
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

    submit_summary = fields.Text(
        string="Resumen enviado",
        help="JSON con product_code, product_data y calculated tal "
        "como se resolvió en /submit_data. Lo consume /sign (PLAN 09) "
        "para generar el contrato sin recalcular.",
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
    _INTENT_KEYWORDS_DISCOVERY_DEPOSIT = ("deposito", "plazo", "ahorro", "ganar", "invertir", "inversion", "rentabilidad", "rendimiento")
    _INTENT_KEYWORDS_CONFIRM = ("si", "quiero", "contratar", "confirmo", "ok", "dale", "claro", "adelante", "vamos", "acepto", "sigamos", "perfecto", "hagamos")
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

    # ------------------------------------------------------------------
    # RUT chileno: normalización y validación módulo 11
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_rut_cl(rut: str) -> str:
        """Devuelve el RUT en formato canónico ``NNNNNNNN-D``.

        Quita puntos, espacios y guiones; pone el dígito verificador
        en mayúscula y re-inserta el guion antes del último carácter.
        No valida; solo normaliza. Para validar ver
        ``_validate_rut_cl``.

        Args:
            rut: RUT en cualquier formato (``"12.345.678-5"``,
                ``"12345678-5"``, ``"123456785"``, ``"12345678k"``).

        Returns:
            RUT normalizado o string vacío si la entrada es vacía.

        Raises:
            ValueError: Si el RUT tiene menos de 2 caracteres tras
                limpiar (no queda ni cuerpo + DV).
        """
        if not rut or not isinstance(rut, str):
            return ""
        cleaned = (
            rut.strip()
            .upper()
            .replace(".", "")
            .replace(" ", "")
            .replace("-", "")
        )
        if len(cleaned) < 2:
            raise ValueError("RUT demasiado corto para normalizar.")
        return f"{cleaned[:-1]}-{cleaned[-1]}"

    @staticmethod
    def _validate_rut_cl(rut: str) -> bool:
        """Valida un RUT chileno con algoritmo módulo 11.

        Acepta el RUT en cualquiera de los 3 formatos habituales
        (con puntos y guion, con guion solo, o pegado). Normaliza
        internamente antes de validar.

        Algoritmo:
            1. Cuerpo = dígitos sin DV; debe ser numérico (7-8 cifras).
            2. Multiplica cada dígito del cuerpo, de derecha a
               izquierda, por la serie cíclica ``[2,3,4,5,6,7]``.
            3. ``dv_calculado = 11 - (suma % 11)``.
            4. ``11 → "0"``, ``10 → "K"``, resto es el propio dígito.
            5. Compara con el DV de entrada.

        Args:
            rut: RUT en cualquier formato.

        Returns:
            ``True`` si es válido, ``False`` en cualquier otro caso
            (incluye entrada vacía, DV incorrecto, caracteres raros).
        """
        if not rut or not isinstance(rut, str):
            return False
        try:
            normalized = ChatbotSession._normalize_rut_cl(rut)
        except ValueError:
            return False
        body, dv = normalized[:-2], normalized[-1]
        if not body.isdigit() or len(body) < 7 or len(body) > 8:
            return False

        multipliers = [2, 3, 4, 5, 6, 7]
        total = 0
        for i, digit in enumerate(reversed(body)):
            total += int(digit) * multipliers[i % len(multipliers)]
        remainder = 11 - (total % 11)
        if remainder == 11:
            expected = "0"
        elif remainder == 10:
            expected = "K"
        else:
            expected = str(remainder)
        return dv == expected

    # ------------------------------------------------------------------
    # Partner idempotente por RUT
    # ------------------------------------------------------------------

    def _get_or_create_partner(self, partner_data: dict):
        """Busca ``res.partner`` por ``vat`` o lo crea.

        Idempotente: dos llamadas con el mismo RUT devuelven el mismo
        registro. Si el partner ya existe, actualiza los campos no
        vacíos de ``partner_data`` (name, email, phone). No elimina
        valores: si el nuevo payload no trae ``phone``, conserva el
        existente.

        Asume que ``partner_data['document_id']`` ya pasó por
        ``_validate_rut_cl`` (el controller lo valida antes).

        Args:
            partner_data: Dict con ``name`` (obligatorio),
                ``document_id`` (obligatorio), ``email`` y ``phone``
                (opcionales).

        Returns:
            El recordset ``res.partner`` (1 registro).
        """
        rut_norm = self._normalize_rut_cl(partner_data["document_id"])
        Partner = self.env["res.partner"].sudo()
        existing = Partner.search([("vat", "=", rut_norm)], limit=1)

        values: dict = {}
        for key, target in (("name", "name"), ("email", "email"), ("phone", "phone")):
            val = partner_data.get(key)
            if val:
                values[target] = val

        if existing:
            if values:
                existing.write(values)
            return existing

        values["vat"] = rut_norm
        if "name" not in values:
            # ``name`` es required en res.partner; si el controller
            # validó el payload, esto no debería pasar. Fallback
            # defensivo.
            values["name"] = rut_norm
        return Partner.create(values)

    # ------------------------------------------------------------------
    # Lanzamiento de firma (PLAN 09)
    # ------------------------------------------------------------------

    def _launch_signature(self) -> tuple["models.Model", str]:
        """Crea el contrato y lanza ``sign.request``; devuelve (contract, url).

        Flujo:
            1. Si ya existe un contrato para esta sesión:
               - En ``signing``: lo reutiliza (idempotente). Devuelve
                 el mismo ``sign_url``.
               - En ``signed``: levanta ``UserError`` (no se relanza
                 una firma completada).
               - En ``cancelled``/``draft``: levanta ``UserError``
                 para no dejar huella inconsistente.
            2. Valida que ``submit_summary`` esté presente (PLAN 08
               garantiza que exista tras ``/submit_data``).
            3. Resuelve ``sign.template`` desde
               ``ir.config_parameter`` ``chat_umayor.sign_template_id``.
               Si falta, levanta ``UserError`` con mensaje que el
               controller traduce a ``SIGN_UNAVAILABLE``.
            4. Crea el contrato con snapshot denormalizado del partner.
            5. Crea ``sign.request`` con la plantilla y el partner
               como firmante.
            6. Vincula ``contract.sign_request_id`` y pasa el contrato
               a ``signing``.

        Returns:
            Tupla ``(contract_record, sign_url)``.

        Raises:
            UserError: ``submit_summary`` faltante, plantilla no
                configurada, plantilla inexistente, o contrato en
                estado inconsistente.
        """
        self.ensure_one()
        Contract = self.env["chat_umayor.contract"].sudo()
        existing = Contract.search([("session_id", "=", self.id)], limit=1)

        if existing:
            if existing.state == "signing":
                # Idempotente: reutilizamos el contrato existente.
                return existing, existing._get_sign_url()
            if existing.state == "signed":
                raise UserError(_("El contrato ya fue firmado."))
            if existing.state == "cancelled":
                # Contrato cancelado por error previo: lo eliminamos
                # para permitir reintento limpio.
                existing.unlink()
            else:
                raise UserError(
                    _(
                        "Existe un contrato en estado %(state)s para esta "
                        "sesión; no se puede relanzar la firma."
                    )
                    % {"state": existing.state}
                )

        if not self.submit_summary:
            raise UserError(
                _("Faltan datos del formulario para generar el contrato.")
            )

        try:
            summary = json.loads(self.submit_summary)
        except (ValueError, TypeError) as exc:
            # submit_summary se serializa en el controller (PLAN 08)
            # con json.dumps; si llega corrupto es un bug grave.
            _logger.exception(
                "submit_summary corrupto en sesión %s: %s", self.id, exc
            )
            raise UserError(
                _("Datos del contrato corruptos. Contacta al administrador.")
            ) from exc

        # 1. Resolver plantilla de firma desde config.
        IrConfig = self.env["ir.config_parameter"].sudo()
        raw_template_id = IrConfig.get_param(
            "chat_umayor.sign_template_id", "0"
        )
        try:
            template_id = int(raw_template_id)
        except (ValueError, TypeError):
            template_id = 0
        if not template_id:
            raise UserError(
                _(
                    "La firma no está configurada. "
                    "Contacta al administrador."
                )
            )

        template = (
            self.env["sign.template"].sudo().browse(template_id).exists()
        )
        if not template:
            raise UserError(
                _(
                    "La plantilla de firma configurada no existe. "
                    "Contacta al administrador."
                )
            )

        # 2. Crear contrato con snapshot denormalizado del partner.
        partner = self.partner_id
        contract = Contract.create(
            {
                "session_id": self.id,
                "partner_id": partner.id,
                # Snapshot denormalizado (inmutable tras create):
                "partner_name": partner.name,
                "partner_vat": partner.vat,
                "partner_email": partner.email or False,
                "partner_phone": partner.phone or False,
                "product_code": summary["product_code"],
                "product_data_json": json.dumps(
                    summary["product_data"], ensure_ascii=False
                ),
                "calculated_json": json.dumps(
                    summary["calculated"], ensure_ascii=False
                ),
            }
        )

        # 3. Crear sign.request con la plantilla y firmantes.
        # Odoo Sign exige al menos un sign.request.item (firmante).
        # Obtenemos los roles únicos de los sign.item de la plantilla
        # y creamos un request.item por rol con el partner como firmante.
        try:
            sign_items = template.sign_item_ids
            roles = sign_items.mapped("responsible_id")

            if not roles:
                raise UserError(
                    _(
                        "La plantilla de firma no tiene campos de firma "
                        "configurados. Abre la plantilla en Odoo Sign, "
                        "dibuja al menos un bloque de firma y guarda."
                    )
                )

            request_item_vals = [
                (0, 0, {"partner_id": partner.id, "role_id": role.id})
                for role in roles
            ]

            sign_request_vals = {
                "template_id": template.id,
                "reference": contract.reference or _("Contrato UMayor"),
                "request_item_ids": request_item_vals,
            }
            sign_request = (
                self.env["sign.request"].sudo().create(sign_request_vals)
            )
        except UserError:
            contract.state = "cancelled"
            raise
        except Exception as exc:
            _logger.exception(
                "Error creando sign.request para contrato %s", contract.id
            )
            contract.state = "cancelled"
            raise UserError(
                _("No se pudo iniciar la firma: %(err)s")
                % {"err": exc}
            ) from exc

        contract.write(
            {
                "sign_request_id": sign_request.id,
                "state": "signing",
            }
        )

        return contract, contract._get_sign_url()

    # ------------------------------------------------------------------
    # Detección de producto (heurística)
    # ------------------------------------------------------------------

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
