/**
 * VoxDesk — Chat Component
 * Mesaj gönderme, streaming response, typing indicator.
 * Multimodal: file upload, drag & drop, paste, pin indicator.
 */

class VoxChat {
    constructor() {
        this.messagesEl = document.getElementById('chatMessages');
        this.inputEl = document.getElementById('chatInput');
        this.sendBtn = document.getElementById('btnSend');
        this.alwaysOnToggle = document.getElementById('alwaysOnToggle');
        this.pinIndicator = document.getElementById('pinIndicator');
        this.chatInputArea = document.getElementById('chatInputArea');
        this.lightbox = document.getElementById('lightbox');
        this.lightboxImg = document.getElementById('lightboxImg');

        // Screen context: backend-driven, frontend only controls ON/OFF
        this.includeScreen = true; // default: screen context ON
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
            this.autoResize();
        });

        this.inputEl.addEventListener('input', () => this.autoResize());

        // Screen context toggle (ON/OFF — backend is source of truth)
        this.alwaysOnToggle.addEventListener('change', async () => {
            this.includeScreen = this.alwaysOnToggle.checked;
            window.voxScreenEnabled = this.includeScreen;

            // Update UI immediately
            const dot = document.getElementById('captureDot');
            const previewImg = document.getElementById('previewImage');
            const placeholder = document.querySelector('.preview-placeholder');

            if (this.includeScreen) {
                if (dot) dot.classList.add('active');
            } else {
                if (dot) dot.classList.remove('active');
                // Show paused state
                if (previewImg) previewImg.style.opacity = '0.3';
                if (placeholder) {
                    placeholder.style.display = 'flex';
                    placeholder.querySelector('span').innerHTML = 'Ekran yakalama<br>devre dışı';
                }
            }

            // Notify backend
            try {
                const res = await fetch('/api/screen/toggle', { method: 'PUT' });
                const data = await res.json();
                if (data.status === 'ok') {
                    // Sync state
                    this.includeScreen = data.screen_enabled;
                    this.alwaysOnToggle.checked = data.screen_enabled;
                    window.voxScreenEnabled = data.screen_enabled;

                    if (data.screen_enabled) {
                        if (previewImg) previewImg.style.opacity = '1';
                    }
                }
            } catch (e) {
                console.error('[Chat] Screen toggle error:', e);
            }
        });

        // Lightbox
        this.lightbox.addEventListener('click', () => {
            this.lightbox.classList.remove('active');
        });

        // WS events
        window.voxWs.on('chat:message', (data) => this.handleWsMessage(data));
        window.voxWs.on('chat:connected', () => this.setStatus('Bağlandı'));
        window.voxWs.on('chat:disconnected', () => this.setStatus('Bağlantı kesildi...'));

        // Greeting time
        const timeEl = document.getElementById('greetingTime');
        if (timeEl) timeEl.textContent = this.formatTime(new Date());
    }


    // ── Pin Support ──────────────────────────────────────────

    showPinIndicator() {
        this.pinIndicator.classList.add('active');
    }

    hidePinIndicator() {
        this.pinIndicator.classList.remove('active');
    }

    // ── Send ─────────────────────────────────────────────────

    send() {
        const text = this.inputEl.value.trim();
        if (!text || this.isStreaming) return;

        // Disable send during streaming
        this.sendBtn.disabled = true;
        this.sendBtn.classList.add('disabled');

        // Show user message
        this.addMessage('user', text);
        this.inputEl.value = '';
        this.autoResize();

        // Send via WS — screen context is backend-driven, no attachments
        window.voxWs.sendChat(text, this.includeScreen);

        // Clear pin indicator (if any)
        this.hidePinIndicator();

        // Typing indicator
        this.showTyping();
    }

    handleWsMessage(data) {
        switch (data.type) {
            case 'start':
                this.isStreaming = true;
                this.sendBtn.disabled = true;
                this.sendBtn.classList.add('disabled');
                this.hideTyping();
                this.currentStreamEl = this.addMessage('assistant', '', true);
                this._waitingFirstToken = true;
                this._showStreamDots();
                break;

            case 'token':
                if (this._waitingFirstToken) {
                    this._waitingFirstToken = false;
                    this._hideStreamDots();
                }
                if (this.currentStreamEl) {
                    const contentEl = this.currentStreamEl.querySelector('.message-content');
                    contentEl.textContent += data.content;
                    this.scrollToBottom();
                }
                break;

            case 'end':
                this.isStreaming = false;
                // Sprint 7: Add read-aloud button to completed stream message
                if (this.currentStreamEl) {
                    this._addReadAloudButton(this.currentStreamEl);
                }
                this.currentStreamEl = null;
                this.sendBtn.disabled = false;
                this.sendBtn.classList.remove('disabled');
                break;

            case 'error':
                this.hideTyping();
                this._hideStreamDots();
                this.isStreaming = false;
                this.currentStreamEl = null;
                this.sendBtn.disabled = false;
                this.sendBtn.classList.remove('disabled');
                this.addMessage('assistant', `⚠️ ${data.message || 'An error occurred'}`);
                break;
        }
    }

    addMessage(role, content, isStream = false) {
        const msgEl = document.createElement('div');
        msgEl.className = `message message-${role}`;

        const avatarSvgs = {
            assistant: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="8" width="18" height="12" rx="3"/><circle cx="9" cy="14" r="1.5" fill="currentColor"/><circle cx="15" cy="14" r="1.5" fill="currentColor"/><path d="M9 4h6"/><line x1="12" y1="4" x2="12" y2="8"/></svg>',
            user: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
            system: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
        };
        const avatar = avatarSvgs[role] || avatarSvgs.user;

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

        // Sprint 7: Add read-aloud button to assistant messages (non-stream)
        if (role === 'assistant' && !isStream && content) {
            this._addReadAloudButton(msgEl);
        }

        return msgEl;
    }

    /**
     * Sprint 7: Add read-aloud button to a message element.
     * @param {HTMLElement} msgEl
     */
    _addReadAloudButton(msgEl) {
        const metaEl = msgEl.querySelector('.message-meta');
        const contentEl = msgEl.querySelector('.message-content');
        if (!metaEl || !contentEl) return;

        const text = contentEl.textContent?.trim();
        if (!text) return;

        const readBtn = document.createElement('button');
        readBtn.className = 'read-aloud-btn';
        readBtn.title = 'Sesli oku';
        readBtn.textContent = '🔊';
        readBtn.addEventListener('click', () => {
            window.dispatchEvent(new CustomEvent('readAloud', {
                detail: { text, button: readBtn },
            }));
        });
        metaEl.appendChild(readBtn);
    }

    showTyping() {
        const el = document.createElement('div');
        el.className = 'message message-assistant';
        el.id = 'typingIndicator';
        el.innerHTML = `
            <div class="message-avatar"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="8" width="18" height="12" rx="3"/><circle cx="9" cy="14" r="1.5" fill="currentColor"/><circle cx="15" cy="14" r="1.5" fill="currentColor"/><path d="M9 4h6"/><line x1="12" y1="4" x2="12" y2="8"/></svg></div>
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

    _showStreamDots() {
        if (!this.currentStreamEl) return;
        const contentEl = this.currentStreamEl.querySelector('.message-content');
        if (contentEl) {
            contentEl.innerHTML = `<span class="stream-dots">
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
            </span>`;
        }
    }

    _hideStreamDots() {
        if (!this.currentStreamEl) return;
        const contentEl = this.currentStreamEl.querySelector('.message-content');
        if (contentEl) {
            const dots = contentEl.querySelector('.stream-dots');
            if (dots) dots.remove();
        }
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
