"""Modelo de mensaje del chatbot y sanitización para el LLM.

Cada ``chatbot.message`` es una entrada del historial de la conversación,
vinculada a una ``chatbot.session``. Almacenamos el texto **original**
en BD (es la fuente de verdad del diálogo) y solo enviamos a Gemini
una versión **saneada** que reemplaza PII (RUT, email, teléfono,
tarjeta) por placeholders.

Cumple §7 de ``AGENTS.md`` local (apartado "Envío de contexto").

Fuera de alcance en este modelo:
    - Helper ``_get_last_n()`` para el wrapper de Gemini (PLAN 06).
    - Llamadas reales al LLM (PLAN 06).
    - Reconocimiento de nombres propios o direcciones (requiere NER).
"""

import re

from odoo import fields, models


class ChatbotMessage(models.Model):
    """Mensaje del historial de una sesión de chatbot."""

    _name = "chatbot.message"
    _description = "Chatbot Message"
    _order = "create_date asc, id asc"

    session_id = fields.Many2one(
        comodel_name="chatbot.session",
        string="Sesión",
        required=True,
        ondelete="cascade",
        index=True,
        help="Sesión a la que pertenece el mensaje.",
    )

    role = fields.Selection(
        selection=[
            ("user", "Usuario"),
            ("assistant", "Asistente"),
            ("system", "Sistema"),
        ],
        string="Rol",
        required=True,
        help="Quién emitió el mensaje: usuario final, el bot o el sistema.",
    )

    content = fields.Text(
        string="Contenido",
        required=True,
        help="Texto original tal como lo escribió el usuario o generó "
        "el bot. Nunca se modifica tras crearse.",
    )

    # ------------------------------------------------------------------
    # Sanitización para el LLM
    # ------------------------------------------------------------------

    # Patrones de PII que reemplazamos antes de enviar a Gemini.
    # Forma: (nombre_legible, regex compilada, placeholder).
    # El orden importa: aplicamos primero los más específicos (tarjeta
    # y teléfono con prefijo +56) para que no los coma el patrón de RUT.
    _SANITIZE_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
        # Tarjeta de crédito: 16 dígitos en 4 grupos de 4, separados
        # por espacio o guion (o sin separador).
        (
            "credit_card",
            re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
            "[TARJETA]",
        ),
        # Teléfono chileno: prefijo +56 obligatorio, con o sin espacios,
        # guiones o paréntesis. Acepta móviles (+56 9 XXXX XXXX) y fijos.
        (
            "phone_cl",
            re.compile(r"\+56[\s\-]?\(?\d\)?(?:[\s\-]?\d){7,8}"),
            "[TELEFONO]",
        ),
        # Email RFC-básico. Suficiente para PII; no validamos RFC 5322.
        (
            "email",
            re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
            "[EMAIL]",
        ),
        # RUT chileno con puntos y guion: 12.345.678-5 o 1.234.567-K.
        (
            "rut_formatted",
            re.compile(r"\b\d{1,2}\.\d{3}\.\d{3}-[\dkK]\b"),
            "[DOCUMENTO]",
        ),
        # RUT chileno con guion sin puntos: 12345678-5 o 1234567-K.
        (
            "rut_dashed",
            re.compile(r"\b\d{7,8}-[\dkK]\b"),
            "[DOCUMENTO]",
        ),
        # RUT chileno sin separadores: 8 o 9 dígitos pegados, con DV
        # numérico o K al final. Es el más agresivo: limitado a 8-9
        # caracteres para no capturar IDs u otros números largos.
        (
            "rut_plain",
            re.compile(r"\b\d{7,8}[\dkK]\b"),
            "[DOCUMENTO]",
        ),
    ]

    def _sanitize_for_llm(self) -> str:
        """Devuelve una versión del contenido sin PII, apta para el LLM.

        Reemplaza RUT, email, teléfono y tarjeta por placeholders. El
        texto original en ``self.content`` no se modifica: esta función
        siempre construye un string nuevo.

        Returns:
            El contenido con los patrones sensibles reemplazados por
            ``[DOCUMENTO]``, ``[EMAIL]``, ``[TELEFONO]``, ``[TARJETA]``.
            Si ``content`` está vacío, devuelve ``""``.
        """
        self.ensure_one()
        text = self.content or ""
        for _name, pattern, placeholder in self._SANITIZE_PATTERNS:
            text = pattern.sub(placeholder, text)
        return text
