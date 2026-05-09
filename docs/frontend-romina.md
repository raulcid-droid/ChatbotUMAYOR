# Notas técnicas — capa de UI extendida

Documentación de los archivos `chatbot_extras.*` y `chatbot.test.js`
que extienden el widget base con el flujo completo de venta:
sugerencias rápidas, formulario de captura y firma de contrato.

---

## Archivos

```
chat_umayor/
├── static/src/
│   ├── js/
│   │   ├── chatbot.js              # widget base (existente)
│   │   └── chatbot_extras.js       # capa con chips, form, revisión y firma
│   ├── css/
│   │   ├── chatbot.css             # estilos base (existentes)
│   │   └── chatbot_extras.css      # estilos de los componentes nuevos
│   └── tests/
│       └── chatbot.test.js         # suite de pruebas frontend
└── docs_romina/
    └── README.md                    # este documento
```

`__manifest__.py` registra los nuevos assets en `web.assets_frontend`.

---

## Cómo funciona

`chatbot_extras.js` no modifica `chatbot.js`. Intercepta el botón de
envío y la tecla Enter para enrutar los mensajes a los endpoints
definidos en `docs/api.md`:

- `POST /chat_umayor/session/new`
- `POST /chat_umayor/session/<id>/message`
- `POST /chat_umayor/session/<id>/submit_data`
- `POST /chat_umayor/session/<id>/sign`

Si los endpoints no responden, el código activa un **modo demo** que
simula respuestas siguiendo el mismo contrato. Eso permite probar la
UI completa sin depender del backend.

### Estados de la conversación

```
greeting → discovery → product_info → data_collection → review → signing
```

El frontend no decide transiciones, solo refleja el `state` que devuelve
el backend (o el demo). Según el estado se renderizan distintos
componentes en el chat:

| Estado            | Componente que aparece              |
|-------------------|-------------------------------------|
| `discovery`       | Chips con productos sugeridos       |
| `product_info`    | Chips "Sí, contratar" / "Volver"    |
| `data_collection` | Formulario con campos del producto  |
| `review`          | Tarjeta de revisión + checkbox      |
| `signing`         | Pestaña externa con Odoo Sign       |

---

## Componentes

### Chips de sugerencias
Cuando el backend devuelve `suggestions: [...]`, se renderizan como
botones-chip debajo del último mensaje. Al tocarlos, el texto se envía
como mensaje del usuario.

### Formulario de captura
Aparece en estado `data_collection`. Campos comunes: nombre, RUT,
email, teléfono. Adicional según producto:
- **SOAP**: patente, año del vehículo
- **Depósito**: monto, plazo en días

El RUT se valida con el algoritmo módulo 11 antes de enviar. El campo
se autoformatea con puntos al perder el foco
(`12345678-5` → `12.345.678-5`).

### Tarjeta de revisión
Aparece en estado `review`. Resumen completo con datos del cliente,
producto y cálculos del backend (prima SOAP o intereses depósito).
Incluye un checkbox de aceptación obligatorio que habilita el botón
de firma — patrón estándar en banca digital para evitar contrataciones
por error.

### Firma con Odoo Sign
El botón llama a `/sign`, recibe la `sign_url` y abre el documento
en una pestaña nueva con `noopener`. Si el módulo `sign` no está
disponible (en demo), abre una página segura como respaldo.

---

## Validación de RUT (módulo 11)

Algoritmo oficial chileno:

1. Tomar los dígitos del cuerpo (sin DV) de derecha a izquierda.
2. Multiplicar por la serie 2,3,4,5,6,7 (cíclica).
3. Sumar todos los productos.
4. Calcular `11 - (suma % 11)`:
   - resultado 11 → DV = `0`
   - resultado 10 → DV = `K`
   - en otro caso → el dígito como string

Acepta entradas con puntos, guion o sin separadores. Rechaza:
RUT vacío, longitud fuera de 7-9, cuerpo no numérico, DV inválido,
DV calculado distinto del ingresado.

---

## Suite de pruebas (chatbot.test.js)

Se ejecuta desde la consola del navegador. Cubre 8 áreas:

1. Estructura del DOM (todos los elementos del widget existen)
2. Accesibilidad básica (placeholder, tipo de input, semántica)
3. Toggle del widget (apertura y cierre)
4. **Respuesta dentro del SLA <5s** (métrica clave de viabilidad)
5. Validación de input vacío (mensajes vacíos no se envían)
6. Resistencia a XSS (HTML inyectado se renderiza como texto)
7. Performance burst (5 mensajes seguidos, peor caso bajo SLA)
8. Validación de RUT módulo 11 (5 válidos + 7 inválidos)

Ejecución:
```javascript
ChatbotTests.runAll()
```

Los resultados se imprimen coloreados con un resumen final.
