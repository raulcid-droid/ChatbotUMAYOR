from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    chat_umayor_gemini_api_key = fields.Char(
        string="Gemini API Key",
        compute="_compute_chat_umayor",
        inverse="_set_gemini_api_key",
        store=False,
    )
    chat_umayor_gemini_model = fields.Char(
        string="Modelo Gemini",
        compute="_compute_chat_umayor",
        inverse="_set_gemini_model",
        store=False,
    )
    chat_umayor_gemini_timeout = fields.Integer(
        string="Timeout (s)",
        compute="_compute_chat_umayor",
        inverse="_set_gemini_timeout",
        store=False,
    )
    chat_umayor_system_prompt = fields.Char(
        string="System Prompt",
        compute="_compute_chat_umayor",
        inverse="_set_system_prompt",
        store=False,
    )
    chat_umayor_sign_template_id = fields.Many2one(
        comodel_name="sign.template",
        string="Plantilla de firma",
        compute="_compute_chat_umayor",
        inverse="_set_sign_template",
        store=False,
    )

    def _get_param(self, key, default=""):
        return self.env["ir.config_parameter"].sudo().get_param(key, default) or default

    def _set_param(self, key, value):
        self.env["ir.config_parameter"].sudo().set_param(key, value or "")

    @api.depends_context("uid")
    def _compute_chat_umayor(self):
        for rec in self:
            rec.chat_umayor_gemini_api_key = self._get_param("chat_umayor.gemini_api_key")
            rec.chat_umayor_gemini_model = self._get_param("chat_umayor.gemini_model", "gemini-2.5-flash-lite")
            timeout_raw = self._get_param("chat_umayor.gemini_timeout_seconds", "15")
            rec.chat_umayor_gemini_timeout = int(timeout_raw) if timeout_raw else 15
            rec.chat_umayor_system_prompt = self._get_param("chat_umayor.system_prompt")
            template_raw = self._get_param("chat_umayor.sign_template_id")
            rec.chat_umayor_sign_template_id = int(template_raw) if template_raw and template_raw.isdigit() else False

    def _set_gemini_api_key(self):
        self._set_param("chat_umayor.gemini_api_key", self.chat_umayor_gemini_api_key)

    def _set_gemini_model(self):
        self._set_param("chat_umayor.gemini_model", self.chat_umayor_gemini_model or "gemini-2.5-flash-lite")

    def _set_gemini_timeout(self):
        self._set_param("chat_umayor.gemini_timeout_seconds", str(self.chat_umayor_gemini_timeout or 15))

    def _set_system_prompt(self):
        self._set_param("chat_umayor.system_prompt", self.chat_umayor_system_prompt)

    def _set_sign_template(self):
        if self.chat_umayor_sign_template_id:
            self._set_param("chat_umayor.sign_template_id", str(self.chat_umayor_sign_template_id.id))
