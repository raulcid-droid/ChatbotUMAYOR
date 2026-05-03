/** @odoo-module **/
import { Component, useState, useRef, useEffect, mount, whenReady } from "@odoo/owl";

class ChatBot extends Component {
    static template = "chat_umayor.ChatBot";
    static props = {};

    setup() {
        this.state = useState({
            isOpen: false,
            messages: [
                {
                    text: "¡Hola! Soy el asistente virtual del Banco RRJ. ¿En qué puedo ayudarte hoy?",
                    from: "bot",
                },
            ],
            inputValue: "",
            isLoading: false,
        });

        this.messagesContainer = useRef("messagesContainer");

        useEffect(
            () => {
                const el = this.messagesContainer.el;
                if (el) el.scrollTop = el.scrollHeight;
            },
            () => [this.state.messages.length, this.state.isLoading]
        );
    }
    

    toggleChat() {
        this.state.isOpen = !this.state.isOpen;
    }

    async sendMessage() {
        const text = this.state.inputValue.trim();
        if (!text || this.state.isLoading) return;

        this.state.messages.push({ text, from: "user" });
        this.state.inputValue = "";
        this.state.isLoading = true;

        try {
            const response = await fetch("/chat_umayor/message", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: text }),
            });
            const data = await response.json();
            this.state.messages.push({
                text: data.result?.reply || "No pude procesar tu mensaje. Intenta nuevamente.",
                from: "bot",
            });
        } catch {
            this.state.messages.push({
                text: "Error de conexión. Por favor, intenta más tarde.",
                from: "bot",
            });
        } finally {
            this.state.isLoading = false;
        }
    }

    onKeyDown(ev) {
        if (ev.key === "Enter") this.sendMessage();
    }
}

whenReady(() => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    mount(ChatBot, container);
});
