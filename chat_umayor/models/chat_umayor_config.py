from odoo import fields, models


class ChatUmayorConfig(models.TransientModel):
    _name = "chat.umayor.config"
    _description = "Configuración Chat UMayor"

    gemini_api_key = fields.Char(string="Gemini API Key")
    gemini_model = fields.Char(string="Modelo Gemini", default="gemini-2.5-flash-lite")
    gemini_timeout = fields.Integer(string="Timeout (s)", default=15)
    gemini_system_prompt = fields.Text(string="System Prompt")
    sign_template_id = fields.Many2one(comodel_name="sign.template", string="Plantilla de firma")

    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        get = lambda key, default="": self.env["ir.config_parameter"].sudo().get_param(key, default)
        res.update({
            "gemini_api_key": get("chat_umayor.gemini_api_key"),
            "gemini_model": get("chat_umayor.gemini_model", "gemini-2.5-flash-lite"),
            "gemini_timeout": int(get("chat_umayor.gemini_timeout_seconds", "15") or 15),
            "gemini_system_prompt": get("chat_umayor.system_prompt"),
        })
        template_id = get("chat_umayor.sign_template_id")
        if template_id:
            res["sign_template_id"] = int(template_id)
        return res

    def save(self):
        set_param = self.env["ir.config_parameter"].sudo().set_param
        set_param("chat_umayor.gemini_api_key", self.gemini_api_key or "")
        set_param("chat_umayor.gemini_model", self.gemini_model or "gemini-2.5-flash-lite")
        set_param("chat_umayor.gemini_timeout_seconds", str(self.gemini_timeout or 15))
        set_param("chat_umayor.system_prompt", self.gemini_system_prompt or "")
        if self.sign_template_id:
            set_param("chat_umayor.sign_template_id", str(self.sign_template_id.id))
        return {"type": "ir.actions.client", "tag": "reload"}
