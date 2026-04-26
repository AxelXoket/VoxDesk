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
        this.reconnectDelay = 3000;
        this.callbacks = {};
    }

    on(event, callback) {
        if (!this.callbacks[event]) this.callbacks[event] = [];
        this.callbacks[event].push(callback);
    }

    emit(event, data) {
        (this.callbacks[event] || []).forEach(cb => cb(data));
    }

    connectChat() {
        if (this.chatWs?.readyState === WebSocket.OPEN) return;

        this.chatWs = new WebSocket(`${this.baseUrl}/api/ws/chat`);

        this.chatWs.onopen = () => {
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
            setTimeout(() => this.connectChat(), this.reconnectDelay);
        };

        this.chatWs.onerror = (err) => {
            console.error('[WS] Chat error:', err);
        };
    }

    connectScreen() {
        if (this.screenWs?.readyState === WebSocket.OPEN) return;

        this.screenWs = new WebSocket(`${this.baseUrl}/api/ws/screen`);

        this.screenWs.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.emit('screen:frame', data);
            } catch (e) { /* ignore */ }
        };

        this.screenWs.onclose = () => {
            setTimeout(() => this.connectScreen(), this.reconnectDelay);
        };
    }

    connectVoice() {
        if (this.voiceWs?.readyState === WebSocket.OPEN) return;

        this.voiceWs = new WebSocket(`${this.baseUrl}/api/ws/voice`);

        this.voiceWs.onopen = () => {
            this.emit('voice:connected');
        };

        this.voiceWs.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.emit('voice:message', data);
            } catch (e) { /* ignore */ }
        };

        this.voiceWs.onclose = () => {
            this.emit('voice:disconnected');
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

    sendVoiceAudio(audioBase64, format = 'webm') {
        if (this.voiceWs?.readyState === WebSocket.OPEN) {
            this.voiceWs.send(JSON.stringify({
                type: 'audio',
                audio: audioBase64,
                format: format,
            }));
        }
    }

    disconnect() {
        [this.chatWs, this.screenWs, this.voiceWs].forEach(ws => {
            if (ws) ws.close();
        });
    }
}

// Global instance
window.voxWs = new VoxWebSocket();
