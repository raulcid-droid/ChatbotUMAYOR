"""Tests del wrapper ``GeminiClient``.

Todos los tests mockean el SDK: cero llamadas reales a Gemini. La
estrategia principal es parchar ``_call_sdk`` (que es el único punto
donde el wrapper toca el SDK real). Para el test de construcción de
contents mockeamos solo ``_get_client`` y capturamos el prompt.

Tags: chat_umayor, post_install, -at_install (igual que los otros tests).
"""

from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.chat_umayor.services.gemini_client import (
    _CANNED_FALLBACK,
    _DEFAULT_MODEL,
    GeminiClient,
    LLMUnavailable,
)

# Logger del wrapper. Los tests que ejercen ramas de error emiten
# ``_logger.error(...)`` a propósito; silenciamos esa salida para no
# confundir el resumen de staging con falsos positivos (ver NOTES.md
# sesión 2026-05-07).
_GEMINI_LOGGER = "odoo.addons.chat_umayor.services.gemini_client"


# Excepciones "sintéticas" que imitan las del SDK sin importarlo.
class _FakeRateLimit(Exception):
    """Imita un rate limit 429 del SDK."""

    code = 429


class _FakeAuth(Exception):
    """Imita un 401/403 del SDK."""

    code = 401


class _FakeTimeout(TimeoutError):
    """Timeout estándar de Python."""


