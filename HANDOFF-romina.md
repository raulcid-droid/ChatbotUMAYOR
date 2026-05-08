# HANDOFF — Frontend (Romina)

> Estado: **2026-05-07**, tras PLAN 09 (backend code-complete).
> Este archivo lista lo que falta del lado UI/config para cerrar la
> demo end-to-end. Yo (Jonathan, backend) no toco nada aquí; Romina
> ejecuta.

---

## Contexto rápido

- Backend tiene **5 de 5 endpoints reales** (`/session/new`,
  `/message`, `/submit_data`, `/sign`, `/state`). Ver `docs/api.md v0.5`.
- Modelo `chat_umayor.contract` creado con snapshot denormalizado
  del partner (`partner_name`, `partner_vat`, `partner_email`,
  `partner_phone` inmutables tras el create).
- Callback de Odoo Sign implementado: cuando el usuario firma,
  contract pasa a `signed` y session a `closed` automáticamente. El
  front se entera haciendo polling a `/state`.
- ACL del contrato ya está para `base.group_user` (no hay que crear
  permisos, solo vistas).

---

## F5 — Botón "Firmar" en el widget (pantalla de review)

Cuando la sesión entra en `review` (tras un `/submit_data` OK), el
front ya muestra el resumen del contrato. Añadir botón "Firmar" que:

1. Llama `POST /chat_umayor/session/<id>/sign` con body `{}`.
2. **Éxito** (`ok: true`): abre `data.sign_url` en nueva pestaña:
   ```js
   window.open(data.sign_url, '_blank', 'noopener,noreferrer');
   ```
   Luego arranca el polling (F6). El `sign_url` viene como **ruta
   relativa** (ej: `/sign/document/12345/abc123`); el front la usa
   tal cual sobre el mismo origen Odoo.
3. **Error**, mapear por `error.code`:
   | `code`                  | UX sugerida                                           |
   |-------------------------|-------------------------------------------------------|
   | `SIGN_UNAVAILABLE`      | Banner: "La firma no está disponible. Contacta al administrador." |
   | `INVALID_STATE`         | Mostrar `error.message` tal cual (ya viene en español). |
   | `MISSING_CONTRACT_DATA` | "Faltan datos. Vuelve al formulario." + permitir volver a la pantalla anterior. |
   | `SESSION_NOT_FOUND`     | Recargar la página (la sesión expiró).                |
   | `SESSION_CLOSED`        | "La sesión ya terminó." + recargar.                    |
   | `INTERNAL_ERROR`        | "Ocurrió un problema interno. Intenta más tarde."     |

---

## F6 — Polling de estado tras firmar

Tras abrir `sign_url`, el front no sabe cuándo el usuario completó
la firma (la página de Odoo Sign vive en otra pestaña). Polling a
`POST /chat_umayor/session/<id>/state` cada **3–5 segundos** mientras:

- `document.visibilityState === 'visible'` (no pollear si la pestaña
  del chat está en background — ahorra tráfico).
- Y no hayamos alcanzado el límite temporal (5 min).

**Parseo de la respuesta** (shape completo en `docs/api.md §4.5`):

```js
const { state, contract } = result.data;

if (state === 'closed' || contract?.state === 'signed') {
    stopPolling();
    showSuccessScreen(contract.reference);   // ej: "CH-000017"
    return;
}
if (state === 'signing') {
    continuePolling();
    return;
}
```

**Timeout (5 min sin éxito)**: mostrar fallback "¿Ya firmaste?
Refresca la página." con botón de reload manual. No bloquea al
usuario si firmó correctamente pero el polling se acabó.

**Importante**: `/state` NO devuelve `SESSION_CLOSED` aunque la
sesión esté cerrada (es la única diferencia con `/message`). Eso es
intencional: permite que el polling vea el cierre post-firma.

---

## F7 — Vistas backoffice del contrato

`chat_umayor.contract` no tiene UI interna. Para la demo, que el
profesor pueda abrir "Contratos" desde el menú y ver los firmados,
añadir en `views/` del módulo (archivo nuevo, XML):

1. `ir.actions.act_window` sobre `chat_umayor.contract` (name:
   "Contratos Chat UMayor").
2. **Tree view** con columnas:
   - `reference` (ej: `CH-000017`)
   - `partner_name` (snapshot, no lookup)
   - `partner_vat`
   - `product_code`
   - `state` (con decorator de color: success=signed, warning=signing,
     muted=cancelled, info=draft)
   - `signed_at`
   - `create_date`
