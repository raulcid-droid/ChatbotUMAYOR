from odoo import models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    def action_open_chat_umayor_config(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Configuración Chat UMayor",
            "res_model": "chat.umayor.config",
            "view_mode": "form",
            "target": "new",
        }
