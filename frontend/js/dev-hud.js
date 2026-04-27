/**
 * VoxDesk — Developer HUD
 * Minimal overlay — WS durumları, model durumları, son hata.
 * Toggle: Ctrl+Shift+D
 */

class DevHud {
    constructor() {
        this._el = document.getElementById('devHud');
        this._visible = false;
        this._pollTimer = null;

        // Keyboard toggle
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.shiftKey && e.key === 'D') {
                e.preventDefault();
                this.toggle();
            }
        });
    }

    toggle() {
        this._visible = !this._visible;
        if (this._el) {
            this._el.style.display = this._visible ? 'block' : 'none';
        }
        if (this._visible) {
            this._update();
            this._pollTimer = setInterval(() => this._update(), 5000);
        } else if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
    }

    _wsStateIcon(ws) {
        if (!ws) return '⚫ NULL';
        switch (ws.readyState) {
            case WebSocket.CONNECTING: return '🟡 CONNECTING';
            case WebSocket.OPEN:       return '🟢 OPEN';
            case WebSocket.CLOSING:    return '🟠 CLOSING';
            case WebSocket.CLOSED:     return '⚫ CLOSED';
            default:                   return '❓ UNKNOWN';
        }
    }

    async _update() {
        if (!this._el) return;

        // Client-side WS states
        const chatState = this._wsStateIcon(window.voxWs?.chatWs);
        const screenState = this._wsStateIcon(window.voxWs?.screenWs);
        const voiceState = this._wsStateIcon(window.voxWs?.voiceWs);

        // Server-side status
        let apiState = '❌ DOWN';
        let sttState = '—';
        let llmState = '—';
        let ttsState = '—';
        let lastError = '—';

        try {
            const res = await fetch('/api/status');
            if (res.ok) {
                const data = await res.json();
                apiState = data.api?.status === 'ok' ? '✅ OK' : '⚠️ ' + (data.api?.status || 'unknown');
                sttState = data.models?.stt?.state || '—';
                llmState = data.models?.llm?.state || '—';
                ttsState = data.models?.tts?.state || '—';
                if (data.last_error) {
                    lastError = data.last_error.substring(0, 60);
                }
            }
        } catch (e) {
            apiState = '❌ UNREACHABLE';
        }

        this._el.innerHTML = `
            <div class="dev-hud-title">DEV HUD</div>
            <div class="dev-hud-row"><span>API</span><span>${apiState}</span></div>
            <div class="dev-hud-row"><span>Chat</span><span>${chatState}</span></div>
            <div class="dev-hud-row"><span>Screen</span><span>${screenState}</span></div>
            <div class="dev-hud-row"><span>Voice</span><span>${voiceState}</span></div>
            <div class="dev-hud-divider"></div>
            <div class="dev-hud-row"><span>STT</span><span>${sttState}</span></div>
            <div class="dev-hud-row"><span>LLM</span><span>${llmState}</span></div>
            <div class="dev-hud-row"><span>TTS</span><span>${ttsState}</span></div>
            <div class="dev-hud-divider"></div>
            <div class="dev-hud-row dev-hud-error"><span>Error</span><span>${lastError}</span></div>
            <div class="dev-hud-hint">Ctrl+Shift+D to close</div>
        `;
    }
}

// Auto-init
window.VoxDevHud = new DevHud();