@tagged("chat_umayor", "post_install", "-at_install")
class TestGeminiClient(TransactionCase):
    """Config, retries, timeout, auth y construcción de prompt."""

    def setUp(self) -> None:
        super().setUp()
        self.Param = self.env["ir.config_parameter"].sudo()
        # Estado base: API key seteada para que los tests no choquen
        # con la env real. Cada test que pruebe fallback la vacía.
        self.Param.set_param("chat_umayor.gemini_api_key", "fake-key-for-tests")
        # System prompt: ponemos uno de prueba para no depender del
        # data XML cargado (en staging sí estará; en tests preferimos
        # ser explícitos).
        self.Param.set_param("chat_umayor.system_prompt", "Eres un bot de prueba.")
        # Reset de modelo y timeout a sus defaults (limpieza cruzada
        # entre tests).
        self.Param.set_param("chat_umayor.gemini_model", "")
        self.Param.set_param("chat_umayor.gemini_timeout_seconds", "")
        self.client = GeminiClient(self.env)

    # ------------------------------------------------------------------
    # Configuración: API key
    # ------------------------------------------------------------------

    def test_api_key_from_config_parameter(self) -> None:
        """El wrapper lee la API key de ``ir.config_parameter``."""
        self.Param.set_param("chat_umayor.gemini_api_key", "llave-config")
        self.assertEqual(self.client._api_key(), "llave-config")

    def test_api_key_fallback_to_env(self) -> None:
        """Si el param está vacío, usa ``GEMINI_API_KEY`` del entorno."""
        self.Param.set_param("chat_umayor.gemini_api_key", "")
        with patch.dict("os.environ", {"GEMINI_API_KEY": "env-llave"}):
            self.assertEqual(self.client._api_key(), "env-llave")

    @mute_logger(_GEMINI_LOGGER)
    def test_api_key_missing_raises_llm_unavailable(self) -> None:
        """Sin param ni env, ``_api_key()`` levanta ``LLMUnavailable``."""
        import os

        self.Param.set_param("chat_umayor.gemini_api_key", "")
        # Garantizamos que la env var no esté seteada durante el test,
        # sin importar el estado del CI. patch.dict con clear en la
        # clave específica la restaura al salir.
        env_backup = os.environ.pop("GEMINI_API_KEY", None)
        try:
            with self.assertRaises(LLMUnavailable):
                self.client._api_key()
        finally:
            if env_backup is not None:
                os.environ["GEMINI_API_KEY"] = env_backup

    # ------------------------------------------------------------------
    # Configuración: modelo y timeout
    # ------------------------------------------------------------------

    def test_default_model_is_flash_lite(self) -> None:
        """Sin override, el modelo default es ``gemini-2.5-flash-lite``."""
        self.assertEqual(self.client._model_name(), _DEFAULT_MODEL)
        self.assertEqual(_DEFAULT_MODEL, "gemini-2.5-flash-lite")

    def test_model_from_config_parameter(self) -> None:
        """El modelo puede sobreescribirse via config param."""
        self.Param.set_param("chat_umayor.gemini_model", "gemini-2.5-pro")
        self.assertEqual(self.client._model_name(), "gemini-2.5-pro")

    def test_timeout_default_is_fifteen_seconds(self) -> None:
        """Sin override, el timeout default es 15 segundos."""
        self.assertEqual(self.client._timeout(), 15)

    # ------------------------------------------------------------------
    # generate_reply: happy path
    # ------------------------------------------------------------------

    def test_generate_reply_happy_path(self) -> None:
        """Una respuesta válida del SDK se devuelve tal cual."""
        with patch.object(
            GeminiClient, "_call_sdk", return_value="Hola, ¿en qué ayudo?"
        ) as mock_call:
            reply = self.client.generate_reply(
                [{"role": "user", "content": "hola"}]
            )
        self.assertEqual(reply, "Hola, ¿en qué ayudo?")
        self.assertEqual(mock_call.call_count, 1)

    # ------------------------------------------------------------------
    # Retries ante rate limit
    # ------------------------------------------------------------------

    @mute_logger(_GEMINI_LOGGER)
    def test_generate_reply_retries_on_rate_limit(self) -> None:
        """Tras un 429, reintenta y devuelve la respuesta del 2º intento."""
        side_effects = [_FakeRateLimit("429 rate limit"), "ok"]
        with (
            patch.object(GeminiClient, "_call_sdk", side_effect=side_effects) as mock_call,
            patch("odoo.addons.chat_umayor.services.gemini_client.time.sleep"),
        ):
            reply = self.client.generate_reply(
                [{"role": "user", "content": "hola"}]
            )
        self.assertEqual(reply, "ok")
        self.assertEqual(mock_call.call_count, 2)

    @mute_logger(_GEMINI_LOGGER)
    def test_generate_reply_gives_up_after_max_retries(self) -> None:
        """Tras 3 rate limits consecutivos, levanta ``LLMUnavailable``."""
        with (
            patch.object(
                GeminiClient, "_call_sdk", side_effect=_FakeRateLimit("429")
            ) as mock_call,
            patch("odoo.addons.chat_umayor.services.gemini_client.time.sleep"),
        ):
            with self.assertRaises(LLMUnavailable):
                self.client.generate_reply(
                    [{"role": "user", "content": "hola"}]
                )
        self.assertEqual(mock_call.call_count, 3)

    # ------------------------------------------------------------------
    # Timeout: 1 retry, luego fallback canned (no excepción)
    # ------------------------------------------------------------------

    @mute_logger(_GEMINI_LOGGER)
    def test_generate_reply_timeout_retries_then_canned(self) -> None:
        """Ante timeout persistente, devuelve el fallback canned."""
        with (
            patch.object(
                GeminiClient, "_call_sdk", side_effect=_FakeTimeout("timeout")
            ) as mock_call,
            patch("odoo.addons.chat_umayor.services.gemini_client.time.sleep"),
        ):
            reply = self.client.generate_reply(
                [{"role": "user", "content": "hola"}]
            )
        self.assertEqual(reply, _CANNED_FALLBACK)
        self.assertEqual(mock_call.call_count, 2)

    @mute_logger(_GEMINI_LOGGER)
    def test_generate_reply_timeout_recovers_on_retry(self) -> None:
        """Si el 2º intento tras timeout funciona, devuelve esa respuesta."""
        side_effects = [_FakeTimeout("timeout"), "recuperado"]
        with (
            patch.object(GeminiClient, "_call_sdk", side_effect=side_effects) as mock_call,
            patch("odoo.addons.chat_umayor.services.gemini_client.time.sleep"),
        ):
            reply = self.client.generate_reply(
                [{"role": "user", "content": "hola"}]
            )
        self.assertEqual(reply, "recuperado")
        self.assertEqual(mock_call.call_count, 2)

    # ------------------------------------------------------------------
    # Auth error: levanta LLMUnavailable
    # ------------------------------------------------------------------

    @mute_logger(_GEMINI_LOGGER)
    def test_generate_reply_auth_error_raises(self) -> None:
        """Un 401 del SDK levanta ``LLMUnavailable``, sin reintentar."""
        with patch.object(
            GeminiClient, "_call_sdk", side_effect=_FakeAuth("401 unauthorized")
        ) as mock_call:
            with self.assertRaises(LLMUnavailable):
                self.client.generate_reply(
                    [{"role": "user", "content": "hola"}]
                )
        self.assertEqual(mock_call.call_count, 1)

    # ------------------------------------------------------------------
    # Error desconocido: log + LLMUnavailable
    # ------------------------------------------------------------------

    def test_generate_reply_unknown_error_logs_and_raises(self) -> None:
        """Una excepción no clasificada se logea con traceback y relevanta."""
        with patch.object(
            GeminiClient, "_call_sdk", side_effect=RuntimeError("boom")
        ):
            with self.assertLogs(
                "odoo.addons.chat_umayor.services.gemini_client", level="ERROR"
            ) as logs:
                with self.assertRaises(LLMUnavailable):
                    self.client.generate_reply(
                        [{"role": "user", "content": "hola"}]
                    )
        self.assertTrue(
            any("no clasificado" in record.getMessage().lower() for record in logs.records),
            f"No se logeó el error: {[r.getMessage() for r in logs.records]}",
        )

    # ------------------------------------------------------------------
    # _build_contents: system prompt y orden
    # ------------------------------------------------------------------

    def test_build_contents_includes_system_prompt(self) -> None:
        """El prompt construido incluye el system prompt configurado."""
        self.Param.set_param("chat_umayor.system_prompt", "PROMPT-DE-PRUEBA")
        prompt = self.client._build_contents(
            [{"role": "user", "content": "hola"}]
        )
        self.assertIn("PROMPT-DE-PRUEBA", prompt)

    def test_build_contents_respects_message_order(self) -> None:
        """El historial aparece en orden cronológico en el prompt."""
        messages = [
            {"role": "user", "content": "primero"},
            {"role": "assistant", "content": "segundo"},
            {"role": "user", "content": "tercero"},
        ]
        prompt = self.client._build_contents(messages)
        pos_first = prompt.find("primero")
        pos_second = prompt.find("segundo")
        pos_third = prompt.find("tercero")
        self.assertGreater(pos_first, -1)
        self.assertGreater(pos_second, pos_first)
        self.assertGreater(pos_third, pos_second)

    # ------------------------------------------------------------------
    # _call_sdk: respuesta vacía del SDK
    # ------------------------------------------------------------------

    def test_call_sdk_empty_response_raises(self) -> None:
        """Si el SDK devuelve response.text vacío, levanta ``LLMUnavailable``."""
        fake_client = MagicMock()
        fake_client.models.generate_content.return_value = MagicMock(text="")
        with patch.object(GeminiClient, "_get_client", return_value=fake_client):
            with self.assertRaises(LLMUnavailable):
                self.client._call_sdk("prompt")
