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
        this.uploadBtn = document.getElementById('btnUpload');
        this.fileInput = document.getElementById('fileInput');
        this.attachmentStrip = document.getElementById('attachmentStrip');
        this.alwaysOnToggle = document.getElementById('alwaysOnToggle');
        this.pinIndicator = document.getElementById('pinIndicator');
        this.chatInputArea = document.getElementById('chatInputArea');
        this.dropOverlay = document.getElementById('dropOverlay');
        this.lightbox = document.getElementById('lightbox');
        this.lightboxImg = document.getElementById('lightboxImg');

        this.includeScreen = true; // always-on default
        this.isStreaming = false;
        this.currentStreamEl = null;
        this.attachments = []; // {data: base64, preview: dataURL, type: 'file'|'pin'}
        this.MAX_ATTACHMENTS = 5;
        this.MAX_IMAGE_WIDTH = 1920;

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

        // Always-on toggle (iOS style)
        this.alwaysOnToggle.addEventListener('change', () => {
            this.includeScreen = this.alwaysOnToggle.checked;
        });

        // Upload button → file input
        this.uploadBtn.addEventListener('click', () => this.fileInput.click());

        // File input change
        this.fileInput.addEventListener('change', (e) => {
            this.handleFiles(e.target.files);
            this.fileInput.value = ''; // Reset so same file can be selected again
        });

        // Drag & drop on input area
        this.chatInputArea.addEventListener('dragenter', (e) => {
            e.preventDefault();
            this.dropOverlay.classList.add('active');
        });
        this.chatInputArea.addEventListener('dragover', (e) => {
            e.preventDefault();
        });
        this.chatInputArea.addEventListener('dragleave', (e) => {
            // Only hide if leaving the actual area
            if (!this.chatInputArea.contains(e.relatedTarget)) {
                this.dropOverlay.classList.remove('active');
            }
        });
        this.chatInputArea.addEventListener('drop', (e) => {
            e.preventDefault();
            this.dropOverlay.classList.remove('active');
            if (e.dataTransfer.files.length > 0) {
                this.handleFiles(e.dataTransfer.files);
            }
        });

        // Paste image from clipboard (Ctrl+V)
        this.inputEl.addEventListener('paste', (e) => {
            const items = e.clipboardData?.items;
            if (!items) return;
            for (const item of items) {
                if (item.type.startsWith('image/')) {
                    e.preventDefault();
                    const file = item.getAsFile();
                    if (file) this.handleFiles([file]);
                    return;
                }
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

    // ── File Handling ────────────────────────────────────────

    handleFiles(files) {
        for (const file of files) {
            if (!file.type.startsWith('image/')) continue;
            if (this.attachments.length >= this.MAX_ATTACHMENTS) {
                console.warn('[Chat] Max attachment limit reached');
                break;
            }
            this.processImage(file);
        }
    }

    processImage(file) {
        const reader = new FileReader();
        reader.onload = (e) => {
            const img = new Image();
            img.onload = () => {
                // Resize if needed
                const canvas = document.createElement('canvas');
                let w = img.width;
                let h = img.height;
                if (w > this.MAX_IMAGE_WIDTH) {
                    h = Math.round(h * (this.MAX_IMAGE_WIDTH / w));
                    w = this.MAX_IMAGE_WIDTH;
                }
                canvas.width = w;
                canvas.height = h;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, w, h);

                // Convert to JPEG for consistent LLM input
                const dataUrl = canvas.toDataURL('image/jpeg', 0.92);

                const attachment = {
                    data: dataUrl,
                    preview: dataUrl,
                    type: 'file',
                    name: file.name,
                };
                this.attachments.push(attachment);
                this.renderAttachments();
            };
            img.src = e.target.result;
        };
        reader.readAsDataURL(file);
    }

    renderAttachments() {
        this.attachmentStrip.innerHTML = '';
        this.attachments.forEach((att, index) => {
            const thumb = document.createElement('div');
            thumb.className = 'attachment-thumb';

            const img = document.createElement('img');
            img.src = att.preview;
            img.alt = att.name || 'Attachment';
            img.addEventListener('click', () => this.showLightbox(att.preview));

            const removeBtn = document.createElement('button');
            removeBtn.className = 'remove-btn';
            removeBtn.textContent = '✕';
            removeBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.attachments.splice(index, 1);
                this.renderAttachments();
            });

            thumb.appendChild(img);
            thumb.appendChild(removeBtn);

            if (att.type === 'pin') {
                const badge = document.createElement('span');
                badge.className = 'pin-badge';
                badge.textContent = '📌 PIN';
                thumb.appendChild(badge);
            }

            this.attachmentStrip.appendChild(thumb);
        });
    }

    showLightbox(src) {
        this.lightboxImg.src = src;
        this.lightbox.classList.add('active');
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
        if ((!text && this.attachments.length === 0) || this.isStreaming) return;

        // Disable send during streaming
        this.sendBtn.disabled = true;
        this.sendBtn.classList.add('disabled');

        // Show user message with any attachment thumbnails
        this.addMessage('user', text, false, this.attachments.map(a => a.preview));
        this.inputEl.value = '';
        this.autoResize();

        // Build attachment payload
        const attachmentPayload = this.attachments.map(a => ({
            data: a.data,
            type: a.type,
        }));

        // Send via WS
        window.voxWs.sendChat(text, this.includeScreen, attachmentPayload);

        // Clear attachments & pin indicator
        this.attachments = [];
        this.renderAttachments();
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

    addMessage(role, content, isStream = false, imagePreviews = []) {
        const msgEl = document.createElement('div');
        msgEl.className = `message message-${role}`;

        const avatarSvgs = {
            assistant: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="8" width="18" height="12" rx="3"/><circle cx="9" cy="14" r="1.5" fill="currentColor"/><circle cx="15" cy="14" r="1.5" fill="currentColor"/><path d="M9 4h6"/><line x1="12" y1="4" x2="12" y2="8"/></svg>',
            user: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
            system: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
        };
        const avatar = avatarSvgs[role] || avatarSvgs.user;

        // Build image thumbnails HTML
        let imagesHtml = '';
        if (imagePreviews && imagePreviews.length > 0) {
            imagesHtml = '<div class="message-attachments">';
            for (let i = 0; i < imagePreviews.length; i++) {
                imagesHtml += `<img src="${this.escapeHtml(imagePreviews[i])}" alt="Attachment" data-lightbox-index="${i}">`;
            }
            imagesHtml += '</div>';
        }

        msgEl.innerHTML = `
            <div class="message-avatar">${avatar}</div>
            <div class="message-bubble">
                ${imagesHtml}
                <div class="message-content">${this.escapeHtml(content)}</div>
                <div class="message-meta">
                    <span class="message-time">${this.formatTime(new Date())}</span>
                </div>
            </div>
        `;

        this.messagesEl.appendChild(msgEl);

        // Safe click delegation for lightbox images (replaces inline onclick XSS)
        if (imagePreviews && imagePreviews.length > 0) {
            const imgs = msgEl.querySelectorAll('img[data-lightbox-index]');
            imgs.forEach(img => {
                const idx = parseInt(img.dataset.lightboxIndex, 10);
                img.style.cursor = 'pointer';
                img.addEventListener('click', () => this.showLightbox(imagePreviews[idx]));
            });
        }

        this.scrollToBottom();
        return msgEl;
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
