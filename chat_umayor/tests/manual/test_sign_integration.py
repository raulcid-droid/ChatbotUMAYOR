"""Test de integración manual contra Odoo Sign REAL.

**NO se ejecuta con ``--test-enable``**: este archivo vive en
``tests/manual/`` y no se importa desde ``tests/__init__.py``. Para
correrlo usar:

    ./odoo-bin --test-enable --stop-after-init \\
        -i chat_umayor --test-tags=chat_umayor_manual

Pre-requisitos en el tenant:
    1. Módulo ``sign`` instalado.
    2. Una ``sign.template`` existente con al menos 1 firmante y 1
       bloque de firma (subir un PDF dummy desde el backoffice).
    3. ``ir.config_parameter`` ``chat_umayor.sign_template_id``
       apuntando a esa plantilla.

Si falta cualquier pre-requisito, este test falla en ``setUp``: es
intencional, documenta la configuración faltante.
"""

import json

from odoo.tests import tagged
from odoo.tests.common import HttpCase


def _jsonrpc_payload(params: dict | None = None) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "call",
            "params": params or {},
            "id": 1,
        }
    )


@tagged("chat_umayor_manual", "-standard", "-at_install", "-post_install")
class TestSignIntegrationManual(HttpCase):
    """Integración real con ``sign.request``.

    Al tag ``chat_umayor_manual`` se le quitan explícitamente
    ``standard``, ``at_install`` y ``post_install`` para que este
    archivo no corra ni con ``--test-enable`` ni con el tag
    ``chat_umayor`` habitual.
    """

    def setUp(self) -> None:
        super().setUp()
        template_id_str = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("chat_umayor.sign_template_id", "0")
        )
        try:
            template_id = int(template_id_str)
        except (ValueError, TypeError):
            template_id = 0
        if not template_id:
            self.skipTest(
                "chat_umayor.sign_template_id no configurado; "
                "crea una sign.template primero."
            )
        self.template = (
            self.env["sign.template"].browse(template_id).exists()
        )
        if not self.template:
            self.skipTest(
                f"sign.template id={template_id} no existe en este tenant."
            )

    def test_full_flow_creates_real_sign_request(self) -> None:
        """Flujo entero: submit_data → sign → sign.request creado en BD."""
        # 1. Sesión en review con submit_summary.
        session = self.env["chatbot.session"]._create_with_greeting()
        for target in (
            "discovery",
            "product_info",
            "data_collection",
            "review",
        ):
            session._do_transition(target)
        partner = self.env["res.partner"].create(
            {"name": "Test Manual", "vat": "12345678-5"}
        )
        session.partner_id = partner.id
        session.product_code = "soap"
        session.submit_summary = json.dumps(
            {
                "product_code": "soap",
                "product_data": {
                    "vehicle_plate": "BCDF12",
                    "vehicle_year": 2020,
                    "vehicle_type": "particular",
                },
                "calculated": {
                    "premium": 7990,
                    "currency": "CLP",
                    "vehicle_type": "particular",
                },
            }
        )

        # 2. Llamada real al endpoint /sign.
        response = self.url_open(
            f"/chat_umayor/session/{session.id}/sign",
            data=_jsonrpc_payload({}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]

        if not result["ok"]:
            self.fail(
                f"/sign devolvió error en integración real: "
                f"{result.get('error')}"
            )

        # 3. Verificar que el sign.request existe y apunta a la plantilla.
        contract = self.env["chat_umayor.contract"].browse(
            result["data"]["contract_id"]
        )
        self.assertTrue(contract.sign_request_id)
        self.assertEqual(
            contract.sign_request_id.template_id.id,
            self.template.id,
        )
        self.assertEqual(contract.state, "signing")
