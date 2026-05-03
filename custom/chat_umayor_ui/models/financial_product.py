# -*- coding: utf-8 -*-
"""
Producto Financiero
===================
Catálogo simple de productos que el bot puede ofrecer (créditos de
consumo, tarjetas, cuentas, etc.). Si el módulo del compañero define
un modelo más completo, este puede deprecarse o extenderse.
"""
from odoo import models, fields


class FinancialProduct(models.Model):
    _name = 'chat.umayor.product'
    _description = 'Producto Financiero UMayor'
    _order = 'sequence, name'

    name = fields.Char(string='Nombre', required=True, translate=True)
    code = fields.Char(string='Código interno', required=True)
    sequence = fields.Integer(string='Orden', default=10)
    description = fields.Text(string='Descripción', translate=True)
    short_description = fields.Char(
        string='Descripción corta',
        help='Texto que el bot usa al ofrecer el producto.',
        translate=True,
    )
    active = fields.Boolean(default=True)

    # Datos comerciales mínimos (mock para la demo)
    interest_rate = fields.Float(string='Tasa de interés mensual (%)')
    min_amount = fields.Float(string='Monto mínimo')
    max_amount = fields.Float(string='Monto máximo')

    # Plantilla a enviar a Odoo Sign cuando el cliente acepta contratar
    # Referencia opcional a la plantilla de Odoo Sign (igual que sign_request_ref
    # en chat.umayor.session: usamos Reference para no obligar la instalación
    # del módulo `sign`).
    sign_template_ref = fields.Reference(
        selection=[('sign.template', 'Plantilla de firma')],
        string='Plantilla de contrato (Odoo Sign)',
        help='Plantilla que se envía al cliente para firmar. Solo aplica '
             'si el módulo Sign está instalado.',
    )

    # Odoo 19: la sintaxis _sql_constraints se reemplazó por models.Constraint
    _code_unique = models.Constraint(
        'UNIQUE(code)',
        'El código del producto debe ser único.',
    )