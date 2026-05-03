# -*- coding: utf-8 -*-
"""
Modelo de Sesión de Chat
========================
Representa UNA conversación completa entre un usuario y el bot.
Cada vez que un visitante abre el widget, se crea (o reabre) una sesión.

Diseño:
- Identificada por un token UUID (no por el ID interno) para que el
  frontend pueda referenciarla sin exponer datos internos.
- Estado de máquina: draft -> active -> awaiting_otp -> awaiting_signature
  -> completed / abandoned.
- Vinculada opcionalmente a un partner (cliente registrado en Odoo).
"""
import uuid
from odoo import models, fields, api


class ChatSession(models.Model):
    _name = 'chat.umayor.session'
    _description = 'Sesión de Chat UMayor'
    _order = 'create_date desc'
    _rec_name = 'token'

    token = fields.Char(
        string='Token',
        required=True,
        index=True,
        copy=False,
        default=lambda self: str(uuid.uuid4()),
        help='Identificador único de la sesión, usado por el frontend.',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente',
        ondelete='set null',
        help='Cliente asociado, si el visitante se identifica.',
    )
    visitor_name = fields.Char(string='Nombre del visitante')
    visitor_email = fields.Char(string='Correo del visitante')
    visitor_phone = fields.Char(string='Teléfono del visitante')

    state = fields.Selection(
        [
            ('draft', 'Borrador'),
            ('active', 'Activa'),
            ('awaiting_otp', 'Esperando OTP'),
            ('awaiting_signature', 'Esperando firma'),
            ('completed', 'Completada'),
            ('abandoned', 'Abandonada'),
        ],
        string='Estado',
        default='draft',
        required=True,
    )

    product_id = fields.Many2one(
        'chat.umayor.product',
        string='Producto financiero',
        help='Producto que el cliente está cotizando/contratando.',
    )

    # NOTA: No usamos Many2one a 'sign.request' porque obligaría a que el
    # módulo Sign esté instalado siempre. En su lugar guardamos el ID y
    # un nombre de modelo, así el módulo carga aunque Sign no esté presente.
    sign_request_ref = fields.Reference(
        selection=[('sign.request', 'Solicitud de firma')],
        string='Solicitud de firma',
        help='Referencia dinámica a la solicitud de firma de Odoo Sign. '
             'Solo se llena si el módulo Sign está instalado.',
    )

    message_ids = fields.One2many(
        'chat.umayor.message',
        'session_id',
        string='Mensajes',
    )
    message_count = fields.Integer(
        string='N° de mensajes',
        compute='_compute_message_count',
    )

    response_avg_ms = fields.Float(
        string='Tiempo medio de respuesta (ms)',
        compute='_compute_response_avg_ms',
        help='Indicador de viabilidad: meta < 5000 ms.',
    )

    @api.depends('message_ids')
    def _compute_message_count(self):
        for rec in self:
            rec.message_count = len(rec.message_ids)

    @api.depends('message_ids.response_time_ms')
    def _compute_response_avg_ms(self):
        for rec in self:
            bot_msgs = rec.message_ids.filtered(
                lambda m: m.role == 'bot' and m.response_time_ms > 0
            )
            if bot_msgs:
                total = sum(bot_msgs.mapped('response_time_ms'))
                rec.response_avg_ms = total / len(bot_msgs)
            else:
                rec.response_avg_ms = 0.0

    def action_mark_completed(self):
        """Cierra la sesión como completada (por ejemplo, después de firmar)."""
        self.write({'state': 'completed'})