3. **Form view** con:
   - Todos los campos (los `readonly=True` del modelo ya saldrán
     grises automáticamente).
   - `partner_id` como link al partner real.
   - `sign_request_id` como link al `sign.request` (botón "Ver firma").
   - `product_data_json` y `calculated_json` como Text monospace (son
     JSON; mostrar raw está bien para demo, no hace falta parser).
4. **Menuitem** bajo un menú propio "Chat UMayor" (si aún no existe)
   o bajo Website/Administración. Ubicación a tu criterio.

El ACL ya la dejé creada yo (fila `access_chat_umayor_contract_user`
en `security/ir.model.access.csv`). No hace falta tocar seguridad.

---

## F8 — Campo `sign_template_id` en Ajustes (opcional)

El backend ya tiene el campo `chat_umayor_sign_template_id` en
`res.config.settings` (`models/res_config_settings.py`), ligado a
`ir.config_parameter` `chat_umayor.sign_template_id`. Es un
`Many2one` a `sign.template`.

Para que el admin lo vea en **Ajustes → Chat UMayor** (o donde
prefieras), añadir el campo a la vista de config settings del módulo
(si ya existe una vista de config, agregar un `<field
name="chat_umayor_sign_template_id"/>`; si no, crearla — mismo
archivo XML que F7 sirve).

**Alternativa (sin UI)**: setear el parámetro por shell. Es lo que
haremos pre-demo si la vista no está lista:
```python
env["ir.config_parameter"].sudo().set_param(
    "chat_umayor.sign_template_id", "5"  # id de la plantilla
)
```

---

## F9 — Setup one-shot de `sign.template` (pre-demo)

**No es código** — es configuración manual en el tenant. Alguien
(Jonathan, Romina o yo) lo hace **una sola vez** antes de la
defensa del proyecto:

1. Entrar al backoffice Odoo → módulo **Sign** → menú "Plantillas"
   (o "Templates").
2. Crear una plantilla nueva:
   - Subir un PDF dummy de contrato bancario (con logo "Banco
     UMayor", 1 página basta — se puede generar con Word o Canva).
   - Dibujar **1 bloque de firma** arrastrando el widget sobre el
     PDF, asociado al rol "firmante" (único firmante).
   - Guardar.
3. Anotar el **id numérico** de la plantilla (aparece en la URL del
   backoffice cuando entras al form de la plantilla, ej:
   `/odoo/sign-templates/7` → id = 7).
4. Setear `ir.config_parameter`:
   - Vía UI: Ajustes → Chat UMayor → "Plantilla de firma" (si F8 hecho).
   - Vía shell: `env["ir.config_parameter"].sudo().set_param("chat_umayor.sign_template_id", "7")`.

**Validación**: probar el flujo end-to-end con el test manual que
dejé en `chat_umayor/tests/manual/test_sign_integration.py`:

```bash
./odoo-bin --addons-path=addons,. -d chatbot_test \
    --test-enable --stop-after-init \
    -i chat_umayor --test-tags=chat_umayor_manual
```

Si pasa en verde, la plantilla está bien configurada y el flujo
real funciona. Si `skipTest`, es porque el `ir.config_parameter` no
está seteado; se vuelve al paso 4 de F9.

---

## Contrato backend ↔ frontend: referencia rápida

Resumen para que no tengas que volver a `docs/api.md`:

| Endpoint                                  | Método | Usado para                                |
|-------------------------------------------|--------|-------------------------------------------|
| `/chat_umayor/session/new`                | POST   | Crear sesión + devolver greeting inicial. |
| `/chat_umayor/session/<id>/message`       | POST   | Turno de chat (request con `content`).    |
| `/chat_umayor/session/<id>/submit_data`   | POST   | Enviar formulario; transiciona a `review`.|
| `/chat_umayor/session/<id>/sign`          | POST   | Lanzar firma; devuelve `sign_url`.        |
| `/chat_umayor/session/<id>/state`         | POST   | Polling de estado (ver F6).               |

Todos `type='jsonrpc'`, `auth='public'`. Shape interno
`{ok, data|error}`. Detalle completo en `docs/api.md v0.5`.

---

## Handoffs previos (aún pendientes)

- **F1, F2, F3, F4**: pendientes de sesiones anteriores (ver
  `NOTES.md` del 2026-05-06). Limpiar `chatbot.js`, lazy session,
  housekeeping de assets, merge `dev_jona ↔ dev_romina`.

---

*Última actualización: 2026-05-07, PLAN 09 cerrado en commit
`[pending]`. Si algo cambia en backend de aquí en adelante, este
archivo se actualiza en el mismo commit que lo rompe.*
