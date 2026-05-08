# NOTES.md — Estado del proyecto chat_umayor

## Sesión 2026-05-02: Reinicio de plan - nuevo roadmap generado, enfocado en backend

### Progreso de la sesión
- ✅ **PLAN 01** cerrado: `AGENTS.md` reconciliado (path real `chat_umayor/` en raíz) + commits de `AGENTS.md`, `NOTES.md`, `PLAN.md` locales.
  - `c6877d3 docs(agents): add real module path at repo root`
  - `4268aa2 docs: add local AGENTS, NOTES and PLAN working notes`
- ✅ **PLAN 02** cerrado: `docs/api.md v0` con los 4 endpoints, catálogo de 8 errores, 6 TBDs explícitos.
  - `d8e1c2d docs(api): add v0 draft of backend-frontend contract`
- 🔄 **`PLAN.md` sobrescrito** con el roadmap de desarrollo (10 sub-planes) reemplazando el plan de auditoría inicial.

### Acuerdos operativos
- Los `git push` los hace Jonathan, no el agente.
- Cada fila del roadmap es un `PLAN.md` atómico nuevo, consensuado antes de ejecutar.

### Pendiente inmediato
- **PLAN 03**: módulo instalable end-to-end mínimo (controller `/chatbot` placeholder + cadena de imports + test smoke). Esperar "ok".

---


## Ruta de trabajo
`~/Proyectos/chatbot_bancario/chat-umayor/`

El módulo Odoo vive en `./chat_umayor/` (en la **raíz del repo**, no en
`custom_addons/`). Nombre definitivo del módulo: **`chat_umayor`**.

## Última sesión — 2026-05-01 · Auditoría inicial

### Decisiones tomadas
- **Nombre del módulo**: se mantiene `chat_umayor` (no se renombra a
  `banking_chatbot`). Razón: ya hay 7 commits y una compañera trabajando
  con esa estructura. Se actualiza `AGENTS.md` para reflejar la realidad.
- **Archivos vacíos intencionales**: `chat_umayor/__init__.py`,
  `controllers/__init__.py`, `controllers/main.py`, `views/assets.xml`,
  `static/src/js/chatbot.js`, `static/src/css/chatbot.css` son **stubs
  acordados** con la compañera de frontend para compartir estructura de
  carpetas. No son bugs.
- **Basura detectada y eliminada**: directorio literal
  `chat_umayor/static/src/{js,css}/` (residuo de `mkdir` sin brace
  expansion).

### Auditoría — ✅ Implementado
- Esqueleto mínimo de módulo Odoo 19:
  - `__manifest__.py` válido: `version: 19.0.1.0.0`, `depends: ['website']`,
    `license: LGPL-3`, `installable: True`.
  - Assets declarados en bundle `web.assets_frontend` (CSS + JS stubs).
- Git limpio, rama `dev_jona` sincronizada con `origin`.
- Cero secretos en el repo (grep de `AIza`, `API_KEY`, `sk-`, `GEMINI`
  → 0 matches).

### Auditoría — ❌ Falta (pendiente de implementar)

Severidades actualizadas tras la aclaración sobre stubs intencionales.

| Sev | Falta |
|---|---|
| 🔴 | **Cero modelos**: `models/` no existe. Falta `chatbot.session` (FSM §5 de AGENTS.md), `chatbot.message`, `chatbot.contract`. |
| 🔴 | **Cero integración Gemini**: no existe `services/gemini_client.py`. `google-genai` no declarado como dependencia. |
| 🔴 | No existe `security/ir.model.access.csv` (obligatorio al crear modelos). |
| 🟡 | Stubs por rellenar (coordinado con frontend): `__init__.py` raíz y `controllers/__init__.py` deben importar módulos cuando existan; `controllers/main.py` debe exponer `/chatbot`; `views/assets.xml` debe declarar templates QWeb. |
| 🟡 | `chatbot.js` y `chatbot.css` son stubs — la compañera los llenará. |
| 🟡 | No existe `data/` (productos SOAP/Depósito ni `system_prompt.xml`). |
| 🟡 | No existe `tests/`. |
| 🟡 | No existe `i18n/es.po`. |

### Respuestas a preguntas del PLAN de auditoría
1. ¿Instala en Odoo 19? **Sí**, pero instalaría un módulo vacío sin
   funcionalidad (el manifest es válido).
2. ¿Código que llame a Gemini? **No**, desde ningún lado.
3. ¿Modelos/persistencia? **No**, nada.
4. ¿Secretos hardcoded? **No**, confirmado por grep.
5. ¿Coincide el nombre con `AGENTS.md`? **No** → resuelto en PLAN 01.

## Roadmap (planes atómicos previstos)

1. ✅ **PLAN 01** — Reconciliar `AGENTS.md` + limpiar basura. *(en curso)*
2. **PLAN 02** — Módulo instalable end-to-end mínimo (controller `/chatbot`
   + template QWeb placeholder). Coordinar con frontend qué stubs rellenar.
3. **PLAN 03** — Modelo `chatbot.session` con FSM + ACL + tests.
4. **PLAN 04** — Modelo `chatbot.message` + `_sanitize_for_llm()` + ACL + tests.
5. **PLAN 05** — `services/gemini_client.py` con mocks, `ir.config_parameter`
   para API key y system prompt.
6. **PLAN 06** — Widget OWL del chat + endpoints JSON.
7. **PLAN 07** — Productos SOAP y Depósito en `data/products.xml` + cálculos.
8. **PLAN 08** — Formulario cliente + modelo `chatbot.contract`.
9. **PLAN 09** — Firma canvas + hash SHA-256.
10. **PLAN 10** — `i18n/es.po` + README de entrega académica.

## Pendiente inmediato
- Terminar PLAN 01 (actualizar `AGENTS.md`, limpiar dir basura).
- Luego esperar mi "ok" para arrancar PLAN 02.

<!-- v0.2 · 2026-05-01 · tras auditoría inicial -->
