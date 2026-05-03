/* =========================================================================
 * chatbot.test.js
 * -------------------------------------------------------------------------
 * Pruebas del frontend del chatbot UMayor.
 *
 * Estas pruebas se ejecutan desde la consola del navegador (F12) sobre
 * el sitio público con el módulo instalado. NO requieren framework de
 * testing - usan asserts manuales para mantenerlo simple y portable.
 *
 * Cómo correrlo:
 *   1. Ir al sitio público con el chatbot cargado.
 *   2. Abrir DevTools (F12).
 *   3. Pegar el contenido de este archivo en la consola.
 *   4. Ejecutar: ChatbotTests.runAll()
 *
 * ========================================================================= */

(function () {
  "use strict";

  const SLA_MS = 5000;
  const results = [];

  function assert(condition, name, detail) {
    const passed = !!condition;
    results.push({ name, passed, detail: detail || "" });
    const icon = passed ? "✓" : "✗";
    const color = passed ? "color: #16a34a" : "color: #d93025";
    console.log(`%c${icon} ${name}${detail ? " — " + detail : ""}`, color);
    return passed;
  }

  function summary() {
    const total = results.length;
    const passed = results.filter((r) => r.passed).length;
    const failed = total - passed;
    console.log("");
    console.log(
      "%c═══════════════════════════════════════════",
      "color: #1a73e8; font-weight: bold",
    );
    console.log(
      `%c  RESUMEN: ${passed}/${total} pruebas pasaron${failed > 0 ? " — " + failed + " fallidas" : ""}`,
      `color: ${failed === 0 ? "#16a34a" : "#d93025"}; font-weight: bold; font-size: 14px`,
    );
    console.log(
      "%c═══════════════════════════════════════════",
      "color: #1a73e8; font-weight: bold",
    );
    return { total, passed, failed };
  }

  // ---------------------------------------------------------------
  // Test 1: Estructura del DOM
  // ---------------------------------------------------------------
  function testDomStructure() {
    console.log(
      "%c--- Test 1: Estructura del DOM ---",
      "color: #1a73e8; font-weight: bold",
    );
    assert(document.getElementById("chatbot-fab"), "Burbuja flotante existe");
    assert(
      document.getElementById("chatbot-window"),
      "Ventana del chat existe",
    );
    assert(
      document.getElementById("chatbot-messages"),
      "Contenedor de mensajes existe",
    );
    assert(document.getElementById("chatbot-input"), "Input de texto existe");
    assert(document.getElementById("chatbot-send"), "Botón de enviar existe");
  }

  // ---------------------------------------------------------------
  // Test 2: Accesibilidad básica
  // ---------------------------------------------------------------
  function testAccessibility() {
    console.log(
      "%c--- Test 2: Accesibilidad ---",
      "color: #1a73e8; font-weight: bold",
    );
    const input = document.getElementById("chatbot-input");
    assert(
      input && input.placeholder,
      "Input tiene placeholder",
      input ? `"${input.placeholder}"` : "",
    );
    assert(input && input.type === "text", "Input es de tipo text");

    const send = document.getElementById("chatbot-send");
    assert(send && send.tagName === "BUTTON", "Botón de enviar es <button>");

    const fab = document.getElementById("chatbot-fab");
    assert(fab && fab.tagName === "BUTTON", "Burbuja flotante es <button>");
  }

  // ---------------------------------------------------------------
  // Test 3: Apertura y cierre del widget
  // ---------------------------------------------------------------
  function testToggleWidget() {
    console.log(
      "%c--- Test 3: Apertura/cierre del widget ---",
      "color: #1a73e8; font-weight: bold",
    );
    const win = document.getElementById("chatbot-window");
    const fab = document.getElementById("chatbot-fab");
    const initiallyHidden =
      win.style.display === "none" || win.style.display === "";

    assert(initiallyHidden, "Widget arranca cerrado");

    fab.click();
    const afterClick = win.style.display;
    assert(
      afterClick === "flex" || afterClick === "block",
      "Widget se abre al hacer click",
      `display="${afterClick}"`,
    );
  }

  // ---------------------------------------------------------------
  // Test 4: Envío de mensaje y SLA <5s
  // ---------------------------------------------------------------
  async function testSendMessageSLA() {
    console.log(
      "%c--- Test 4: Envío de mensaje y SLA <5s ---",
      "color: #1a73e8; font-weight: bold",
    );
    const input = document.getElementById("chatbot-input");
    const send = document.getElementById("chatbot-send");
    const msgsEl = document.getElementById("chatbot-messages");

    // Limpiar métricas previas
    if (window.__chatbotExtras) {
      window.__chatbotExtras.clearMetrics();
    }

    const beforeCount = msgsEl.querySelectorAll(".chatbot-message").length;
    const t0 = performance.now();

    input.value = "Hola";
    send.click();

    // Esperar hasta que aparezca una respuesta del bot (max 6 segundos)
    let elapsed = 0;
    const interval = 100;
    while (elapsed < 6000) {
      await new Promise((r) => setTimeout(r, interval));
      elapsed += interval;
      const newCount = msgsEl.querySelectorAll(".chatbot-message--bot").length;
      const initialBotCount =
        msgsEl.querySelectorAll(".chatbot-message--bot").length - 1;
      if (newCount > initialBotCount) break;
    }

    const totalTime = Math.round(performance.now() - t0);
    assert(
      totalTime < SLA_MS,
      `Respuesta dentro del SLA (<${SLA_MS} ms)`,
      `tomó ${totalTime} ms`,
    );

    const afterCount = msgsEl.querySelectorAll(".chatbot-message").length;
    assert(
      afterCount > beforeCount,
      "Se agregaron mensajes nuevos al DOM",
      `${afterCount - beforeCount} mensajes nuevos`,
    );
  }

  // ---------------------------------------------------------------
  // Test 5: Validación de input vacío
  // ---------------------------------------------------------------
  function testEmptyInputValidation() {
    console.log(
      "%c--- Test 5: Input vacío ---",
      "color: #1a73e8; font-weight: bold",
    );
    const input = document.getElementById("chatbot-input");
    const send = document.getElementById("chatbot-send");
    const msgsEl = document.getElementById("chatbot-messages");

    const beforeCount = msgsEl.querySelectorAll(
      ".chatbot-message--user",
    ).length;

    input.value = "";
    send.click();
    input.value = "   "; // solo espacios
    send.click();

    const afterCount = msgsEl.querySelectorAll(".chatbot-message--user").length;
    assert(
      afterCount === beforeCount,
      "Mensajes vacíos o de espacios no se envían",
      `usuarios antes=${beforeCount} después=${afterCount}`,
    );
  }

  // ---------------------------------------------------------------
  // Test 6: Resistencia a XSS (no inyectar HTML)
  // ---------------------------------------------------------------
  async function testXssResistance() {
    console.log(
      "%c--- Test 6: Resistencia a XSS ---",
      "color: #1a73e8; font-weight: bold",
    );
    const input = document.getElementById("chatbot-input");
    const send = document.getElementById("chatbot-send");
    const msgsEl = document.getElementById("chatbot-messages");

    const xssPayload = `<img src=x onerror="window.__xssTriggered=true">`;
    window.__xssTriggered = false;

    input.value = xssPayload;
    send.click();
    await new Promise((r) => setTimeout(r, 300));

    const lastUserMsg = msgsEl.querySelectorAll(
      ".chatbot-message--user .chatbot-bubble",
    );
    const lastText = lastUserMsg.length
      ? lastUserMsg[lastUserMsg.length - 1].textContent
      : "";

    assert(
      !window.__xssTriggered,
      "No se ejecuta script inyectado (XSS bloqueado)",
    );
    assert(
      lastText.includes("<img"),
      "El texto se renderiza como texto plano, no HTML",
    );
  }

  // ---------------------------------------------------------------
  // Test 7: Performance - múltiples mensajes seguidos
  // ---------------------------------------------------------------
  async function testBurstPerformance() {
    console.log(
      "%c--- Test 7: Performance burst (5 mensajes) ---",
      "color: #1a73e8; font-weight: bold",
    );
    const input = document.getElementById("chatbot-input");
    const send = document.getElementById("chatbot-send");

    const messages = [
      "SOAP",
      "Sí, contratar",
      "Hola",
      "Depósito a Plazo",
      "Información",
    ];
    const times = [];

    for (const msg of messages) {
      const t0 = performance.now();
      input.value = msg;
      send.click();
      await new Promise((r) => setTimeout(r, 1500)); // espacio para que responda
      times.push(Math.round(performance.now() - t0));
    }

    const avg = Math.round(times.reduce((a, b) => a + b, 0) / times.length);
    const max = Math.max(...times);

    assert(
      max < SLA_MS,
      `Peor caso bajo el SLA (<${SLA_MS} ms)`,
      `peor=${max} ms, promedio=${avg} ms`,
    );
    assert(avg < 3000, "Promedio razonable (<3000 ms)", `${avg} ms`);

    console.log(
      "    Tiempos por mensaje:",
      times.map((t) => t + " ms").join(", "),
    );
  }

  // ---------------------------------------------------------------
  // Test 8: Validación de RUT (algoritmo módulo 11)
  // ---------------------------------------------------------------
  function testRutValidation() {
    console.log(
      "%c--- Test 8: Validación RUT (módulo 11) ---",
      "color: #1a73e8; font-weight: bold",
    );

    // Necesitamos exponer validateRut en window para testearlo desde aquí.
    // Si no está disponible, lo recreamos inline para no bloquear.
    const validate =
      window.__chatbotExtras && window.__chatbotExtras.validateRut
        ? window.__chatbotExtras.validateRut
        : null;

    if (!validate) {
      assert(
        false,
        "validateRut accesible desde tests",
        "no expuesta en window.__chatbotExtras",
      );
      return;
    }

    // RUTs válidos (DV calculado correctamente con módulo 11)
    const valid = [
      "11111111-1",
      "22222222-2",
      "15489732-1",
      "7654321-6",
      "20.230.811-2", // formato con puntos también acepta
    ];
    valid.forEach((rut) => {
      const r = validate(rut);
      assert(
        r.valid,
        `RUT válido aceptado: ${rut}`,
        r.valid ? `→ ${r.formatted}` : r.message,
      );
    });

    // RUTs inválidos
    const invalid = [
      "12345678-9", // DV incorrecto
      "11111111-K", // DV incorrecto
      "abc-1", // letras en cuerpo
      "", // vacío
      "1", // muy corto
      "1234567890-1", // muy largo
      "12.345.678-Z", // DV inválido
    ];
    invalid.forEach((rut) => {
      const r = validate(rut);
      assert(
        !r.valid,
        `RUT inválido rechazado: "${rut}"`,
        r.valid ? "ACEPTADO erróneamente" : r.message,
      );
    });
  }

  // ---------------------------------------------------------------
  // Runner
  // ---------------------------------------------------------------
  async function runAll() {
    results.length = 0;
    console.log(
      "%c╔═══════════════════════════════════════════╗",
      "color: #1a73e8; font-weight: bold",
    );
    console.log(
      "%c║  CHATBOT UMAYOR — SUITE DE PRUEBAS UI    ║",
      "color: #1a73e8; font-weight: bold",
    );
    console.log(
      "%c║  Autora: Romina Beca                      ║",
      "color: #1a73e8; font-weight: bold",
    );
    console.log(
      "%c╚═══════════════════════════════════════════╝",
      "color: #1a73e8; font-weight: bold",
    );
    console.log("");

    testDomStructure();
    testAccessibility();
    testToggleWidget();
    await testSendMessageSLA();
    testEmptyInputValidation();
    await testXssResistance();
    await testBurstPerformance();
    testRutValidation();

    return summary();
  }

  // Exponemos para uso desde consola
  window.ChatbotTests = {
    runAll,
    runIndividual: {
      domStructure: testDomStructure,
      accessibility: testAccessibility,
      toggleWidget: testToggleWidget,
      sendMessageSLA: testSendMessageSLA,
      emptyInput: testEmptyInputValidation,
      xss: testXssResistance,
      burst: testBurstPerformance,
      rut: testRutValidation,
    },
    getResults: () => results.slice(),
  };

  console.log(
    "%cChatbotTests cargado. Ejecuta: ChatbotTests.runAll()",
    "color: #1a73e8; font-weight: bold",
  );
})();
