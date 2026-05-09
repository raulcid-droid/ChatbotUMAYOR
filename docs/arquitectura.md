# Arquitectura — Chat UMayor

## Visión general

Módulo Odoo 19 (`chat_umayor`) que implementa un asistente virtual bancario integrado en el sitio web. El chatbot guía al usuario a través de la contratación de productos financieros usando Google Gemini como LLM.

---

## Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| Backend | Odoo 19 (Python) |
| LLM | Google Gemini via `google-genai` SDK |
| Frontend | OWL / Vanilla JS + CSS |
| Base de datos | PostgreSQL (via Odoo ORM) |
| Hosting | Odoo.sh |
| Firma electrónica | Odoo Sign |

---

## Estructura del módulo

```
chat_umayor/
├── models/
│   ├── chatbot_session.py       # Sesión con FSM (7 estados)
│   ├── chatbot_message.py       # Mensajes con sanitización PII
│   ├── chatbot_contract.py      # Contrato vinculado a Sign
│   ├── product_soap.py          # Producto: SOAP
│   ├── product_deposit.py       # Producto: Depósito a Plazo
│   ├── res_config_settings.py   # Config en Settings (compute/inverse)
│   ├── sign_request.py          # Override de Odoo Sign
│   └── chat_umayor_config.py    # Wizard de configuración standalone
├── services/
│   └── gemini_client.py         # Wrapper Google Gemini SDK
├── controllers/
│   └── main.py                  # Endpoints JSON-RPC
├── views/
│   ├── res_config_settings_views.xml  # Sección en Settings sidebar
│   └── assets.xml
├── data/
│   ├── system_prompt.xml        # Prompt inicial (noupdate)
│   └── products.xml             # Datos de productos
├── security/
│   └── ir.model.access.csv
├── static/src/
│   ├── js/chatbot.js            # Frontend base
│   ├── js/chatbot_extras.js     # Chips, formulario, firma
│   └── css/
└── requirements.txt             # google-genai
```

---

## Modelos

### `chatbot.session`
Núcleo del chatbot. Implementa una **FSM** (máquina de estados finitos):

```
greeting → discovery → product_info → data_collection → review → signing → closed
```

Responsabilidades:
- Detectar intención del usuario (`_classify_intent`)
- Validar RUT chileno
- Crear/encontrar `res.partner`
- Lanzar flujo de firma

### `chatbot.message`
Almacena cada mensaje. Sanitiza datos sensibles (RUT, email, teléfono) antes de enviarlos a Gemini para no exponer PII al LLM.

### `chat_umayor.contract`
Vincula sesión → partner → `sign.request`. Estados: `draft → signing → signed / cancelled`.

### `product.soap` / `product.deposit`
Datos de los dos productos del banco (SOAP vehicular y Depósito a Plazo). Gemini los consulta para responder preguntas.

---

## Servicio Gemini (`GeminiClient`)

- Lee API key desde `ir.config_parameter` con fallback a env `GEMINI_API_KEY`
- Construye prompt: `system_prompt + historial sanitizado`
- Manejo de errores: rate limit (backoff exponencial, 3 reintentos), timeout (1 reintento + fallback canned), auth error (LLMUnavailable)
- Import diferido del SDK (`from google import genai`) para no bloquear la instalación si el paquete no está

---

## API (endpoints JSON-RPC)

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/chatbot/ping` | GET | Health check |
| `/chatbot/session/new` | POST | Crea sesión, devuelve saludo |
| `/chatbot/session/message` | POST | Procesa mensaje → Gemini → avanza FSM |
| `/chatbot/session/submit_data` | POST | Recibe datos del formulario (nombre, RUT, email) |
| `/chatbot/session/sign` | POST | Lanza flujo de firma con Odoo Sign |
| `/chatbot/session/state` | GET | Estado actual de la sesión |

---

## Flujo completo de una conversación

```
Usuario abre web
       │
       ▼
POST /session/new ──► chatbot.session._create_with_greeting()
       │                       │
       │              Gemini genera saludo
       ▼
Usuario escribe
       │
       ▼
POST /session/message
       │
       ├──► _classify_intent() → avanza FSM
       ├──► chatbot.message._sanitize_for_llm()
       ├──► GeminiClient.generate_reply()
       └──► respuesta al frontend

[Si estado = data_collection]
       │
       ▼
POST /session/submit_data ──► valida RUT ──► crea res.partner

[Si estado = review]
       │
       ▼
POST /session/sign ──► chat_umayor.contract ──► sign.request (Odoo Sign)
                                                        │
                                              Usuario firma PDF
                                                        │
                                              sign.request._sign() override
                                                        │
                                              contract._mark_signed()
                                                        │
                                              session → closed
```

---

## Configuración

Accesible desde **Ajustes → Chat UMayor** (sidebar):

| Parámetro | `ir.config_parameter` key |
|-----------|--------------------------|
| Gemini API Key | `chat_umayor.gemini_api_key` |
| Modelo Gemini | `chat_umayor.gemini_model` |
| Timeout (s) | `chat_umayor.gemini_timeout_seconds` |
| System Prompt | `chat_umayor.system_prompt` |
| Plantilla firma | `chat_umayor.sign_template_id` |

Los campos usan `compute`/`inverse` con `store=False` para evitar columnas físicas en `res_config_settings`.

---

## Dependencias Odoo

```python
depends = ['website', 'base', 'mail', 'sign']
```

---

## Ramas del repositorio

| Rama | Autor | Contenido |
|------|-------|-----------|
| `main` | — | Producción (merge de todas las ramas) |
| `dev_jona` | Jona | Backend completo: modelos, servicios, API, tests |
| `dev_romina` | Romina | Frontend: UI, chips, formulario, validación RUT |
| `dev_raul` | Raúl | Integración, configuración, Odoo.sh |
| `tests_unitarios` | — | Suite de tests (15 archivos) |
