"""Modelo ``chat_umayor.contract``: contrato generado tras submit_data.

Representa el acuerdo firmable resultado del flujo del chatbot. Se
crea cuando el endpoint ``/sign`` dispara ``_launch_signature`` sobre
la sesión, y su ciclo de vida refleja el de ``sign.request``:

    draft → signing → signed
                   ↘ cancelled

Invariante: **un contrato por sesión** (constraint SQL). Los datos
del partner se denormalizan (snapshot) en ``partner_name/vat/email/
phone`` para que el contrato siga siendo auditable aunque el
``res.partner`` cambie o se anonimice tras la firma.

El contrato **no** recalcula: copia ``product_data`` y ``calculated``
desde ``session.submit_summary`` (JSON ya resuelto en PLAN 08).

Para la integración con Odoo Sign ver ``sign_request.py`` (override
de ``_sign`` que propaga la firma a ``_mark_signed``) y
``chatbot_session._launch_signature``.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError  # noqa: F401  (uso futuro)

_logger = logging.getLogger(__name__)


class ChatbotContract(models.Model):
    """Contrato firmable asociado a una sesión del chatbot."""

    _name = "chat_umayor.contract"
    _description = "Chat UMayor — Contrato"
    _order = "create_date desc, id desc"

    # ------------------------------------------------------------------
    # Relaciones
    # ------------------------------------------------------------------

    session_id = fields.Many2one(
        comodel_name="chatbot.session",
        string="Sesión",
        required=True,
        ondelete="restrict",
        index=True,
        help="Sesión del chatbot que originó el contrato. "
        "``restrict`` impide borrar la sesión mientras exista el contrato.",
    )

    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Cliente",
        required=True,
        ondelete="restrict",
        help="Cliente titular del contrato. ``restrict`` evita "
        "quedarnos con contratos huérfanos si alguien borra el partner.",
    )

    sign_request_id = fields.Many2one(
        comodel_name="sign.request",
        string="Solicitud de firma",
        ondelete="set null",
        help="``sign.request`` asociado en Odoo Sign. Si el request "
        "se elimina conservamos el contrato (queda en cancelled) "
        "para auditoría.",
    )

    # ------------------------------------------------------------------
    # Snapshot denormalizado del partner (inmutable tras create)
    # ------------------------------------------------------------------
    # Se copian al crear el contrato para auditoría: aunque el
    # res.partner cambie de email/teléfono o se anonimice en el
    # futuro, el contrato conserva los datos tal como estaban al
    # firmarse. readonly=True es convención UI de Odoo (no constraint
    # de BD); para inmutabilidad dura haría falta un write override
    # — no se considera necesario en v0.5.

    partner_name = fields.Char(
        string="Nombre (snapshot)",
        required=True,
        readonly=True,
        help="Nombre del cliente al momento de la firma.",
    )
    partner_vat = fields.Char(
        string="RUT (snapshot)",
        required=True,
        readonly=True,
        help="RUT normalizado a NNNNNNNN-D al momento de la firma.",
    )
    partner_email = fields.Char(
        string="Email (snapshot)",
        readonly=True,
    )
    partner_phone = fields.Char(
        string="Teléfono (snapshot)",
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Datos del producto
    # ------------------------------------------------------------------

    product_code = fields.Selection(
        selection=[
            ("soap", "SOAP"),
            ("deposit", "Depósito a Plazo"),
        ],
        string="Producto",
        required=True,
        help="Producto contratado.",
    )
    product_data_json = fields.Text(
        string="Datos del producto (JSON)",
        help="Payload exacto de ``product_data`` del formulario, "
        "serializado como JSON.",
    )
    calculated_json = fields.Text(
        string="Cálculo (JSON)",
        help="Resultado del cálculo (prima SOAP o interés depósito) "
        "resuelto al firmar, serializado como JSON.",
    )

    # ------------------------------------------------------------------
    # Helpers para QWeb (evita parsear JSON en la plantilla)
    # ------------------------------------------------------------------

    def _product_data(self) -> dict:
        try:
            import json
            return json.loads(self.product_data_json or "{}")
        except Exception:
            return {}

    def _calculated_data(self) -> dict:
        try:
            import json
            return json.loads(self.calculated_json or "{}")
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Estado y metadatos
    # ------------------------------------------------------------------

    state = fields.Selection(
        selection=[
            ("draft", "Borrador"),
            ("signing", "En firma"),
            ("signed", "Firmado"),
            ("cancelled", "Cancelado"),
        ],
        string="Estado",
        default="draft",
        required=True,
        index=True,
        copy=False,
    )
    signed_at = fields.Datetime(
        string="Firmado en",
        readonly=True,
        copy=False,
    )
    reference = fields.Char(
        string="Referencia",
        readonly=True,
        copy=False,
        index=True,
        help="Identificador legible tipo ``CH-000017``. Se asigna en "
        "``create`` una vez que el ORM genera el id numérico.",
    )

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    _session_id_unique = models.Constraint(
        "unique(session_id)",
        "Ya existe un contrato para esta sesión.",
    )

    # ------------------------------------------------------------------
    # Create: asignar reference tras obtener id
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """Crea registros y asigna ``reference`` tipo ``CH-NNNNNN``.

        El ``reference`` depende del ``id`` generado por la BD, que
        sólo existe tras ``super().create()``. Odoo 19 rechaza
        ``@api.depends('id')`` en un computed field; por eso
        sobreescribimos ``create`` y seteamos el campo manualmente
        una vez tenemos el id. Si el llamador provee ``reference``
        en ``vals``, se respeta (caso import/migración).
        """
        records = super().create(vals_list)
        for rec in records:
            if not rec.reference:
                rec.reference = f"CH-{rec.id:06d}"
        return records

    # ------------------------------------------------------------------
    # Transiciones
    # ------------------------------------------------------------------

    def _mark_signed(self) -> None:
        """Marca el contrato como firmado y cierra la sesión asociada.

        Llamado por el override de ``sign.request._sign`` cuando la
        firma se completa (todos los firmantes firmaron). Idempotente:
        si ya está en ``signed``, no-op; no vuelve a transicionar la
        sesión.

        Raises:
            UserError: Si el contrato no está en ``signing`` (estado
                inconsistente, ej. alguien lo canceló manualmente).
        """
        self.ensure_one()
        if self.state == "signed":
            # Idempotente: la firma puede dispararse más de una vez
            # en casos de retry del módulo ``sign``.
            return
        if self.state != "signing":
            raise UserError(
                _(
                    "No se puede marcar como firmado un contrato en "
                    "estado %(state)s."
                )
                % {"state": self.state}
            )

        self.write(
            {
                "state": "signed",
                "signed_at": fields.Datetime.now(),
            }
        )
        # Cierra la sesión. Si el FSM rechaza (estado inconsistente),
        # logeamos y seguimos: la firma ya está hecha, no podemos
        # deshacerla, y queremos conservar ``state=signed`` en el
        # contrato para auditoría.
        try:
            self.session_id._do_transition("closed")
        except Exception:
            _logger.exception(
                "No se pudo cerrar la sesión %s tras firmar el "
                "contrato %s; el contrato queda en signed.",
                self.session_id.id,
                self.id,
            )

    def _cancel(self) -> None:
        """Marca el contrato como cancelado. Reservado para uso futuro."""
        self.ensure_one()
        if self.state == "signed":
            raise UserError(_("No se puede cancelar un contrato ya firmado."))
        self.state = "cancelled"

    # ------------------------------------------------------------------
    # URL pública de firma
    # ------------------------------------------------------------------

    def _get_sign_url(self) -> str:
        """Devuelve la URL pública donde el cliente firma el documento.

        En Odoo 19 la URL habitual es
        ``/sign/document/<request_id>/<access_token>``, con
        ``access_token`` viviendo en ``sign.request.item`` (uno por
        firmante). Si hay un único firmante, tomamos su token; si hay
        varios, devolvemos el del primero (nuestro caso típico: un
        cliente único).

        Si la estructura exacta de Odoo 19 resulta diferente en
        staging (el campo o el path pueden cambiar), se corrige aquí
        sin tocar el resto del flujo.

        Returns:
            URL relativa apta para abrir en navegador.

        Raises:
            UserError: Si el contrato no tiene ``sign_request_id``
                asociado o si el request no tiene firmantes.
        """
        self.ensure_one()
        if not self.sign_request_id:
            raise UserError(
                _("El contrato no tiene solicitud de firma asociada.")
            )
        sign_request = self.sign_request_id.sudo()
        items = getattr(sign_request, "request_item_ids", False)
        if items:
            first_item = items[0]
            token = getattr(first_item, "access_token", False)
            if token:
                return f"/sign/document/{sign_request.id}/{token}"
        # Fallback: URL sin token (válida si el usuario está logueado
        # como firmante). Documentamos que el front puede recibirla.
        return f"/sign/document/{sign_request.id}"
