"""Controllers HTTP del módulo ``chat_umayor``.

Expone los endpoints JSON-RPC documentados en ``docs/api.md``.
Estado en v0.5 (PLAN 09):

- ``/chat_umayor/ping``                              — smoke check (PLAN 03).
- ``/chat_umayor/session/new``                       — crea sesión + greeting.
- ``/chat_umayor/session/<id>/message``              — turno de chat con Gemini.
- ``/chat_umayor/session/<id>/submit_data``          — formulario (PLAN 08).
- ``/chat_umayor/session/<id>/sign``                 — firma real (PLAN 09).
- ``/chat_umayor/session/<id>/state``                — polling de estado (PLAN 09).

Shape de respuesta (dentro del ``result`` JSON-RPC)::

    {"ok": True,  "data":  {...}}
    {"ok": False, "error": {"code": "...", "message": "..."}}

Las transiciones del FSM se deciden server-side con
``chatbot.session._classify_intent`` (heurística de keywords). El
wrapper Gemini solo genera el texto de respuesta; no interpreta
intención en esta versión (se migra a JSON estructurado en PLAN 08).
"""

import json
import logging
import re

from odoo.exceptions import UserError
from odoo.http import Controller, request, route, Response

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

# Límites simples para el formulario (PLAN 08).
MAX_NAME_LENGTH = 120
MAX_EMAIL_LENGTH = 254
MAX_PHONE_LENGTH = 32
VALID_PRODUCT_CODES = ("soap", "deposit")

