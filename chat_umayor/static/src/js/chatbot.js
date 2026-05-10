/** @odoo-module **/

(function () {
    function buildWidget() {
        const container = document.createElement("div");
        container.className = "chatbot-container";
        container.innerHTML = `
            <div class="chatbot-window" id="chatbot-window" style="display:none">
                <div class="chatbot-header">
                    <div class="chatbot-header-info">
                        <div class="chatbot-avatar">UM</div>
                        <div>
                            <div class="chatbot-header-name">Chatbot UMayor</div>
                            <div class="chatbot-header-status">En línea</div>
                        </div>
                    </div>
                    <div class="chatbot-header-actions">
                        <button class="chatbot-expand" id="chatbot-expand" title="Ampliar">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                                <polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/>
                                <line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>
                            </svg>
                        </button>
                        <button class="chatbot-close" id="chatbot-close">✕</button>
                    </div>
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
        const expand  = container.querySelector("#chatbot-expand");
        const input   = container.querySelector("#chatbot-input");
        const send    = container.querySelector("#chatbot-send");
        const msgs    = container.querySelector("#chatbot-messages");

        addMessage("¡Hola! Soy el asistente virtual de UMayor. ¿En qué puedo ayudarte hoy?", "bot");

        fab.addEventListener("click", () => toggle(true));
        close.addEventListener("click", () => toggle(false));
        expand.addEventListener("click", toggleExpand);
        send.addEventListener("click", sendMessage);
        input.addEventListener("keydown", (e) => { if (e.key === "Enter") sendMessage(); });

        function toggle(open) {
            window_.style.display = open ? "flex" : "none";
            if (open) input.focus();
        }

        function toggleExpand() {
            const isExpanded = window_.classList.toggle("chatbot-window--expanded");
            expand.title = isExpanded ? "Reducir" : "Ampliar";
            expand.innerHTML = isExpanded
                ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                       <polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/>
                       <line x1="10" y1="14" x2="3" y2="21"/><line x1="21" y1="3" x2="14" y2="10"/>
                   </svg>`
                : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                       <polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/>
                       <line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>
                   </svg>`;
            msgs.scrollTop = msgs.scrollHeight;
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
