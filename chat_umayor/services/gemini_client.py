"""Wrapper aislado del SDK ``google-genai`` para el chatbot UMayor.

Este módulo es la **única** puerta de entrada al LLM desde el resto del
módulo Odoo. El objetivo es aislar la dependencia del SDK en un solo
lugar para que:

    - Los tests unitarios puedan mockear ``_get_client`` sin necesidad
      de tener la librería real instalada (import diferido).
    - Un cambio en la API del SDK se resuelva tocando un único archivo.
    - El controller (PLAN 07) dependa de esta clase, no del SDK.

Configuración (§7 AGENTS local). Se lee de ``ir.config_parameter``:

    chat_umayor.gemini_api_key          (fallback a env GEMINI_API_KEY)
    chat_umayor.gemini_model            (default: gemini-2.5-flash-lite)
    chat_umayor.system_prompt           (obligatorio; carga via data XML)
    chat_umayor.gemini_timeout_seconds  (default: 15)

Manejo de errores (§7 AGENTS):

    - RateLimit     -> backoff exponencial, máx 3 intentos, luego LLMUnavailable.
    - Timeout       -> 1 reintento, luego fallback canned (string, NO excepción).
    - Auth          -> log + LLMUnavailable (el controller mapea a LLM_UNAVAILABLE).
    - Otros         -> logger.exception, LLMUnavailable, nunca traceback al cliente.

Dependencia externa: ``pip install google-genai`` en el entorno Python
del servidor Odoo. El módulo se instala igual sin la lib (import
diferido); solo falla al invocar ``generate_reply()``.
"""

from __future__ import annotations

import logging
import os
import random
import time

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------

_DEFAULT_MODEL = "gemini-2.5-flash-lite"
_DEFAULT_TIMEOUT_SECONDS = 15
_MAX_RETRIES = 3
_BASE_BACKOFF_SECONDS = 0.5
_CANNED_FALLBACK = "Disculpa, tuve un problema. ¿Puedes repetir?"


# ---------------------------------------------------------------------
# Excepciones
# ---------------------------------------------------------------------


class LLMUnavailable(Exception):
    """El LLM no está disponible para responder.

    El controller (PLAN 07) la captura y la mapea al código
    ``LLM_UNAVAILABLE`` del catálogo de errores de ``docs/api.md §3``.
    """


# ---------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------


