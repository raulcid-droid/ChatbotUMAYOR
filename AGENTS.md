# chat_umayor — Proyecto académico Odoo + Gemini (rol: BACKEND)

> Este archivo complementa `~/.pi/agent/AGENTS.md`. No repite reglas globales.

## 1. Contexto del proyecto

Chatbot bancario **ficticio** para trabajo universitario. Guía a un cliente
por la venta de dos productos financieros, recoge sus datos en un formulario
Odoo, y lanza una firma digital para generar un "contrato".

- **Entorno**: ficticio, datos inventados.
- **Entregable**: módulo Odoo 19 instalable + demo funcional en equipo.
- **Módulo**: `chat_umayor` (en la raíz del repo, `chat_umayor/`).

### Productos

1. **SOAP** — Seguro Obligatorio de Accidentes Personales (confirmar país con el profesor).
2. **Depósito a Plazo** — ahorro con monto, plazo (días), tasa de interés.

---

## 2. Mi rol en el equipo: BACKEND

El proyecto lo hace un equipo. **Yo solo hago backend.** Otro compañero hace UI.

### ✅ Lo que SÍ hago

1. **Motor lógico del chatbot** (Python): modelos, ORM, lógica de negocio.
2. **Flujo conversacional transaccional** (máquina de estados en `chatbot.session`).
3. **Integración con Gemini** (`services/gemini_client.py` con `google-genai`).
4. **Sincronización de datos**: persistir en Odoo lo que capture el chatbot (`res.partner`, productos, contratos).
5. **Endpoints/controllers Python** que el frontend consume (JSON-RPC o `http.Controller`).
6. **Cableado con Odoo Sign**: método que inicia la firma, callback que recibe el resultado, guardar en el modelo. *(El botón lo pone el frontend; la tubería es mía.)*
7. **Tests unitarios** de mis modelos y del wrapper Gemini (con mocks).

### ❌ Lo que NO hago (es del compañero de UI)

- Vistas QWeb / páginas del portal web.
- Componentes OWL / JavaScript del widget de chat.
- CSS / estilos.
- Plantillas del Website Builder de Odoo.
- Tests de UI / E2E / usabilidad.

### 🟡 Zonas grises — consultar al equipo antes de tocar

- **Assets XML** (`views/assets.xml`): normalmente frontend, pero si el backend necesita exponer un asset, coordinar.
- **Diseño del contrato PDF**: el QWeb del reporte puede ser del UI, pero los datos los calculo yo.
- **Textos de UI en español**: yo genero los strings base (`_description`, errores), el UI los estiliza.

---

## 3. Stack

| Componente | Versión / detalle |
|---|---|
| Python | **3.12** (mín. 3.10, recomendado 3.12 para Odoo 19) |
| Odoo | **19 Community** |
| PostgreSQL | 15+ |
| SDK Gemini | **`google-genai`** (nuevo). **No uses** `google-generativeai` (legado). |
| Modelo Gemini | Elegir de https://ai.google.dev/gemini-api/docs/models. Familia Flash por coste/latencia. Registrar elección en `PLAN.md`. |
| Firmas | **Odoo Sign** (módulo nativo `sign`). |
| Control versiones | Git (sin CI/CD). |

---

## 4. Comandos

Ajusta el binario según tu instalación (`odoo-bin` / `odoo` / `python odoo-bin`).

```bash
# Dev (auto-reload) — el módulo vive en la raíz del repo, por eso `.` en addons-path
./odoo-bin --addons-path=addons,. -d chatbot_db --dev=all

# Tests del módulo (solo lo mío: modelos, services)
./odoo-bin --addons-path=addons,. -d chatbot_test \
  --test-enable --stop-after-init -i chat_umayor \
  --test-tags=/chat_umayor:TestSession,/chat_umayor:TestGeminiClient

# Linter sobre mi código Python
ruff check chat_umayor/models chat_umayor/services chat_umayor/controllers
```

---

## 5. Estructura — solo mis archivos

```
chat_umayor/                               # raíz del repo (no custom_addons/)
├── __manifest__.py                        # mixto; coordinar cambios con UI
├── __init__.py                            # importa models/, services/, controllers/
├── models/                                # ← MÍO
│   ├── __init__.py
│   ├── chatbot_session.py                 # máquina de estados
│   ├── chatbot_message.py                 # historial
│   ├── chatbot_contract.py                # contrato + vínculo a sign.request
│   └── res_config_settings.py             # API key + ajustes Gemini
├── services/                              # ← MÍO
│   └── gemini_client.py                   # wrapper aislado de google-genai
├── controllers/                           # ← MÍO
│   └── main.py                            # endpoints JSON-RPC que consume el frontend
├── data/                                  # ← MÍO
│   ├── products.xml                       # SOAP + Depósito
│   └── system_prompt.xml                  # prompt sistema
├── security/ir.model.access.csv           # ← MÍO
├── tests/                                 # ← MÍO (unitarios, con mocks)
│   ├── __init__.py
│   ├── test_session_fsm.py
│   ├── test_gemini_client.py
│   └── test_contract.py
│
├── views/                                 # del compañero de UI — NO TOCAR
├── static/                                # del compañero de UI — NO TOCAR
└── i18n/                                  # compartido; yo solo si toco strings Python
```

**Regla de oro**: no edito `views/`, `static/`, ni archivos QWeb/OWL/CSS.

---

## 6. Arquitectura del motor (lo mío)

### Máquina de estados (`chatbot.session.state`)

```
greeting → discovery → product_info → data_collection → review → signing → closed
                  ↑__________________________________________|
                  (cambio de producto)
```

