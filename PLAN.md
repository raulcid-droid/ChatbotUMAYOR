# PLAN — Roadmap backend `chat_umayor`

## Objetivo
Entregar el módulo `chat_umayor` instalable y funcional (rol backend) en
sub-planes atómicos. Cada fila es un `PLAN.md` independiente: **1 commit
o 1 tanda de commits atómicos**, con tests cuando aplique (§5 AGENTS global).

## Alcance
Todo lo declarado como "mío" en §2 y §5 del `AGENTS.md` del repo:
modelos, services, controllers, data, security, tests y `docs/api.md`.
**No toco** `views/`, `static/`, ni QWeb/OWL/CSS.

## Roadmap

| #  | Estado | PLAN | Entregable |
|----|--------|------|------------|
| 01 | ✅ 2026-05-02 | Reconciliar `AGENTS.md` (path real `chat_umayor/` en raíz) + commitear docs locales | 2 commits `docs:` |
| 02 | ✅ 2026-05-02 | `docs/api.md v0` — contrato de los 4 endpoints (request/response/errores) **sin implementar** — desbloquea a UI | 1 commit `docs:` |
| 03 | ⏳ siguiente   | Módulo instalable end-to-end mínimo: controller `/chatbot` con respuesta placeholder JSON + cadena de imports (`__init__.py` raíz → `controllers/`) | 1 commit `feat:` + test smoke |
| 04 |               | Modelo `chatbot.session` con FSM (estados §6 AGENTS), transiciones `_transition_to_*`, ACL en `ir.model.access.csv` | 1 commit `feat:` + `test_session_fsm.py` (RED→GREEN) |
| 05 |               | Modelo `chatbot.message` + `_sanitize_for_llm()` + ACL + tests de sanitización | 1 commit `feat:` |
| 06 |               | `services/gemini_client.py`: wrapper `google-genai` con `ir.config_parameter` (`chat_umayor.gemini_api_key`, `chat_umayor.system_prompt`), reintentos, fallbacks §7 AGENTS, **tests con mock** | 1 commit `feat:` + `test_gemini_client.py`. Elegir modelo Flash y registrarlo aquí. |
| 07 |               | Endpoints reales: implementar los 4 endpoints del `docs/api.md`, conectar session + message + gemini; bump `docs/api.md` a `v1` | 1 commit `feat:` + `docs:` |
| 08 |               | Productos SOAP + Depósito a Plazo: `data/products.xml` + cálculos (prima SOAP, interés depósito) en el modelo del producto | 1 commit `feat:` + tests de cálculo |
| 09 |               | Modelo `chatbot.contract` + vínculo a `sign.request`. Agregar `sign` a `depends` (**coordinar con UI antes**), método `_launch_signature`, callback | 1 commit `feat:` + `test_contract.py` |
| 10 |               | `i18n/es.po` + README entrega académica (cómo instalar, demo, arquitectura) | 1 commit `docs:` + `chore:` |

## Reglas operativas

- **Un PLAN a la vez**. Antes de empezar cada fila escribo un `PLAN.md`
  detallado en formato §3 AGENTS global (objetivo, archivos, pasos,
  riesgos, rollback) y pido "ok".
- **Tests**: TDD ligero (§5 AGENTS global) en todo código no trivial.
  RED → GREEN → REFACTOR.
- **Coordinación con UI**: antes de tocar el `__manifest__.py` (agregar
  `sign`, `mail`) y antes de hacer cambios que impacten `docs/api.md`,
  aviso en el chat del equipo.
- **Push**: lo hace el humano (Jonathan), no yo.

## Riesgos globales

- Cambios del profesor en requisitos (país SOAP, campos obligatorios) →
  mitigado porque los TBDs están explícitos en `docs/api.md §5`.
- Desalineación con UI si implemento endpoints distintos al doc →
  mitigado porque `docs/api.md` es fuente de verdad y bumpea en el
  mismo commit que el controller (regla §10.6 AGENTS).
- Secretos (Gemini API key) → solo en `ir.config_parameter`, nunca en
  código, XML de datos, ni commits (§7 AGENTS + §14 AGENTS global).

## Rollback global
Cada PLAN es 1 commit atómico (o tanda pequeña): `git revert <sha>` o
`git reset --hard <sha-anterior>` si todavía no hay push.

<!-- v1.0 · 2026-05-02 · reemplaza el PLAN de auditoría por el roadmap de desarrollo -->
