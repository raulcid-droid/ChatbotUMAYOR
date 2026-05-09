from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    chat_umayor_gemini_api_key = fields.Char(
        string="Gemini API Key",
        config_parameter="chat_umayor.gemini_api_key",
    )
    chat_umayor_gemini_model = fields.Char(
        string="Modelo Gemini",
        config_parameter="chat_umayor.gemini_model",
        default="gemini-2.5-flash-lite",
    )
    chat_umayor_gemini_timeout = fields.Integer(
        string="Timeout (s)",
        config_parameter="chat_umayor.gemini_timeout_seconds",
        default=15,
    )
    chat_umayor_system_prompt = fields.Char(
        string="System Prompt",
        config_parameter="chat_umayor.system_prompt",
    )
    chat_umayor_sign_template_id = fields.Many2one(
        comodel_name="sign.template",
        string="Plantilla de firma",
        config_parameter="chat_umayor.sign_template_id",
    )

    def action_open_chat_umayor_config(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Configuración Chat UMayor",
            "res_model": "chat.umayor.config",
            "view_mode": "form",
            "target": "new",
        }
