# API `chat_umayor` — contrato backend ↔ frontend

- **Versión**: `v0.3` (draft · propuesta unilateral del backend).
- **Estado**: implementados 2 de 4 endpoints (`/session/new`, `/message`).
  `/submit_data` y `/sign` son **stubs** que devuelven `INVALID_STATE`.
- **Fecha**: 2026-05-07.
- **Fuente de verdad**: este documento. Cualquier cambio en endpoints se
  refleja aquí **en el mismo commit** que toca `controllers/main.py`
  (regla §10.6 de `AGENTS.md`).

> Mientras este doc esté en `v0`, los payloads pueden cambiar sin aviso.
> A partir de `v1` (tras PLAN 07) los cambios rompedores requieren bump
> de versión explícito.

---

## 1. Convenciones

### Transporte
- **JSON-RPC 2.0 nativo de Odoo** sobre `http.Controller` con `type='jsonrpc'`.
  Es el patrón idíomatico en Odoo 19 y el widget OWL de UI puede usar el
  cliente `rpc` de Odoo sin código extra.
- Todos los endpoints aceptan y devuelven **JSON UTF-8**.
- Método: **`POST`** siempre (obligatorio para `type='jsonrpc'`).
- Base URL: raíz del website Odoo. Prefijo fijo **`/chat_umayor/`**
  (alineado con §6 de `AGENTS.md`).

### Envoltorio JSON-RPC

La UI **no** envía directamente los payloads documentados abajo: los
envuelve en la estructura JSON-RPC que Odoo espera.

**Request** (lo que sale del cliente):
```json
{
  "jsonrpc": "2.0",
  "method": "call",
  "params": { ... payload documentado en §4 ... },
  "id": 1
}
```

**Response exitosa** (lo que recibe el cliente):
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": { ... shape `{ok, data|error}` documentado abajo ... }
}
```

En el resto del documento, cuando digo "request" o "response" me refiero
al contenido de `params` y de `result` respectivamente. La UI usa
`fetch` con `Content-Type: application/json` o, preferiblemente, el
helper `rpc` de `@web/core/network/rpc`.

### Autenticación
- `auth='public'` en los 4 endpoints (el chatbot atiende visitantes anónimos).
- La identidad de la conversación se lleva por **`session_id` en la URL**,
  no por cookie. Es el id de un registro `chatbot.session` en BD.
- CSRF: gestionado por Odoo automáticamente en `type='jsonrpc'` (no hace
  falta `csrf=False` ni tokens manuales). Esto resuelve el TBD §5.1 de `v0`.

### Formato de `result` (shape de negocio)
Dentro del `result` del JSON-RPC usamos siempre este shape:

**Éxito**:
```json
{
  "ok": true,
  "data": { ... }
}
```

**Error de negocio** (la llamada JSON-RPC fue OK pero la operación falló):
```json
{
  "ok": false,
  "error": {
    "code": "SESSION_NOT_FOUND",
    "message": "La sesión indicada no existe o expiró."
  }
}
```

El mensaje de `error.message` está en **español** y es apto para mostrar
al usuario final. Nunca contiene tracebacks, nombres de tabla, ni
detalles de infraestructura (regla §7 de `AGENTS.md`).

### Errores de protocolo vs. errores de negocio
- **Errores de negocio** (validación, estado inválido, LLM caído, etc.)
  → HTTP 200, JSON-RPC `result` con `{"ok": false, "error": {...}}`.
- **Errores de protocolo** (excepción Python no controlada) → JSON-RPC
  devuelve `{"error": {...}}` en lugar de `result`. La UI debe tratarlo
  como `INTERNAL_ERROR` y mostrar mensaje genérico al usuario.
- **JSON malformado** → HTTP 400 gestionado por Odoo.

### Timestamps
ISO-8601 con offset, ej. `"2026-05-02T14:23:11+00:00"`.

---

## 2. Máquina de estados (espejo informativo)

El campo `state` que devuelven varios endpoints proviene de
`chatbot.session.state`, definido en §6 de `AGENTS.md`:

```
greeting → discovery → product_info → data_collection → review → signing → closed
                 ↑__________________________________________|
                 (cambio de producto)
