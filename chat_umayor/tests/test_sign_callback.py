"""Tests del callback de firma (override de ``sign.request._sign``).

No creamos registros ``sign.request`` reales (su ``create`` tiene
constraints NOT NULL sobre ``template_id`` que requerirían montar un
``sign.template`` con attachment PDF — innecesario para lo que
queremos validar).

Estrategia de mocks:
    - Contrato real en BD con ``sign_request_id = False`` (el campo
      es M2o con ``ondelete='set null'``, NULL es legítimo).
    - ``sign.request`` simulado con ``MagicMock`` que expone los
      atributos mínimos que usa el método: ``ids`` y ``env``.
    - Invocación **unbound** del método desde la clase (pasando el
      mock como ``self``).
    - ``search`` de ``chat_umayor.contract`` parcheado a nivel de
      clase para que devuelva el contrato que nos interesa.

La integración end-to-end con Sign real no tiene cobertura
automatizada dedicada: los mocks aquí y en ``test_sign_endpoint.py``
son suficientes. La validación manual se hace desde el widget en
staging contra una ``sign.template`` real (ver
``HANDOFF-romina.md §F9``).
"""

from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.chat_umayor.models.sign_request import SignRequest


_SIGN_LOGGER = "odoo.addons.chat_umayor.models.sign_request"


@tagged("chat_umayor", "post_install", "-at_install")
class TestSignCallback(TransactionCase):
    """Propagación de la firma al ``chat_umayor.contract`` vinculado."""

    FAKE_SIGN_REQUEST_ID = 99999

    def _make_signing_context(self):
        """Crea sesión+contrato en ``signing`` sin ``sign.request`` real.

        El contrato queda con ``sign_request_id = False``; el
        ``search`` mockeado en cada test lo devolverá igualmente.
        """
        session = self.env["chatbot.session"]._create_with_greeting()
        for target in (
            "discovery",
            "product_info",
            "data_collection",
            "review",
            "signing",
        ):
            session._do_transition(target)
        partner = self.env["res.partner"].create(
            {"name": "Juan Pérez", "vat": "12345678-5"}
        )
        contract = self.env["chat_umayor.contract"].create(
            {
                "session_id": session.id,
                "partner_id": partner.id,
                "partner_name": partner.name,
                "partner_vat": partner.vat,
                "product_code": "soap",
                "state": "signing",
                # sign_request_id intencionalmente NULL.
            }
        )
        return session, contract

    def _fake_sign_request(self, ids=None):
        """Construye un MagicMock que se hace pasar por sign.request.

        Solo necesita ``ids``, ``env`` y comportarse como truthy para
        pasar el guard ``if not self: return`` del método.
        """
        fake = MagicMock()
        fake.ids = ids if ids is not None else [self.FAKE_SIGN_REQUEST_ID]
        fake.env = self.env
        # MagicMock por defecto es truthy; nos sirve.
        return fake

    def _invoke_callback(self, fake_sign_request, contracts_to_return):
        """Llama ``_notify_chat_umayor_contracts`` como unbound.

        Parchea el ``search`` de ``chat_umayor.contract`` para que
        devuelva el recordset pasado, sin importar los criterios.
        """
        with patch.object(
            type(self.env["chat_umayor.contract"]),
            "search",
            return_value=contracts_to_return,
        ):
            SignRequest._notify_chat_umayor_contracts(fake_sign_request)

    # -----------------------------------------------------------------
    # Happy path: callback mueve el contrato a ``signed`` y cierra sesión
    # -----------------------------------------------------------------

    def test_sign_callback_transitions_contract_to_signed(self) -> None:
        """``_notify_chat_umayor_contracts`` marca el contrato signed."""
        session, contract = self._make_signing_context()
        fake = self._fake_sign_request()

        self._invoke_callback(fake, contract)

        contract.invalidate_recordset()
        self.assertEqual(contract.state, "signed")
        self.assertTrue(contract.signed_at)

    def test_sign_callback_closes_session(self) -> None:
        """El callback también transiciona la sesión a ``closed``."""
        session, contract = self._make_signing_context()
        fake = self._fake_sign_request()

        self._invoke_callback(fake, contract)

        session.invalidate_recordset()
        self.assertEqual(session.state, "closed")

    # -----------------------------------------------------------------
    # Recordset vacío: no debe romper
    # -----------------------------------------------------------------

    @mute_logger(_SIGN_LOGGER)
    def test_sign_callback_ignores_non_chatbot_requests(self) -> None:
        """Un sign.request sin contrato asociado no rompe el callback.

        Cubre dos casos en uno:
            1. ``ids`` vacío → ``if not self: return`` sin tocar BD.
            2. ``ids`` con valores pero search devuelve vacío → no
               hay contratos que mover, callback termina silencioso.
        """
        empty_fake = self._fake_sign_request(ids=[])
        # No debe levantar excepción.
        SignRequest._notify_chat_umayor_contracts(empty_fake)

        # Caso 2: ids no vacíos pero ningún contrato en BD.
        no_match_fake = self._fake_sign_request(ids=[42, 43])
        empty_contracts = self.env["chat_umayor.contract"]
        self._invoke_callback(no_match_fake, empty_contracts)
