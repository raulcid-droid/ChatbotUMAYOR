/** @odoo-module **/

(function () {
    function buildWidget() {
        const container = document.createElement("div");
        container.className = "chatbot-container";
        container.innerHTML = `
            <div class="chatbot-window" id="chatbot-window" style="display:none">
                <div class="chatbot-header">
                    <div class="chatbot-header-info">
                        <div class="chatbot-avatar">RRJ</div>
                        <div>
                            <div class="chatbot-header-name">Asistente Virtual</div>
                            <div class="chatbot-header-status">En línea</div>
                        </div>
                    </div>
                    <button class="chatbot-close" id="chatbot-close">✕</button>
                </div>
                <div class="chatbot-messages" id="chatbot-messages"></div>
                <div class="chatbot-input-area">
                    <input type="text" class="chatbot-input" id="chatbot-input" placeholder="Escribe tu mensaje..." />
                    <button class="chatbot-send-btn" id="chatbot-send">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="22" y1="2" x2="11" y2="13"/>
                            <polygon points="22 2 15 22 11 13 2 9 22 2"/>
                        </svg>
                    </button>
                </div>
            </div>
            <button class="chatbot-fab" id="chatbot-fab">
                <svg viewBox="0 0 24 24" fill="currentColor">
                    <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/>
                </svg>
            </button>
        `;
        document.body.appendChild(container);

        const window_ = container.querySelector("#chatbot-window");
        const fab     = container.querySelector("#chatbot-fab");
        const close   = container.querySelector("#chatbot-close");
        const input   = container.querySelector("#chatbot-input");
        const send    = container.querySelector("#chatbot-send");
        const msgs    = container.querySelector("#chatbot-messages");

        addMessage("¡Hola! Soy el asistente virtual del Banco RRJ. ¿En qué puedo ayudarte hoy?", "bot");

        fab.addEventListener("click", () => toggle(true));
        close.addEventListener("click", () => toggle(false));
        send.addEventListener("click", sendMessage);
        input.addEventListener("keydown", (e) => { if (e.key === "Enter") sendMessage(); });

        function toggle(open) {
            window_.style.display = open ? "flex" : "none";
            if (open) input.focus();
        }

        function addMessage(text, from) {
            const div = document.createElement("div");
            div.className = `chatbot-message chatbot-message--${from}`;
            div.innerHTML = `<div class="chatbot-bubble">${escapeHtml(text)}</div>`;
            msgs.appendChild(div);
            msgs.scrollTop = msgs.scrollHeight;
        }

        function showTyping() {
            const div = document.createElement("div");
            div.className = "chatbot-message chatbot-message--bot";
            div.id = "chatbot-typing";
            div.innerHTML = `<div class="chatbot-bubble chatbot-typing"><span></span><span></span><span></span></div>`;
            msgs.appendChild(div);
            msgs.scrollTop = msgs.scrollHeight;
        }

        function removeTyping() {
            const el = msgs.querySelector("#chatbot-typing");
            if (el) el.remove();
        }

        async function sendMessage() {
            const text = input.value.trim();
            if (!text) return;
            input.value = "";
            send.disabled = true;
            addMessage(text, "user");
            showTyping();
            try {
                const res = await fetch("/chat_umayor/message", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: { message: text } }),
                });
                const data = await res.json();
                removeTyping();
                addMessage(data.result?.reply || "No pude procesar tu mensaje.", "bot");
            } catch {
                removeTyping();
                addMessage("Error de conexión. Intenta más tarde.", "bot");
            } finally {
                send.disabled = false;
                input.focus();
            }
        }

        function escapeHtml(str) {
            return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", buildWidget);
    } else {
        buildWidget();
    }
})();
