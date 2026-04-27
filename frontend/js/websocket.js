/**
 * VoxDesk — WebSocket Communication
 * Chat, screen preview, voice WebSocket bağlantıları.
 */

class VoxWebSocket {
    constructor() {
        this.chatWs = null;
        this.screenWs = null;
        this.voiceWs = null;
        this.baseUrl = `ws://${window.location.host}`;
        this.callbacks = {};
        // Sprint 3: backoff state
        this._chatRetries = 0;
        this._screenRetries = 0;
        this._maxRetries = 10;
    }

    on(event, callback) {
        if (!this.callbacks[event]) this.callbacks[event] = [];
        this.callbacks[event].push(callback);
    }

    emit(event, data) {
        (this.callbacks[event] || []).forEach(cb => cb(data));
    }

    // Sprint 3: exponential backoff with ±20% jitter
    _getBackoffDelay(attempt) {
        const base = Math.min(1000 * Math.pow(2, attempt), 30000);
        const jitter = base * 0.2 * (Math.random() * 2 - 1);
        return Math.max(500, base + jitter);
    }

    connectChat() {
        // Sprint 3: CONNECTING guard
        if (this.chatWs?.readyState === WebSocket.OPEN ||
            this.chatWs?.readyState === WebSocket.CONNECTING) return;

        this.chatWs = new WebSocket(`${this.baseUrl}/api/ws/chat`);

        this.chatWs.onopen = () => {
            this._chatRetries = 0;
            console.log('[WS] Chat connected');
            this.emit('chat:connected');
        };

        this.chatWs.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.emit('chat:message', data);
            } catch (e) {
                console.error('[WS] Parse error:', e);
            }
        };

        this.chatWs.onclose = () => {
            console.log('[WS] Chat disconnected');
            this.emit('chat:disconnected');
            if (this._chatRetries < this._maxRetries) {
                const delay = this._getBackoffDelay(this._chatRetries++);
                console.log(`[WS] Chat reconnect in ${Math.round(delay)}ms (attempt ${this._chatRetries})`);
                setTimeout(() => this.connectChat(), delay);
            } else {
                console.warn('[WS] Chat max retries reached');
                this.emit('chat:max_retries');
            }
        };

        this.chatWs.onerror = (err) => {
            console.error('[WS] Chat error:', err);
        };
    }

    connectScreen() {
        // Sprint 3: CONNECTING guard
        if (this.screenWs?.readyState === WebSocket.OPEN ||
            this.screenWs?.readyState === WebSocket.CONNECTING) return;

        this.screenWs = new WebSocket(`${this.baseUrl}/api/ws/screen`);

        // Sprint 3: missing onopen handler
        this.screenWs.onopen = () => {
            this._screenRetries = 0;
            console.log('[WS] Screen connected');
            this.emit('screen:connected');
        };

        this.screenWs.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.emit('screen:frame', data);
            } catch (e) { /* ignore */ }
        };

        this.screenWs.onclose = () => {
            console.log('[WS] Screen disconnected');
            this.emit('screen:disconnected');
            if (this._screenRetries < this._maxRetries) {
                const delay = this._getBackoffDelay(this._screenRetries++);
                setTimeout(() => this.connectScreen(), delay);
            } else {
                console.warn('[WS] Screen max retries reached');
                this.emit('screen:max_retries');
            }
        };

        // Sprint 3: missing onerror handler
        this.screenWs.onerror = (err) => {
            console.error('[WS] Screen error:', err);
            this.emit('screen:error', err);
        };
    }

    connectVoice() {
        if (this.voiceWs?.readyState === WebSocket.OPEN ||
            this.voiceWs?.readyState === WebSocket.CONNECTING) return;

        // Sprint 2: Use v2 binary endpoint (prefix-consistent with chat/screen)
        this.voiceWs = new WebSocket(`${this.baseUrl}/api/ws/voice/v2`);

        this.voiceWs.onopen = () => {
            console.log('[WS] Voice v2 connected');
            this.emit('voice:connected');
        };

        this.voiceWs.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.emit('voice:message', data);
            } catch (e) { /* binary frame or parse error — ignore */ }
        };

        // Sprint 2: NO auto-reconnect for voice — user manually retries
        this.voiceWs.onclose = () => {
            console.log('[WS] Voice disconnected');
            this.emit('voice:disconnected');
        };

        this.voiceWs.onerror = (err) => {
            console.error('[WS] Voice error:', err);
            this.emit('voice:error', err);
        };
    }

    sendChat(message, includeScreen = true) {
        if (this.chatWs?.readyState === WebSocket.OPEN) {
            this.chatWs.send(JSON.stringify({
                message,
                include_screen: includeScreen,
            }));
        }
    }

    disconnectVoice(reason = '') {
        if (this.voiceWs) {
            this.voiceWs.close();
            this.voiceWs = null;
            if (reason) console.log(`[WS] Voice closed: ${reason}`);
        }
    }

    isVoiceConnected() {
        return this.voiceWs?.readyState === WebSocket.OPEN;
    }

    sendVoiceControl(payload) {
        if (this.voiceWs?.readyState === WebSocket.OPEN) {
            this.voiceWs.send(JSON.stringify(payload));
            return true;
        }
        return false;
    }

    sendVoiceBinary(buffer) {
        if (this.voiceWs?.readyState === WebSocket.OPEN) {
            this.voiceWs.send(buffer);
            return true;
        }
        return false;
    }

    // Legacy compatibility — routes through sendVoiceControl
    sendVoiceAudio(audioBase64, format = 'webm') {
        return this.sendVoiceControl({
            type: 'audio',
            audio: audioBase64,
            format: format,
        });
    }

    disconnect() {
        [this.chatWs, this.screenWs, this.voiceWs].forEach(ws => {
            if (ws) ws.close();
        });
    }
}

// Global instance
window.voxWs = new VoxWebSocket();
