"""Expone la configuración de Gemini en Ajustes de Odoo.

Los 4 parámetros viven en ``ir.config_parameter`` (fuente de verdad)
pero se reflejan como campos de ``res.config.settings`` para que un
administrador pueda editarlos desde la UI sin tocar BD ni ficheros XML.

La vista XML que renderiza estos campos es opcional (PLAN 10). Sin
ella, los parámetros se siguen pudiendo setear directamente en
``ir.config_parameter`` o vía la API de Odoo.
"""

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Ajustes del módulo chat_umayor.

    Cada campo está ligado a un ``ir.config_parameter`` con la
    convención ``chat_umayor.<nombre>``. Odoo se encarga del get/set.
    """

    _inherit = "res.config.settings"

    chat_umayor_gemini_api_key = fields.Char(
        string="Gemini API Key",
        config_parameter="chat_umayor.gemini_api_key",
        help="Clave de API de Google Gemini. Si está vacía se usa la "
        "variable de entorno GEMINI_API_KEY como fallback.",
    )

    chat_umayor_gemini_model = fields.Char(
        string="Gemini Model",
        config_parameter="chat_umayor.gemini_model",
        default="gemini-2.5-flash-lite",
        help="Identificador del modelo Gemini. Por defecto "
        "gemini-2.5-flash-lite (familia Flash, variante económica).",
    )

    chat_umayor_system_prompt = fields.Text(
        string="System Prompt",
        config_parameter="chat_umayor.system_prompt",
        help="Prompt de sistema que recibe Gemini antes del historial. "
        "Editable sin redeploy; el valor inicial se carga desde "
        "data/system_prompt.xml al instalar.",
    )

    chat_umayor_gemini_timeout = fields.Integer(
        string="Gemini Timeout (s)",
        config_parameter="chat_umayor.gemini_timeout_seconds",
        default=15,
        help="Timeout en segundos para cada llamada al SDK. Por defecto "
        "15s. Bajar en producción si el SLA del front <5s se ajusta.",
    )