```

El frontend **no** decide transiciones: solo refleja el estado que le
devuelve el backend.

---

## 3. Catálogo de errores

| `code`                  | Significado                                              | Cuándo |
|-------------------------|----------------------------------------------------------|--------|
| `SESSION_NOT_FOUND`     | `session_id` inexistente o borrada.                      | Cualquiera con `<id>` en la URL. |
| `SESSION_CLOSED`        | La sesión está en `state='closed'`.                      | `/message`, `/submit_data`, `/sign`. |
| `INVALID_STATE`         | Operación no permitida en el estado actual.              | Ej: `/sign` antes de `review`. |
| `VALIDATION_ERROR`      | Datos del formulario inválidos (con detalle por campo).  | `/submit_data`. |
| `LLM_UNAVAILABLE`       | Gemini no respondió tras reintentos (§7 AGENTS).         | `/message`. |
| `MISSING_CONTRACT_DATA` | Falta información para generar el contrato.              | `/sign`. |
| `SIGN_UNAVAILABLE`      | Odoo Sign no disponible o plantilla no configurada.      | `/sign`. |
| `INTERNAL_ERROR`        | Excepción no clasificada (logeada en servidor).          | Cualquiera. |

---

## 4. Endpoints

### 4.1 `POST /chat_umayor/session/new`

Crea una nueva sesión de chat.

**Request**: body vacío (`{}`) o sin body.

**Response 200 OK**:
```json
{
  "ok": true,
  "data": {
    "session_id": 42,
    "state": "greeting",
    "greeting_message": "Hola, soy el asistente virtual de Banco UMayor. Puedo ayudarte a contratar un SOAP o un Depósito a Plazo. ¿Qué te interesa?",
    "created_at": "2026-05-02T14:23:11+00:00"
  }
}
```

**Errores posibles**: `INTERNAL_ERROR`.

**Notas backend**:
- Crea registro en `chatbot.session` con `state='greeting'`.
- `greeting_message` se registra también como primer `chatbot.message` (rol `assistant`).

---

### 4.2 `POST /chat_umayor/session/<int:session_id>/message`

Envía un mensaje del usuario y recibe la respuesta del bot.

**Request**:
```json
{
  "content": "Quiero contratar un seguro"
}
```

**Campos**:
| Campo     | Tipo   | Requerido | Descripción                              |
|-----------|--------|-----------|------------------------------------------|
| `content` | string | sí        | Texto del usuario. 1–2000 caracteres.    |

**Response 200 OK**:
```json
{
  "ok": true,
  "data": {
    "reply": "Perfecto, te puedo ofrecer SOAP o Depósito a Plazo. ¿Cuál te interesa?",
    "state": "discovery",
    "product_code": null,
    "suggestions": []
  }
}
```

**Response 200 OK (tras elegir SOAP en product_info y confirmar)**:
```json
{
  "ok": true,
  "data": {
    "reply": "Genial, ahora te pido tus datos en un formulario.",
    "state": "data_collection",
    "product_code": "soap",
    "suggestions": []
  }
}
```

**Campos de `data`**:
| Campo          | Tipo                | Descripción                                                                                 |
|----------------|---------------------|---------------------------------------------------------------------------------------------|
| `reply`        | string              | Respuesta generada por Gemini (o fallback canned ante error).                               |
| `state`        | string              | Nuevo estado del FSM tras procesar el mensaje.                                              |
| `product_code` | `"soap"\|"deposit"\|null` | **Siempre presente.** `null` si no se ha elegido producto; valor fijado al elegir en discovery. |
| `suggestions`  | array[string]       | Chips/respuestas rápidas sugeridas. Vacío en v0.3; se rellena en PLAN 08.                   |

**Errores posibles**: `SESSION_NOT_FOUND`, `SESSION_CLOSED`, `LLM_UNAVAILABLE`, `VALIDATION_ERROR` (si `content` viene vacío o >2000).

**Nota sobre `LLM_UNAVAILABLE`**: cuando Gemini no responde tras reintentos, la respuesta viene con `ok=false` y `error.code="LLM_UNAVAILABLE"`, pero además incluye `error.reply`, `error.state` y `error.product_code` para que la UI pueda mostrar un mensaje canned sin bloquear la conversación.

**Notas backend**:
- Guarda el mensaje del usuario en `chatbot.message`, aplica `_sanitize_for_llm()`, llama a Gemini con últimos N=10 mensajes (§7 AGENTS).
- Ante `LLM_UNAVAILABLE`, `state` no cambia y se persiste un turno `assistant` con el canned para no desbalancear el historial.
- Transiciones de FSM: en v0.3 se deciden server-side por heurística de keywords (`chatbot.session._classify_intent`). En PLAN 08 se migrará a respuesta estructurada de Gemini (JSON mode).

---

### 4.3 `POST /chat_umayor/session/<int:session_id>/submit_data`

> ⚠️ **Stub en v0.3**: devuelve siempre `{"ok": false, "error": {"code": "INVALID_STATE", "message": "Operación aún no disponible en esta versión."}}`. La implementación real llega en **PLAN 08** (cuando existan `res.partner` + productos SOAP/Depósito + cálculos). El contrato del request/response de abajo es el objetivo final, no el comportamiento actual.

Envía el formulario con los datos del cliente y del producto elegido.
Transición típica: `data_collection → review`.

**Request** (ejemplo para SOAP):
```json
{
  "product_code": "soap",
  "partner": {
    "name": "Juan Pérez",
    "document_id": "12.345.678-9",
    "email": "juan@example.com",
    "phone": "+56 9 1234 5678"
  },
  "product_data": {
    "vehicle_plate": "ABCD12",
    "vehicle_year": 2020
  }
}
```

**Request** (ejemplo para Depósito a Plazo):
```json
{
  "product_code": "deposit",
  "partner": { "name": "...", "document_id": "...", "email": "...", "phone": "..." },
  "product_data": {
    "amount": 1500000,
    "term_days": 90
  }
}
```

**Campos comunes**:
| Campo                    | Tipo   | Requerido | Descripción                                              |
|--------------------------|--------|-----------|----------------------------------------------------------|
| `product_code`           | string | sí        | `"soap"` o `"deposit"`.                                  |
| `partner.name`           | string | sí        | Nombre completo.                                         |
| `partner.document_id`    | string | sí        | RUT/DNI ficticio. **TBD**: formato según país (ver §5).  |
| `partner.email`          | string | sí        | Email válido.                                            |
| `partner.phone`          | string | no        | Teléfono.                                                |
| `product_data`           | object | sí        | Campos específicos del producto (ver abajo).             |

**Campos `product_data` para SOAP**: `vehicle_plate` (string), `vehicle_year` (int). **TBD**: confirmar con profesor.

**Campos `product_data` para Depósito**: `amount` (number, > 0), `term_days` (int, > 0).

**Response 200 OK**:
```json
{
  "ok": true,
  "data": {
    "state": "review",
    "summary": {
      "product_name": "SOAP",
      "partner_name": "Juan Pérez",
      "calculated": {
        "premium": 7890,
        "currency": "CLP"
      }
    }
  }
}
```

Para Depósito, `calculated` contiene `{"interest": ..., "total_at_maturity": ..., "currency": "CLP"}`.

**Response 200 con error de validación**:
```json
{
  "ok": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Algunos campos son inválidos.",
    "fields": {
      "partner.email": "Email con formato inválido.",
      "product_data.amount": "Debe ser mayor a 0."
    }
  }
}
```

**Errores posibles**: `SESSION_NOT_FOUND`, `SESSION_CLOSED`, `INVALID_STATE`, `VALIDATION_ERROR`.

**Notas backend**:
- Crea/actualiza `res.partner` (idempotente por `document_id`).
- Calcula prima SOAP o intereses del depósito en el modelo del producto (no en prompt).
- Pasa `state` a `review`.

---

### 4.4 `POST /chat_umayor/session/<int:session_id>/sign`

> ⚠️ **Stub en v0.3**: devuelve siempre `{"ok": false, "error": {"code": "INVALID_STATE", "message": "Operación aún no disponible en esta versión."}}`. La implementación real llega en **PLAN 09** (integración con Odoo Sign). El contrato de abajo es el objetivo final, no el comportamiento actual.

Lanza el flujo de firma con Odoo Sign. Requiere `state='review'` (o `signing` si es reintento).

**Request**: body vacío (`{}`).

**Response 200 OK**:
```json
{
  "ok": true,
  "data": {
    "contract_id": 17,
    "sign_url": "https://.../sign/document/17/abc123token",
    "state": "signing"
  }
}
```

**Errores posibles**: `SESSION_NOT_FOUND`, `SESSION_CLOSED`, `INVALID_STATE`, `MISSING_CONTRACT_DATA`, `SIGN_UNAVAILABLE`.

**Notas backend**:
- Crea `chat_umayor.contract`, crea `sign.request` a partir de plantilla, devuelve URL pública.
- El callback de `sign` (cuando el usuario firma) transiciona a `closed` — **no** pasa por este endpoint. El frontend debe hacer polling a `/message` o escuchar el estado por otro medio. **TBD**: definir si agregamos `GET /chat_umayor/session/<id>/state` para polling de estado post-firma.

---

## 5. TBD / preguntas abiertas

1. ~~**CSRF en JSON públicos**~~ → resuelto en `v0.1`: Odoo lo gestiona en `type='jsonrpc'`.
2. **Formato de `document_id`**: depende de qué país se use para SOAP (AGENTS §1 dice "confirmar con el profesor"). Por ahora aceptamos string libre y validamos en backend.
3. **Polling de estado post-firma**: ¿endpoint dedicado `GET /state` o incluir el estado de firma en la próxima respuesta de `/message`?
4. **Rate limiting**: no contemplado en `v0.1`. Ante abuso del endpoint `/message`, el wrapper de Gemini ya tiene backoff (§7 AGENTS) pero no hay protección por IP.
5. **I18n de `error.message`**: en `v0.1` solo español. Si UI quisiera otros idiomas, agregar `Accept-Language` y `.po`.
6. **Campos de SOAP**: confirmar con profesor qué datos vehiculares son obligatorios.

---

## 6. Changelog

- **v0.3** (2026-05-07): primera versión con endpoints reales
  implementados.
  - `/session/new` y `/session/<id>/message` funcionales (PLAN 07).
  - `/submit_data` y `/sign` marcados como **stubs** que devuelven
    `INVALID_STATE` hasta PLAN 08 y PLAN 09 respectivamente.
  - Response de `/message` incluye `product_code` (siempre presente;
    `null` si no aplica) para que el front no tenga que inferirlo del
    texto. Campo estable tanto en éxito como en `LLM_UNAVAILABLE`.
  - Saludo actualizado a "Banco UMayor" (coherencia con el proyecto).
  - Transiciones del FSM descritas en §4.2: heurística server-side en
    v0.3, migración a Gemini JSON mode prevista en PLAN 08.
- **v0.2** (2026-05-03): rename `type='json'` → `type='jsonrpc'`. Desde
  Odoo 19.0 el primero es un alias deprecado del segundo. Sin cambios
  en payloads ni envoltorio JSON-RPC: solo el nombre del `type` en el
  decorador `@route` del backend.
- **v0.1** (2026-05-02): aclara transporte como JSON-RPC 2.0 nativo de
  Odoo (no REST plano). Documenta envoltorio `params`/`result`. Cierra
  TBD de CSRF.
- **v0** (2026-05-02): primer draft tras PLAN 02. Sin implementación aún.

<!-- v0.3 · 2026-05-07 · PLAN 07: /session/new + /message reales, stubs documentados, product_code estable -->
