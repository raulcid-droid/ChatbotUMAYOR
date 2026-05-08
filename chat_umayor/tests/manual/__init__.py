# Paquete vacío a propósito. Los tests de integración dentro de
# ``chat_umayor/tests/manual/`` NO se importan desde
# ``chat_umayor/tests/__init__.py`` para evitar que corran con
# ``--test-enable``. Para ejecutarlos manualmente, usar la tag
# ``chat_umayor_manual`` al invocar Odoo:
#
#     ./odoo-bin --test-enable --stop-after-init \
#         -i chat_umayor --test-tags=chat_umayor_manual