class GeminiClient:
    """Wrapper de alto nivel del SDK ``google-genai``.

    Uso típico desde PLAN 07::

        client = GeminiClient(env)
        reply = client.generate_reply([
            {"role": "user", "content": "Quiero contratar SOAP"},
            {"role": "assistant", "content": "..."},
        ])

    El caller es responsable de sanear los mensajes antes (llamar a
    ``chatbot.message._sanitize_for_llm()`` en cada entrada). El wrapper
    no conoce los modelos de Odoo: recibe dicts y devuelve strings.
    """

    def __init__(self, env) -> None:
        self.env = env

    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------

    def _get_param(self, key: str, default: str = "") -> str:
        """Lee un parámetro de ``ir.config_parameter``.

        Args:
            key: Clave del parámetro.
            default: Valor por defecto si no existe o está vacío.

        Returns:
            El valor como string.
        """
        value = self.env["ir.config_parameter"].sudo().get_param(key, default)
        return (value or default or "").strip()

    def _api_key(self) -> str:
        """Devuelve la API key.

        Primero intenta ``ir.config_parameter``; si está vacío, lee la
        variable de entorno ``GEMINI_API_KEY``. Si ambos están vacíos,
        levanta ``LLMUnavailable``.
        """
        key = self._get_param("chat_umayor.gemini_api_key")
        if not key:
            key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            _logger.error(
                "Gemini API key no configurada "
                "(ir.config_parameter 'chat_umayor.gemini_api_key' ni "
                "variable de entorno GEMINI_API_KEY)."
            )
            raise LLMUnavailable("API key no configurada")
        return key

    def _model_name(self) -> str:
        """Devuelve el identificador del modelo Gemini a usar."""
        return self._get_param("chat_umayor.gemini_model", _DEFAULT_MODEL)

    def _system_prompt(self) -> str:
        """Devuelve el system prompt.

        Si no está cargado significa que el data XML no se instaló
        correctamente; consideramos el estado inconsistente.
        """
        prompt = self._get_param("chat_umayor.system_prompt")
        if not prompt:
            _logger.error(
                "System prompt vacío. ¿Se cargó data/system_prompt.xml?"
            )
            raise LLMUnavailable("System prompt no configurado")
        return prompt

    def _timeout(self) -> int:
        """Devuelve el timeout en segundos para las llamadas al SDK."""
        raw = self._get_param(
            "chat_umayor.gemini_timeout_seconds", str(_DEFAULT_TIMEOUT_SECONDS)
        )
        try:
            return int(raw)
        except (TypeError, ValueError):
            return _DEFAULT_TIMEOUT_SECONDS

    # ------------------------------------------------------------------
    # SDK (import diferido)
    # ------------------------------------------------------------------

    def _get_client(self):
        """Construye el cliente del SDK Gemini.

        Import diferido de ``google.genai`` para que el módulo Odoo
        pueda instalarse sin la librería. Los tests mockean este método.
        """
        from google import genai  # noqa: PLC0415  lazy por diseño

        return genai.Client(api_key=self._api_key())

    # ------------------------------------------------------------------
    # Construcción del prompt
    # ------------------------------------------------------------------

    def _build_contents(self, messages: list[dict]) -> str:
        """Construye el string de entrada para Gemini.

        Estrategia minimalista y estable entre versiones del SDK:
        un único string que concatena system prompt + historial en
        formato ``Rol: contenido``. Si el SDK cambia su interfaz de
        mensajes estructurados, solo hay que tocar esta función.

        Args:
            messages: Lista de dicts con ``role`` y ``content``. Se
                asume que vienen en orden cronológico.

        Returns:
            Prompt completo listo para pasar a ``generate_content``.
        """
        parts: list[str] = [self._system_prompt(), ""]
        role_label = {
            "user": "Usuario",
            "assistant": "Asistente",
            "system": "Sistema",
        }
        for msg in messages:
            role = role_label.get(msg.get("role", ""), "Usuario")
            content = msg.get("content", "")
            parts.append(f"{role}: {content}")
        parts.append("Asistente:")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Llamada al SDK (un único punto de toque con google.genai)
    # ------------------------------------------------------------------

    def _call_sdk(self, prompt: str) -> str:
        """Invoca ``generate_content`` del SDK y devuelve el texto.

        Aislado para que las pruebas mockeen únicamente esta función.
        """
        client = self._get_client()
        response = client.models.generate_content(
            model=self._model_name(),
            contents=prompt,
        )
        # El SDK expone ``.text`` como atajo al primer candidate.text.
        text = getattr(response, "text", None)
        if not text:
            raise LLMUnavailable("Respuesta del LLM sin contenido")
        return text

    # ------------------------------------------------------------------
    # Clasificación de errores
    # ------------------------------------------------------------------

    @staticmethod
    def _is_rate_limit(exc: BaseException) -> bool:
        """Heurística: ¿la excepción es un rate limit (HTTP 429)?"""
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if code == 429:
            return True
        msg = str(exc).lower()
        return "429" in msg or "rate" in msg or "quota" in msg

    @staticmethod
    def _is_timeout(exc: BaseException) -> bool:
        """¿La excepción es un timeout?"""
        if isinstance(exc, TimeoutError):
            return True
        name = type(exc).__name__.lower()
        return "timeout" in name or "timeout" in str(exc).lower()

    @staticmethod
    def _is_auth_error(exc: BaseException) -> bool:
        """¿La excepción es un error de autenticación (401/403)?"""
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if code in (401, 403):
            return True
        msg = str(exc).lower()
        return (
            "401" in msg
            or "403" in msg
            or "unauthorized" in msg
            or "permission" in msg
            or "api key" in msg
        )

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def generate_reply(self, messages: list[dict]) -> str:
        """Genera la respuesta del asistente para el historial dado.

        Args:
            messages: Historial **ya saneado** (sin PII). Cada entrada
                es ``{"role": "user"|"assistant"|"system", "content": str}``.

        Returns:
            El texto de la respuesta. Ante timeout tras reintento,
            devuelve el fallback canned (string, no excepción).

        Raises:
            LLMUnavailable: Ante rate limit agotado, error de auth o
                cualquier otra excepción no clasificada. El controller
                lo mapea al código ``LLM_UNAVAILABLE`` del catálogo.
        """
        prompt = self._build_contents(messages)

        attempt = 0
        timeout_retried = False
        while True:
            attempt += 1
            try:
                return self._call_sdk(prompt)
            except LLMUnavailable:
                # Respuesta vacía del SDK: no es reintentable.
                raise
            except Exception as exc:
                if self._is_rate_limit(exc):
                    if attempt >= _MAX_RETRIES:
                        _logger.error(
                            "Gemini rate limit tras %s intentos: %s",
                            attempt,
                            exc,
                        )
                        raise LLMUnavailable("Rate limit") from exc
                    backoff = _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    backoff += random.uniform(0, _BASE_BACKOFF_SECONDS)
                    _logger.warning(
                        "Gemini rate limit (intento %s/%s), backoff %.2fs",
                        attempt,
                        _MAX_RETRIES,
                        backoff,
                    )
                    time.sleep(backoff)
                    continue

                if self._is_timeout(exc):
                    if timeout_retried:
                        _logger.warning(
                            "Gemini timeout tras reintento, usando fallback canned."
                        )
                        return _CANNED_FALLBACK
                    timeout_retried = True
                    _logger.warning("Gemini timeout, reintentando una vez.")
                    continue

                if self._is_auth_error(exc):
                    _logger.error("Gemini auth error: %s", exc)
                    raise LLMUnavailable("Auth error") from exc

                # Desconocido: log completo server-side, mensaje
                # genérico al cliente.
                _logger.exception("Error no clasificado llamando a Gemini")
                raise LLMUnavailable("Unknown error") from exc
