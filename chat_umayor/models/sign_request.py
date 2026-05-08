"""Extensión de ``sign.request`` para propagar la firma al chat_umayor.

Cuando todos los firmantes de un ``sign.request`` completan su firma,
Odoo invoca internamente el método ``_sign`` (Odoo 19). Aquí
interceptamos ese hook para buscar ``chat_umayor.contract`` vinculados
al request y dispararles ``_mark_signed()``, que a su vez cierra la
``chatbot.session`` asociada.

Diseño defensivo (§7 AGENTS):
    - El override llama ``super()`` **primero** y preserva su
      resultado. La lógica del chatbot no debe bloquear la firma real
      de Odoo si algo nuestro falla.
    - Cualquier excepción en ``_mark_signed`` se logea con
      ``logger.exception`` pero **no se propaga**: queremos que el
      request en Odoo Sign complete su ciclo normal, aunque nuestra
      capa quede inconsistente (se puede recuperar manualmente).
    - Filtramos estrictamente por ``sign_request_id`` de
      ``chat_umayor.contract``: no tocamos requests ajenos al módulo
      en tenants que usen Odoo Sign para otros flujos.

Riesgo conocido (PLAN 09): el nombre exacto ``_sign`` puede variar
entre versiones menores de Odoo 19. Si staging muestra que el hook
real es otro (``_sign_final``, ``_action_sign``, callback via
``write`` con ``state='signed'``), el override se adapta en un fix
pequeño y aislado.
"""

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class SignRequest(models.Model):
    """Override acotado de ``sign.request`` para callback a ``chat_umayor``."""

    _inherit = "sign.request"

    def _sign(self, *args, **kwargs):
        """Intercepta la firma para propagar a ``chat_umayor.contract``.

        Llama a ``super()._sign`` y luego busca contratos vinculados
        a estos requests. La propagación es **best-effort**: si
        levanta, solo se logea; la firma real nunca se bloquea.
        """
        result = super()._sign(*args, **kwargs)
        try:
            self._notify_chat_umayor_contracts()
        except Exception:
            _logger.exception(
                "Error propagando firma a chat_umayor.contract "
                "(requests: %s)",
                self.ids,
            )
        return result

    def _notify_chat_umayor_contracts(self) -> None:
        """Marca como firmados los contratos vinculados a estos requests.

        Busca ``chat_umayor.contract`` con ``sign_request_id in self.ids``
        y estado ``signing``, y llama a ``_mark_signed()`` sobre cada
        uno. Los contratos ya ``signed`` se ignoran (idempotente).
        """
        if not self:
            return
        contracts = (
            self.env["chat_umayor.contract"]
            .sudo()
            .search(
                [
                    ("sign_request_id", "in", self.ids),
                    ("state", "=", "signing"),
                ]
            )
        )
        for contract in contracts:
            try:
                contract._mark_signed()
            except Exception:
                _logger.exception(
                    "Fallo marcando contrato %s como firmado tras "
                    "callback de sign.request %s",
                    contract.id,
                    contract.sign_request_id.id,
                )