- Cada transición es `_transition_to_<state>()` con validación previa.
- Toda la lógica (calcular prima SOAP, interés depósito, validar RUT/DNI ficticio, generar contrato, lanzar firma) **vive en modelos Odoo**, nunca en el prompt.
- Gemini **solo** genera texto natural e interpreta intención.
- Cálculos, validación, persistencia → ORM.

### Contrato de API con el frontend

Yo expongo (controllers/main.py):
- `POST /chat_umayor/session/new` → crea sesión, devuelve `session_id`.
- `POST /chat_umayor/session/<id>/message` → recibe mensaje usuario, devuelve respuesta del bot + estado actual.
- `POST /chat_umayor/session/<id>/submit_data` → recibe formulario, valida, persiste.
- `POST /chat_umayor/session/<id>/sign` → lanza el flujo de Odoo Sign, devuelve URL de firma.

**Documento este contrato en `docs/api.md`** apenas lo implemente, para que el compañero de UI lo consuma sin adivinar.

---

## 7. Integración con Gemini

### API key
- En `ir.config_parameter` con clave `chat_umayor.gemini_api_key`.
- Fallback a `GEMINI_API_KEY` si el parámetro está vacío.
- **Nunca** en código, XML de datos, commits, logs, errores al cliente.

### System prompt
- En `ir.config_parameter` (`chat_umayor.system_prompt`), editable sin redeploy.
- Versión inicial desde `data/system_prompt.xml`.
- **No** lleva cálculos ni lógica financiera — solo tono, rol, flujo.

### Envío de contexto
- Últimos **N=10** mensajes (configurable).
- Sanear datos sensibles: `_sanitize_for_llm()` reemplaza RUT/nombre/dirección/email por placeholders (`[CLIENTE]`, `[DOCUMENTO]`).
- Registrar texto original en `chatbot.message`; mandar la versión saneada a Gemini.

### Manejo de errores (`services/gemini_client.py`)
- `RateLimitError` → reintento exponencial, máx 3.
- `TimeoutError` → fallback canned ("Disculpa, tuve un problema. ¿Puedes repetir?").
- `AuthError` → log + aviso admin; cliente ve mensaje genérico.
- Cualquier otra → log completo; cliente ve mensaje genérico, **nunca traceback**.

### Tests
- Unitarios **siempre con mock** de `google-genai`. Cero llamadas reales en tests.
- Test de humo manual opcional en `tests/manual/` que **no** corre con `--test-enable`.

---

## 8. Integración con Odoo Sign (parte backend)

- Depender de `sign` en el `__manifest__.py` (coordinar con UI antes de añadir).
- Modelo `chat_umayor.contract` tiene `Many2one` a `sign.request`.
- Método `_launch_signature(contract)`:
  1. Crea `sign.request` con plantilla predefinida.
  2. Asocia firmante (`res.partner`) desde datos del chatbot.
  3. Devuelve URL pública de firma al frontend.
- Callback: al completarse la firma, Odoo Sign dispara un evento — suscribirse y marcar `contract.state = 'signed'`.
- **No implemento** el componente visual de firma ni el canvas — eso es UI.

---

## 9. Convenciones (mi código)

- ORM siempre. Cero SQL crudo salvo migración justificada.
- Nombres de modelos/campos **en inglés** (`partner_rut`, no `rut_cliente`).
- Labels de UI en español vía `.po` (cuando toque).
- Todo modelo nuevo → entrada en `security/ir.model.access.csv` en el **mismo** commit.
- `_description` + docstring en cada modelo.
- Métodos públicos del controller: docstring con payload de entrada y salida.

### No tocar
- `odoo/`, `addons/` (core).
- `views/`, `static/`, `*.xml` de plantillas QWeb del partner de UI.
- `*.pyc`, `__pycache__/`, `i18n/*.pot`.

---

## 10. Definición de "hecho" (para mi parte)

1. ✅ Módulo instala: `-i chat_umayor`.
2. ✅ Módulo actualiza: `-u chat_umayor`.
3. ✅ Mis tests pasan: `--test-enable --stop-after-init`.
4. ✅ `ruff check` limpio sobre `models/`, `services/`, `controllers/`.
5. ✅ Si toca modelo → `ir.model.access.csv` actualizado.
6. ✅ Si toca endpoint → `docs/api.md` actualizado.
7. ✅ Diff contenido en mis carpetas (no toco `views/`/`static/`).
8. ✅ Commit atómico con Conventional Commits.

---

## 11. Estado actual

<!-- Actualizar en cada sesión -->

### Backend (mío)
- [ ] Auditoría inicial del repo (`PLAN.md` en curso).
- [ ] Modelo `chatbot.session` con FSM.
- [ ] Modelo `chatbot.message`.
- [ ] Modelo `chatbot.contract` con vínculo a `sign.request`.
- [ ] Productos SOAP y Depósito en `data/products.xml`.
- [ ] Wrapper `services/gemini_client.py` + mocks.
- [ ] Controller `/chat_umayor/session/*` con los 4 endpoints.
- [ ] Método `_launch_signature` + callback de Sign.
- [ ] Tests unitarios de FSM, wrapper, contrato.
- [ ] `docs/api.md` con contrato backend↔frontend.

### Frontend (compañero — no modifico)
- [ ] Widget de chat en Website.
- [ ] Formulario de datos.
- [ ] Botón de firma.

<!-- v0.3 · 2026-05-02 · path real del módulo reconciliado (chat_umayor/ en raíz) -->
