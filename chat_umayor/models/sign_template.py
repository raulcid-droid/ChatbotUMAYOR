"""Fix para el GC de sign.template que falla por FK constraint.

El autovacuum de Odoo llama a _gc_sign_items() para borrar roles de firma
huérfanos (sign_item_role). El borrado falla porque sign_item.responsible_id
los referencia sin ON DELETE CASCADE. Este override limpia esas referencias
antes de que el GC intente borrar el rol.
"""

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class SignTemplate(models.Model):
    _inherit = "sign.template"

    def _gc_sign_items(self):
        # Intentamos el GC normal dentro de un savepoint.
        # Si falla por FK constraint, limpiamos las referencias bloqueantes
        # y reintentamos.
        try:
            with self.env.cr.savepoint():
                return super()._gc_sign_items()
        except Exception as exc:
            _logger.warning(
                "sign.template._gc_sign_items falló (%s); "
                "limpiando referencias FK bloqueantes y reintentando.",
                exc,
            )

        # Nullify responsible_id en sign_item cuyo rol ya no pertenece
        # a ningún template activo (son los que el GC quiere borrar).
        self.env.cr.execute("""
            UPDATE sign_item
            SET    responsible_id = NULL
            WHERE  responsible_id IS NOT NULL
              AND  responsible_id NOT IN (
                       SELECT DISTINCT si2.responsible_id
                       FROM   sign_item si2
                       JOIN   sign_template st ON st.id = si2.template_id
                       WHERE  si2.responsible_id IS NOT NULL
                         AND  st.active IS NOT FALSE
                   )
        """)

        return super()._gc_sign_items()
