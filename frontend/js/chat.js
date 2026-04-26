/**
 * VoxDesk — Chat Component
 * Mesaj gönderme, streaming response, typing indicator.
 */

class VoxChat {
    constructor() {
        this.messagesEl = document.getElementById('chatMessages');
        this.inputEl = document.getElementById('chatInput');
        this.sendBtn = document.getElementById('btnSend');
        this.screenshotBtn = document.getElementById('btnScreenshot');
        this.includeScreen = true;
        this.isStreaming = false;
        this.currentStreamEl = null;

        this.init();
    }

    init() {
        // Send button
        this.sendBtn.addEventListener('click', () => this.send());

        // Enter / Ctrl+Enter
        this.inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && e.ctrlKey) {
                e.preventDefault();
                this.send();
            }
            // Auto-resize
            this.autoResize();
        });

        this.inputEl.addEventListener('input', () => this.autoResize());

        // Screenshot toggle
        this.screenshotBtn.addEventListener('click', () => {
            this.includeScreen = !this.includeScreen;
            this.screenshotBtn.style.opacity = this.includeScreen ? '1' : '0.4';
        });

        // WS events
        window.voxWs.on('chat:message', (data) => this.handleWsMessage(data));
        window.voxWs.on('chat:connected', () => this.setStatus('Bağlandı'));
        window.voxWs.on('chat:disconnected', () => this.setStatus('Bağlantı kesildi...'));

        // Greeting time
        const timeEl = document.getElementById('greetingTime');
        if (timeEl) timeEl.textContent = this.formatTime(new Date());
    }

    send() {
        const text = this.inputEl.value.trim();
        if (!text || this.isStreaming) return;

        // Kullanıcı mesajını ekle
        this.addMessage('user', text);
        this.inputEl.value = '';
        this.autoResize();

        // WS üzerinden gönder
        window.voxWs.sendChat(text, this.includeScreen);

        // Typing indicator
        this.showTyping();
    }

    handleWsMessage(data) {
        switch (data.type) {
            case 'start':
                this.isStreaming = true;
                this.hideTyping();
                this.currentStreamEl = this.addMessage('assistant', '', true);
                break;

            case 'token':
                if (this.currentStreamEl) {
                    const contentEl = this.currentStreamEl.querySelector('.message-content');
                    contentEl.textContent += data.content;
                    this.scrollToBottom();
                }
                break;

            case 'end':
                this.isStreaming = false;
                this.currentStreamEl = null;
                break;
        }
    }

    addMessage(role, content, isStream = false) {
        const msgEl = document.createElement('div');
        msgEl.className = `message message-${role}`;

        const avatar = role === 'assistant' ? '🤖' : '👤';

        msgEl.innerHTML = `
            <div class="message-avatar">${avatar}</div>
            <div class="message-bubble">
                <div class="message-content">${this.escapeHtml(content)}</div>
                <div class="message-meta">
                    <span class="message-time">${this.formatTime(new Date())}</span>
                </div>
            </div>
        `;

        this.messagesEl.appendChild(msgEl);
        this.scrollToBottom();
        return msgEl;
    }

    showTyping() {
        const el = document.createElement('div');
        el.className = 'message message-assistant';
        el.id = 'typingIndicator';
        el.innerHTML = `
            <div class="message-avatar">🤖</div>
            <div class="message-bubble">
                <div class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
        `;
        this.messagesEl.appendChild(el);
        this.scrollToBottom();
    }

    hideTyping() {
        const el = document.getElementById('typingIndicator');
        if (el) el.remove();
    }

    setStatus(text) {
        const el = document.getElementById('statusText');
        if (el) el.textContent = text;
    }

    scrollToBottom() {
        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
    }

    autoResize() {
        this.inputEl.style.height = 'auto';
        this.inputEl.style.height = Math.min(this.inputEl.scrollHeight, 120) + 'px';
    }

    formatTime(date) {
        return date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

window.VoxChat = null;