# Regex de email básico. No pretende cubrir RFC 5322: solo detecta
# payloads claramente mal formados. Mismo criterio que la
# sanitización de ``chatbot.message``.
_EMAIL_REGEX = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
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
    def _get_session_or_error(session_id: int, allow_closed: bool = False):
        """Busca la sesión y devuelve (session, None) o (None, err).

        Valida existencia y, por defecto, que no esté cerrada. El
        controller normalmente hace::

            session, err = self._get_session_or_error(session_id)
            if err: return err

        Args:
            session_id: Id del registro ``chatbot.session``.
            allow_closed: Si ``True``, no rechaza sesiones en
                ``state='closed'``. Lo usa ``/state`` para permitir
                consultar el estado final tras la firma.

        Returns:
            Tupla ``(recordset_sesion, None)`` si todo OK, o
            ``(None, dict_error)`` si la sesión no existe o está
            cerrada (con ``allow_closed=False``).
        """
        session = (
            request.env["chatbot.session"].sudo().browse(session_id).exists()
        )
        if not session:
            return None, _err(
                "SESSION_NOT_FOUND",
                "La sesión indicada no existe o expiró.",
            )
        if session.state == "closed" and not allow_closed:
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
    # Validación del payload de /submit_data
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_submit_payload(
        product_code: str | None,
        partner: dict | None,
        product_data: dict | None,
    ) -> dict[str, str]:
        """Valida el payload completo y devuelve todos los errores.

        Shape de salida: dict plano con claves en dot-notation
        (``partner.email``, ``product_data.amount``, etc.) y valor
        string en español. Diccionario vacío si todo es válido.

        Si ``product_code`` no es válido, se omiten las validaciones
        de ``product_data`` (no sabemos qué modelo aplicar). Se
        siguen validando los campos de ``partner``.
        """
        errors: dict[str, str] = {}

        # product_code
        code_valid = product_code in VALID_PRODUCT_CODES
        if not code_valid:
            errors["product_code"] = (
                "product_code inválido; debe ser 'soap' o 'deposit'."
            )

        # partner
        if not isinstance(partner, dict):
            errors["partner"] = "El objeto 'partner' es obligatorio."
        else:
            name = partner.get("name")
            if not name or not isinstance(name, str) or not name.strip():
                errors["partner.name"] = "El nombre es obligatorio."
            elif len(name) > MAX_NAME_LENGTH:
                errors["partner.name"] = (
                    f"Máximo {MAX_NAME_LENGTH} caracteres."
                )

            document_id = partner.get("document_id")
            if not document_id or not isinstance(document_id, str):
                errors["partner.document_id"] = "El RUT es obligatorio."
            else:
                Session = request.env["chatbot.session"].sudo()
                if not Session._validate_rut_cl(document_id):
                    errors["partner.document_id"] = (
                        "RUT inválido (dígito verificador incorrecto)."
                    )

            email = partner.get("email")
            if not email or not isinstance(email, str):
                errors["partner.email"] = "El email es obligatorio."
            elif len(email) > MAX_EMAIL_LENGTH or not _EMAIL_REGEX.match(email):
                errors["partner.email"] = "Email con formato inválido."

            phone = partner.get("phone")
            if phone is not None:
                if not isinstance(phone, str) or len(phone) > MAX_PHONE_LENGTH:
                    errors["partner.phone"] = (
                        f"Teléfono inválido (máximo {MAX_PHONE_LENGTH} caracteres)."
                    )

        # product_data: solo si product_code es válido; si no, no
        # sabemos qué modelo usar.
        if code_valid:
            Product = request.env[f"chat_umayor.product.{product_code}"].sudo()
            product = Product.search([], limit=1)
            if not product:
                # No debe pasar porque ``data/products.xml`` siembra
                # un singleton. Si pasa, es un bug de instalación.
                errors["product_data"] = (
                    "Producto no configurado. Contacta al administrador."
                )
            else:
                for field, msg in product._validate(product_data or {}).items():
                    errors[f"product_data.{field}"] = msg

        return errors

    # ------------------------------------------------------------------
    # /session/<id>/submit_data
    # ------------------------------------------------------------------

    @route(
        "/chat_umayor/session/<int:session_id>/submit_data",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
    )
    def session_submit_data(
        self,
        session_id: int,
        product_code: str | None = None,
        partner: dict | None = None,
        product_data: dict | None = None,
        **kwargs,
    ) -> dict:
        """Recibe el formulario, persiste el partner y calcula el resumen.

        Flujo:
            1. Valida sesión (existencia, no cerrada).
            2. Valida estado: solo ``data_collection`` procesa. Si
               está en ``review`` devuelve ``INVALID_STATE`` con
               mensaje específico (ya enviado).
            3. Valida payload (agregado, todos los errores de una).
            4. Fija ``product_code`` en la sesión.
            5. Crea/actualiza ``res.partner`` idempotente por RUT.
            6. Calcula prima/intereses vía el modelo del producto.
            7. Persiste ``submit_summary`` en la sesión (JSON).
            8. Transiciona ``data_collection → review``.

        Args:
            session_id: Id de la sesión (viene en la URL).
            product_code: ``"soap"`` o ``"deposit"``.
            partner: Dict con ``name``, ``document_id``, ``email``,
                ``phone`` (opcional).
            product_data: Dict con campos del producto (ver
                ``_validate`` de cada modelo).

        Returns:
            Shape ``{ok, data|error}``. En éxito, ``data`` incluye
            ``state='review'`` y ``summary`` con el cálculo.
        """
        session, err = self._get_session_or_error(session_id)
        if err:
            return err

        # Estado: solo data_collection procesa.
        if session.state == "review":
            return _err(
                "INVALID_STATE",
                "Los datos ya fueron enviados. Continúa con la firma.",
            )
        if session.state != "data_collection":
            return _err(
                "INVALID_STATE",
                "La sesión no está lista para recibir datos del formulario.",
            )

        # Validación agregada del payload.
        field_errors = self._validate_submit_payload(
            product_code, partner, product_data
        )
        if field_errors:
            return _err(
                "VALIDATION_ERROR",
                "Algunos campos son inválidos.",
                fields=field_errors,
            )

        try:
            # product_code del payload gana sobre el de la sesión
            # (el usuario puede haber cambiado de idea tras discovery).
            if session.product_code and session.product_code != product_code:
                _logger.info(
                    "Producto cambiado en submit (sesión %s): %s -> %s",
                    session.id,
                    session.product_code,
                    product_code,
                )
            session.product_code = product_code

            partner_rec = session._get_or_create_partner(partner)
            session.partner_id = partner_rec.id

            Product = request.env[
                f"chat_umayor.product.{product_code}"
            ].sudo()
            product_rec = Product.search([], limit=1)
            calculated = product_rec._calculate(product_data)

            session.submit_summary = json.dumps(
                {
                    "product_code": product_code,
                    "product_data": product_data,
                    "calculated": calculated,
                },
                ensure_ascii=False,
            )

            session._do_transition("review")

            return _ok(
                {
                    "state": session.state,
                    "summary": {
                        "product_name": product_rec.display_name,
                        "partner_name": partner_rec.name,
                        "calculated": calculated,
                    },
                }
            )
        except UserError as exc:
            # Transición FSM rechazada (no debería ocurrir tras las
            # validaciones de estado de arriba; defensa en profundidad).
            _logger.warning(
                "UserError en /submit_data sesión %s: %s",
                session_id,
                exc,
            )
            return _err("INVALID_STATE", str(exc))
        except Exception:
            _logger.exception(
                "Error no controlado en /submit_data sesión %s",
                session_id,
            )
            return _err("INTERNAL_ERROR", "Ocurrió un problema interno.")

    # ------------------------------------------------------------------
    # /session/<id>/sign
    # ------------------------------------------------------------------

    @route(
        "/chat_umayor/session/<int:session_id>/sign",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
    )
    def session_sign(self, session_id: int, **kwargs) -> dict:
        """Lanza el flujo de firma con Odoo Sign.

        Flujo:
            1. Valida sesión existente y no cerrada.
            2. Si está en ``signing``, devuelve el ``sign_url`` del
               contrato existente (idempotente).
            3. Si está en ``review`` y hay ``submit_summary``, crea
               contrato + ``sign.request`` vía ``_launch_signature``
               y transiciona a ``signing``.
            4. Otros estados → ``INVALID_STATE``.
            5. Falta ``submit_summary`` → ``MISSING_CONTRACT_DATA``.
            6. Plantilla no configurada o fallo al crear
               ``sign.request`` → ``SIGN_UNAVAILABLE``.

        Args:
            session_id: Id de la sesión (viene en la URL).

        Returns:
            Shape ``{ok, data|error}``. En éxito, ``data`` incluye
            ``contract_id``, ``sign_url`` y ``state``.
        """
        session, err = self._get_session_or_error(session_id)
        if err:
            return err

        # Idempotencia: reutiliza contrato existente si ya se está
        # firmando.
        if session.state == "signing":
            contract = (
                request.env["chat_umayor.contract"]
                .sudo()
                .search([("session_id", "=", session.id)], limit=1)
            )
            if contract and contract.state == "signing":
                try:
                    sign_url = contract._get_sign_url()
                except UserError as exc:
                    return _err("SIGN_UNAVAILABLE", str(exc))
                return _ok(
                    {
                        "contract_id": contract.id,
                        "sign_url": sign_url,
                        "state": session.state,
                    }
                )
            # signing en la sesión pero sin contrato 'signing' →
            # inconsistencia (ej. contrato cancelado manualmente).
            return _err(
                "INVALID_STATE",
                "La sesión está en firma pero el contrato no está "
                "disponible. Contacta al administrador.",
            )

        if session.state != "review":
            return _err(
                "INVALID_STATE",
                "La sesión no está lista para firmar.",
            )

        if not session.submit_summary:
            return _err(
                "MISSING_CONTRACT_DATA",
                "Faltan datos del formulario para generar el contrato.",
            )

        try:
            contract, sign_url = session._launch_signature()
            session._do_transition("signing")
            return _ok(
                {
                    "contract_id": contract.id,
                    "sign_url": sign_url,
                    "state": session.state,
                }
            )
        except UserError as exc:
            msg = str(exc)
            # Clasificamos por contenido del mensaje: las razones
            # "plantilla/firma no configurada/no existe" y "no se pudo
            # iniciar la firma" son ``SIGN_UNAVAILABLE``; "faltan
            # datos del formulario" es ``MISSING_CONTRACT_DATA``;
            # resto es ``INVALID_STATE``.
            lower = msg.lower()
            if (
                "plantilla" in lower
                or "firma no está configurada" in lower
                or "no se pudo iniciar la firma" in lower
            ):
                return _err("SIGN_UNAVAILABLE", msg)
            if "datos del formulario" in lower or "corruptos" in lower:
                return _err("MISSING_CONTRACT_DATA", msg)
            return _err("INVALID_STATE", msg)
        except Exception:
            _logger.exception(
                "Error no controlado en /sign sesión %s", session_id
            )
            return _err("INTERNAL_ERROR", "Ocurrió un problema interno.")

    # ------------------------------------------------------------------
    # /session/<id>/contrato.pdf — descarga del contrato en PDF
    # ------------------------------------------------------------------

    @route(
        "/chat_umayor/session/<int:session_id>/contrato.pdf",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def session_contract_pdf(self, session_id, **kwargs):
        """Genera y devuelve el contrato como PDF descargable.

        Crea el contrato si no existe, genera el PDF con el reporte
        QWeb y cierra la sesión. Reemplaza el flujo de Odoo Sign.
        """
        session = (
            request.env["chatbot.session"].sudo().browse(session_id).exists()
        )
        if not session or not session.submit_summary:
            return request.not_found()

        Contract = request.env["chat_umayor.contract"].sudo()
        contract = Contract.search(
            [("session_id", "=", session.id)], limit=1
        )

        if not contract:
            try:
                summary = json.loads(session.submit_summary)
                partner = session.partner_id
                contract = Contract.create(
                    {
                        "session_id": session.id,
                        "partner_id": partner.id,
                        "partner_name": partner.name,
                        "partner_vat": partner.vat or "",
                        "partner_email": partner.email or False,
                        "partner_phone": partner.phone or False,
                        "product_code": summary["product_code"],
                        "product_data_json": json.dumps(
                            summary["product_data"], ensure_ascii=False
                        ),
                        "calculated_json": json.dumps(
                            summary["calculated"], ensure_ascii=False
                        ),
                        "state": "signed",
                    }
                )
                # Cerrar la sesión directamente desde review
                if session.state == "review":
                    session._do_transition("closed")
            except Exception:
                _logger.exception(
                    "Error creando contrato para sesión %s", session_id
                )
                return Response("Error generando contrato.", status=500)

        try:
            Report = request.env["ir.actions.report"].sudo()
            pdf_content, _mime = Report._render_qweb_pdf(
                "chat_umayor.action_report_contract",
                res_ids=contract.ids,
            )
        except Exception:
            _logger.exception(
                "Error generando PDF para contrato %s", contract.id
            )
            return Response("Error generando PDF.", status=500)

        filename = f"Contrato_{contract.reference}.pdf"
        return request.make_response(
            pdf_content,
            headers=[
                ("Content-Type", "application/pdf"),
                (
                    "Content-Disposition",
                    f'attachment; filename="{filename}"',
                ),
                ("Content-Length", str(len(pdf_content))),
            ],
        )

    # ------------------------------------------------------------------
    # /session/<id>/state — polling ligero
    # ------------------------------------------------------------------

    @route(
        "/chat_umayor/session/<int:session_id>/state",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
    )
    def session_state(self, session_id: int, **kwargs) -> dict:
        """Devuelve el estado actual de la sesión y su contrato (si aplica).

        Endpoint barato pensado para polling del front mientras el
        usuario firma en otra pestaña. Acepta sesiones ``closed``
        (para que el polling vea el cierre tras la firma).

        Args:
            session_id: Id de la sesión (viene en la URL).

        Returns:
            Shape ``{ok, data}`` con:
                - ``state`` (string): estado actual del FSM.
                - ``product_code`` (string | null).
                - ``contract`` (object | null): si hay contrato
                  asociado, incluye ``state``, ``signed_at``
                  (ISO-8601 o null) y ``reference``.
        """
        session, err = self._get_session_or_error(
            session_id, allow_closed=True
        )
        if err:
            return err

        data = {
            "state": session.state,
            "product_code": session.product_code or None,
            "contract": None,
        }
        contract = (
            request.env["chat_umayor.contract"]
            .sudo()
            .search([("session_id", "=", session.id)], limit=1)
        )
        if contract:
            data["contract"] = {
                "state": contract.state,
                "signed_at": (
                    contract.signed_at.isoformat()
                    if contract.signed_at
                    else None
                ),
                "reference": contract.reference or None,
            }
        return _ok(data)


