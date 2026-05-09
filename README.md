# Chat UMayor

> Trabajo universitario — Taller de Integración, UMayor.
> Chatbot bancario ficticio integrado en Odoo 19, asistido por Google
> Gemini y con firma digital vía Odoo Sign.

[![License: LGPL-3](https://img.shields.io/badge/license-LGPL--3-blue.svg)](https://www.gnu.org/licenses/lgpl-3.0)

---

## 1. Qué es

Un módulo de **Odoo 19** que agrega un asistente virtual al sitio web
público del banco ficticio **Banco UMayor**. El cliente abre un widget
de chat, describe qué quiere contratar, y el bot lo guía hasta
completar la venta y firmar el contrato digitalmente.

Productos disponibles (valores y tarifas **ficticios**, no reales):

- **SOAP** — Seguro Obligatorio de Accidentes Personales (Chile).
  Tarifa plana por tipo de vehículo (particular, moto, comercial, taxi).
- **Depósito a Plazo** — ahorro con monto y plazo (30/60/90/180/365
  días), interés simple con tasa fija por tramo.

El bot **solo genera texto natural e interpreta intención** con
Gemini. Todos los cálculos (primas, intereses, validación de RUT,
patente, etc.) y la persistencia viven en modelos Odoo — nunca en el
prompt del LLM.

---

## 2. Stack

| Componente        | Versión / Detalle                                       |
|-------------------|---------------------------------------------------------|
| Python            | 3.12 (mínimo 3.10)                                      |
| Odoo              | 19 Community                                            |
| PostgreSQL        | 15+                                                     |
| SDK Gemini        | `google-genai` (paquete nuevo, **no** `google-generativeai`) |
| Modelo Gemini     | `gemini-2.5-flash-lite` (familia Flash, default)        |
| Firmas digitales  | Odoo Sign (módulo nativo `sign`)                        |
| Control versiones | Git                                                     |

Módulos Odoo requeridos (`depends`): `website`, `base`, `mail`, `sign`.

---

## 3. Instalación

### 3.1 Clonar el repo

```bash
git clone <url-del-repo> chat-umayor
cd chat-umayor
```

El módulo Odoo vive en `chat_umayor/` (en la raíz del repo, no en
`custom_addons/`).

### 3.2 Dependencia Python

```bash
pip install google-genai
```

El módulo se instala igual sin la librería (import diferido en
`services/gemini_client.py`); solo falla al invocar al LLM.

### 3.3 Instalar en Odoo

Añadir la raíz del repo al `addons-path` de Odoo:

```bash
./odoo-bin --addons-path=addons,/ruta/a/chat-umayor \
    -d chatbot_db \
    -i chat_umayor \
    --stop-after-init
```

O, en `odoo.conf`:

```ini
[options]
addons_path = /ruta/a/odoo/addons,/ruta/a/chat-umayor
```

Para **actualizar** tras cambios (por ejemplo, tras un `git pull`):

```bash
./odoo-bin --addons-path=addons,/ruta/a/chat-umayor \
    -d chatbot_db -u chat_umayor --stop-after-init
```

---

## 4. Configuración post-instalación

### 4.1 Gemini API key (obligatorio para que el chat responda)

El módulo lee la clave desde `ir.config_parameter`
`chat_umayor.gemini_api_key`, con fallback a la variable de entorno
`GEMINI_API_KEY`. Para setearla:

**Opción A — UI**: Ajustes → Chat UMayor → "Gemini API Key" (requiere
la vista de settings; ver `HANDOFF-romina.md §F8`).

**Opción B — shell de Odoo**:
```bash
./odoo-bin shell -d chatbot_db --addons-path=addons,/ruta/a/chat-umayor
```
```python
env["ir.config_parameter"].sudo().set_param(
    "chat_umayor.gemini_api_key", "AIza...")
```

**Opción C — variable de entorno** (más limpio para desarrollo):
```bash
export GEMINI_API_KEY=AIza...
./odoo-bin ...
```

Ver `chat_umayor/models/res_config_settings.py` para el resto de
parámetros configurables: modelo (`chat_umayor.gemini_model`), system
prompt (`chat_umayor.system_prompt`, se carga por defecto desde
`data/system_prompt.xml`) y timeout
(`chat_umayor.gemini_timeout_seconds`, default 15 s).

### 4.2 Plantilla de Odoo Sign (obligatorio para firmar)

El endpoint `/sign` necesita una `sign.template` configurada. Sin
ella, la firma devuelve `SIGN_UNAVAILABLE`.

Setup manual (una sola vez):

1. Backoffice Odoo → módulo **Sign** → Plantillas.
2. Crear plantilla nueva:
   - Subir un PDF dummy de contrato (1 página basta).
   - Dibujar **1 bloque de firma** asociado a un único firmante.
   - Guardar y anotar el **id numérico** (visible en la URL, ej.
     `/odoo/sign-templates/7` → id = 7).
3. Setear el parámetro:
   ```python
   env["ir.config_parameter"].sudo().set_param(
       "chat_umayor.sign_template_id", "7")
   ```

Detalle paso a paso en `HANDOFF-romina.md §F9`.

---

## 5. Arquitectura

### 5.1 Máquina de estados de la sesión (`chatbot.session`)

```
greeting ─► discovery ─► product_info ─► data_collection
                ▲              │
                │              ▼
                └───── (cambio de producto)
                               │
                               ▼
                            review ─► signing ─► closed
```

Cada transición pasa por `_transition_to_<estado>()` con validación
contra `_ALLOWED_TRANSITIONS` (ver `models/chatbot_session.py`).
Intentar una transición inválida levanta `UserError` en español.

### 5.2 Modelos

| Modelo                      | Responsabilidad                                    |
|-----------------------------|----------------------------------------------------|
| `chatbot.session`           | FSM de la conversación + partner + submit_summary. |
| `chatbot.message`           | Historial. Sanea PII (RUT/email/teléfono/tarjeta) antes de enviar a Gemini. |
| `chat_umayor.contract`      | Contrato firmable. Snapshot inmutable del partner. |
| `chat_umayor.product.soap`  | Validación + cálculo de prima SOAP.                |
| `chat_umayor.product.deposit` | Validación + cálculo de interés de depósito.     |
| `res.config.settings`       | Parámetros del módulo (API key, plantilla, etc.).  |
| `sign.request` (override)   | Callback cuando se completa la firma → `contract.signed`. |

### 5.3 Endpoints HTTP

Todos los endpoints son JSON-RPC 2.0 nativos de Odoo
(`type='jsonrpc'`, `auth='public'`). Shape interno:
`{ok, data|error}`.

| Endpoint                                  | Uso                                 |
|-------------------------------------------|-------------------------------------|
| `POST /chat_umayor/ping`                  | Smoke check.                        |
| `POST /chat_umayor/session/new`           | Crear sesión + greeting inicial.    |
| `POST /chat_umayor/session/<id>/message`  | Turno de chat.                      |
| `POST /chat_umayor/session/<id>/submit_data` | Envío del formulario.            |
| `POST /chat_umayor/session/<id>/sign`     | Lanzar firma; devuelve `sign_url`.  |
| `POST /chat_umayor/session/<id>/state`    | Polling de estado (post-firma).     |

Contrato completo, payloads, shapes de respuesta y catálogo de
códigos de error: **`docs/api.md v0.5`**.

---

## 6. Correr los tests

Los tests del módulo están en `chat_umayor/tests/`. Todos usan mocks;
no tocan la API real de Gemini ni generan `sign.request` reales.

```bash
./odoo-bin --addons-path=addons,/ruta/a/chat-umayor \
    -d chatbot_test \
    --test-enable --stop-after-init \
    -i chat_umayor \
    --test-tags=/chat_umayor
```

**Esperado**: 114 tests verdes, 0 failed, 0 errors, 0 warnings.

Desglose:

- `test_smoke.py` (1) — ping HTTP.
- `test_session_fsm.py` (7) — FSM y transiciones.
- `test_message_sanitization.py` (13) — PII saneada para el LLM.
- `test_gemini_client.py` (16) — wrapper Gemini con mocks (retries,
  timeout, auth, canned).
- `test_session_intents.py` (22) — clasificación de intenciones.
- `test_rut_validation.py` (3), `test_partner_idempotency.py` (2) —
  RUT + partners.
- `test_product_soap.py` (4), `test_product_deposit.py` (4) —
  validación y cálculo.
- `test_controllers.py` (~25) — endpoints HTTP.
- `test_contract.py` (5), `test_sign_endpoint.py` (5),
  `test_state_endpoint.py` (2), `test_sign_callback.py` (3) — firma.

**Lint**:
```bash
ruff check chat_umayor/models chat_umayor/services chat_umayor/controllers
```

---

## 7. Demo end-to-end

Una vez instalado y configurado (§4), el flujo que seguirá el
evaluador:

1. Abrir la home del sitio web de Odoo (`/`).
2. Click en el FAB del chat (esquina inferior derecha).
3. El bot saluda:
   > *"Hola, soy el asistente virtual de Banco UMayor. Puedo ayudarte
   > a contratar un SOAP o un Depósito a Plazo. ¿Qué te interesa?"*
4. El usuario describe qué quiere (ej. *"quiero un SOAP"*).
5. El bot pregunta por los datos del vehículo (patente, año, tipo).
6. Usuario rellena el formulario → aparece la pantalla de **revisión**
   con el resumen y la prima calculada.
7. Click en "Firmar" → se abre Odoo Sign en una nueva pestaña con el
   PDF de la plantilla.
8. Usuario firma → Odoo Sign dispara el callback → contrato pasa a
   `signed`, sesión a `closed`. El widget del chat detecta el cambio
   vía polling y muestra el número de referencia (ej. `CH-000017`).
9. En el backoffice, el contrato queda registrado en
   **Contratos → Chat UMayor** (vistas provistas por el frontend).

---

## 8. División del trabajo

Proyecto hecho en equipo de 2:

| Rol       | Persona  | Alcance                                                        |
|-----------|----------|----------------------------------------------------------------|
| Backend   | Jonathan | Modelos, controllers, wrapper Gemini, integración Sign, tests. |
| Frontend  | Romina   | Widget OWL, formulario, polling, vistas backoffice, assets.    |

Lo pendiente del lado frontend para cerrar la demo está detallado en
`HANDOFF-romina.md` (F5–F9). Ver también `AGENTS.md` para las
convenciones del proyecto y `NOTES.md` para el historial de
decisiones por sesión.

---

## 9. Limitaciones conocidas

- **Datos 100% ficticios**: tarifas SOAP y tasas de depósito
  inventadas con fines académicos. No usar para cotizaciones reales.
- **Sin CI/CD**: los tests se corren manualmente o en Odoo.sh staging
  por push a la rama.
- **Intent detection por keywords**: el clasificador
  (`_classify_intent`) usa una tabla de palabras clave normalizadas
  (sin acentos). Frágil ante sinónimos; se reemplazará por respuesta
  estructurada de Gemini (JSON mode) en una iteración posterior
  (PLAN 08.5, fuera del alcance actual).
- **Plantilla Sign manual**: la `sign.template` se configura una vez
  a mano en el backoffice (§4.2). El módulo no la genera.
- **País hardcodeado a Chile**: formato de RUT, patente chilena,
  moneda CLP. Extender a otros países requeriría un nuevo PLAN.
- **Sin timeout de sesiones**: una sesión en `signing` abandonada
  queda así. No afecta a la demo; limpieza manual si molesta.
- **PII sanitizada con regex**: cubre RUT, email, teléfono chileno y
  tarjeta. **No** cubre nombres propios ni direcciones (requiere NER).

---

## 10. Estructura del repo

```
chat-umayor/
├── AGENTS.md              # convenciones del módulo (rol backend)
├── NOTES.md               # historial de sesiones y decisiones
├── PLAN.md                # plan vigente (atómico)
├── HANDOFF-romina.md      # pendientes de frontend
├── README.md              # este archivo
├── docs/
│   └── api.md             # contrato backend ↔ frontend (v0.5)
└── chat_umayor/           # el módulo Odoo
    ├── __manifest__.py
    ├── controllers/
    ├── models/
    ├── services/          # wrapper Gemini
    ├── data/              # productos + system_prompt
    ├── security/
    ├── views/             # frontend (Romina)
    ├── static/            # frontend (Romina)
    ├── i18n/es.po         # traducciones español
    └── tests/
```

---

## 11. Licencia

LGPL-3. Ver `chat_umayor/__manifest__.py`.

---

*Proyecto académico sin garantías. Contacto: equipo UMayor 2026.*
