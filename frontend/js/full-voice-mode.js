/**
 * VoxDesk — Full Voice Mode
 * Sprint 7 : Dedicated voice-only conversation mode.
 *
 * State machine : idle → listening → user_speaking → silence_countdown
 *                 → processing → ai_speaking → listening (loop)
 *
 * Silence detection tamamen frontend'de, AudioWorklet RMS level ile.
 * WebSocket session turn'ler arasında açık kalır.
 * AI speaking sırasında mic capture duraklatılır (echo önlemi).
 * Normal dictation mode (#btnMic) ile birleştirilmez.
 *
 * Güvenlik :
 *   - External URL yok, tüm iletişim localhost
 *   - Audio data disk'e yazılmaz
 */

// ── Constants ───────────────────────────────────────────────
const FVM_SILENCE_RMS_THRESHOLD = 0.01;
const FVM_SILENCE_DURATION_MS = 3000;
const FVM_ERROR_RECOVERY_MS = 2000;
const FVM_PROCESSING_TIMEOUT_MS = 30000;  // Sprint 7.2: hard timeout for stuck processing
const FVM_LLM_TTS_GRACE_MS = 5000;       // Sprint 7.2: wait for tts_audio after llm_response
const FVM_BAR_COUNT = 12;

const FVM_STATES = {
    IDLE: 'idle',
    LISTENING: 'listening',
    USER_SPEAKING: 'user_speaking',
    SILENCE_COUNTDOWN: 'silence_countdown',
    PROCESSING: 'processing',
    AI_SPEAKING: 'ai_speaking',
    ERROR: 'error',
};

const FVM_STATE_LABELS = {
    idle: '',
    listening: 'Dinliyorum...',
    user_speaking: 'Konuşuyor...',
    silence_countdown: 'Sessizlik algılandı...',
    processing: 'İşleniyor...',
    ai_speaking: 'Yanıt veriliyor...',
    error: '⚠️ Hata',
};


class FullVoiceMode {
    constructor() {
        // DOM
        this._overlay = document.getElementById('fvmOverlay');
        this._statusEl = document.getElementById('fvmStatus');
        this._waveformEl = document.getElementById('fvmWaveform');
        this._closeBtn = document.getElementById('fvmClose');
        this._sidebarToggle = document.getElementById('fullVoiceToggle');

        // State
        this._state = FVM_STATES.IDLE;
        this._isActive = false;
        this._hasSpokeYet = false;
        this._silenceTimer = null;
        this._errorTimer = null;
        this._processingTimer = null;   // Sprint 7.2: hard timeout
        this._llmTtsGraceTimer = null;  // Sprint 7.2: llm→tts grace
        this._currentRms = 0;
        this._animFrameId = null;

        // Audio
        this._audioCapture = null;

        // Waveform bars — created once
        this._bars = [];

        this._init();
    }

    get isActive() {
        return this._isActive;
    }

    // ── Init ─────────────────────────────────────────────────

    _init() {
        // Create waveform bars
        if (this._waveformEl) {
            this._waveformEl.innerHTML = '';
            for (let i = 0; i < FVM_BAR_COUNT; i++) {
                const bar = document.createElement('div');
                bar.className = 'fvm-bar';
                this._waveformEl.appendChild(bar);
                this._bars.push(bar);
            }
        }

        // Close button
        if (this._closeBtn) {
            this._closeBtn.addEventListener('click', () => this.deactivate());
        }

        // Sidebar toggle
        if (this._sidebarToggle) {
            this._sidebarToggle.addEventListener('change', () => {
                if (this._sidebarToggle.checked) {
                    this.activate();
                } else {
                    this.deactivate();
                }
            });
        }
    }

    // ── Activate / Deactivate ────────────────────────────────

    async activate() {
        if (this._isActive) return;
        this._isActive = true;

        // Show overlay, hide normal chat input
        if (this._overlay) this._overlay.style.display = 'flex';
        const chatInputContainer = document.querySelector('.input-container');
        const chatHints = document.querySelector('.input-hints');
        if (chatInputContainer) chatInputContainer.style.display = 'none';
        if (chatHints) chatHints.style.display = 'none';

        // Sync sidebar toggle
        if (this._sidebarToggle && !this._sidebarToggle.checked) {
            this._sidebarToggle.checked = true;
        }

        // Start listening
        await this._startListening();
    }

    deactivate() {
        if (!this._isActive) return;
        this._isActive = false;

        // Stop everything
        this._stopListening();
        this._clearTimers();
        this._stopAnimation();

        // Sprint 7.1: Flush FVM TTS queue + stop active audio so no stale
        // callbacks carry over to the next activation or dictation session.
        window._fvmTtsQueue = [];
        window._fvmTtsPlaying = false;
        if (typeof window.voxStopAudio === 'function') {
            window.voxStopAudio();
        }

        // Hide overlay, restore chat input
        if (this._overlay) this._overlay.style.display = 'none';
        const chatInputContainer = document.querySelector('.input-container');
        const chatHints = document.querySelector('.input-hints');
        if (chatInputContainer) chatInputContainer.style.display = '';
        if (chatHints) chatHints.style.display = '';

        // Sync sidebar toggle
        if (this._sidebarToggle && this._sidebarToggle.checked) {
            this._sidebarToggle.checked = false;
        }

        this._setState(FVM_STATES.IDLE);
    }

    // ── State Machine ────────────────────────────────────────

    _setState(newState) {
        this._state = newState;
        if (this._overlay) {
            this._overlay.setAttribute('data-state', newState);
        }
        if (this._statusEl) {
            this._statusEl.textContent = FVM_STATE_LABELS[newState] || '';
        }
    }

    // ── Listening Lifecycle ──────────────────────────────────

    async _startListening() {
        this._hasSpokeYet = false;
        this._clearTimers();

        // Ensure voice WS is connected
        if (!window.voxWs.isVoiceConnected()) {
            window.voxWs.connectVoice();
            await new Promise(r => setTimeout(r, 500));
            if (!window.voxWs.isVoiceConnected()) {
                this._handleError('Ses bağlantısı kurulamadı');
                return;
            }
        }

        // Create AudioCapture with FVM's own transport
        const transport = {
            sendControl: (payload) => window.voxWs.sendVoiceControl(payload),
            sendBinary: (buffer) => window.voxWs.sendVoiceBinary(buffer),
            isOpen: () => window.voxWs.isVoiceConnected(),
        };

        const useBinary = true; // FVM always uses binary/worklet path
        this._audioCapture = new AudioCapture(transport, { useBinary });

        // RMS callback — silence detection + waveform
        this._audioCapture.onLevelUpdate = (rms) => this._onRmsUpdate(rms);

        try {
            await this._audioCapture.start();
        } catch (e) {
            this._handleError(`Mikrofon erişimi reddedildi: ${e.message}`);
            return;
        }

        this._setState(FVM_STATES.LISTENING);
        this._startAnimation();
    }

    _stopListening() {
        if (this._audioCapture && this._audioCapture.isRecording) {
            this._audioCapture.stop();
        }
        this._audioCapture = null;
    }

    // ── RMS Update (Silence Detection Core) ──────────────────

    _onRmsUpdate(rms) {
        this._currentRms = rms;

        // Ignore RMS during non-listening states
        if (this._state === FVM_STATES.AI_SPEAKING ||
            this._state === FVM_STATES.PROCESSING ||
            this._state === FVM_STATES.ERROR ||
            this._state === FVM_STATES.IDLE) {
            return;
        }

        const isSpeaking = rms > FVM_SILENCE_RMS_THRESHOLD;

        if (isSpeaking) {
            this._hasSpokeYet = true;
            this._clearSilenceTimer();

            if (this._state !== FVM_STATES.USER_SPEAKING) {
                this._setState(FVM_STATES.USER_SPEAKING);
            }
        } else if (this._hasSpokeYet) {
            // Silence detected after speech
            if (this._state === FVM_STATES.USER_SPEAKING) {
                this._setState(FVM_STATES.SILENCE_COUNTDOWN);
                this._startSilenceTimer();
            }
            // If already in SILENCE_COUNTDOWN, timer is running
        }
        // If !hasSpokeYet && !isSpeaking → stay in LISTENING, no timer
    }

    // ── Silence Timer ────────────────────────────────────────

    _startSilenceTimer() {
        this._clearSilenceTimer();
        this._silenceTimer = setTimeout(() => {
            this._closeTurn();
        }, FVM_SILENCE_DURATION_MS);
    }

    _clearSilenceTimer() {
        if (this._silenceTimer) {
            clearTimeout(this._silenceTimer);
            this._silenceTimer = null;
        }
    }

    // ── Turn Close ───────────────────────────────────────────

    _closeTurn() {
        this._clearSilenceTimer();

        // Play beep to signal turn end
        this._playBeep();

        // Stop recording — this sends audio_end to backend
        this._stopListening();

        this._setState(FVM_STATES.PROCESSING);

        // Sprint 7.2: Hard processing timeout — if nothing arrives, recover
        this._clearProcessingTimer();
        this._processingTimer = setTimeout(() => {
            if (this._isActive && this._state === FVM_STATES.PROCESSING) {
                console.warn('[FVM] Processing timeout — recovering');
                this._handleError('İşlem zaman aşımına uğradı');
            }
        }, FVM_PROCESSING_TIMEOUT_MS);
    }

    // ── Voice WS Message Handler ─────────────────────────────

    handleVoiceMessage(data) {
        if (!this._isActive) return false; // Not handled by FVM

        // Route ACK/error to AudioCapture
        if (this._audioCapture) {
            this._audioCapture.handleMessage(data);
        }

        switch (data.type) {
            case 'stt_result':
                window.VoxChat.addMessage('user', data.text);
                break;

            case 'stt_empty':
                // No speech detected — go back to listening
                this._clearProcessingTimer();
                this._clearLlmTtsGraceTimer();
                if (this._state === FVM_STATES.PROCESSING) {
                    this._restartListening();
                }
                break;

            case 'llm_response':
                window.VoxChat.addMessage('assistant', data.text);
                // Sprint 7.2: Start grace timer — if no tts_audio within
                // FVM_LLM_TTS_GRACE_MS, return to listening (TTS may be
                // disabled, unavailable, or backend chose not to send audio).
                this._clearLlmTtsGraceTimer();
                this._llmTtsGraceTimer = setTimeout(() => {
                    if (this._isActive && this._state === FVM_STATES.PROCESSING) {
                        console.info('[FVM] No TTS audio after LLM response — returning to listening');
                        this._clearProcessingTimer();
                        this._restartListening();
                    }
                }, FVM_LLM_TTS_GRACE_MS);
                break;

            case 'tts_audio':
                // Sprint 7.2: TTS arrived — cancel grace + processing timers
                this._clearProcessingTimer();
                this._clearLlmTtsGraceTimer();
                this._setState(FVM_STATES.AI_SPEAKING);
                // Queue through global TTS queue — uses shared playAudio()
                if (window._fvmTtsQueue) {
                    window._fvmTtsQueue.push(data.audio);
                    if (!window._fvmTtsPlaying) this._playNextFvmTts();
                }
                break;

            case 'voice_error':
                this._clearProcessingTimer();
                this._clearLlmTtsGraceTimer();
                this._handleError(data.message || 'Voice error occurred');
                break;

            case 'audio_config_ack':
            case 'protocol_error':
                // Already routed to AudioCapture above
                break;
        }

        return true; // Handled by FVM
    }

    // ── TTS Playback (FVM-owned queue) ───────────────────────

    _playNextFvmTts() {
        if (!window._fvmTtsQueue || window._fvmTtsQueue.length === 0) {
            window._fvmTtsPlaying = false;
            // TTS finished — return to listening
            if (this._isActive && this._state === FVM_STATES.AI_SPEAKING) {
                this._restartListening();
            }
            return;
        }

        window._fvmTtsPlaying = true;
        const b64 = window._fvmTtsQueue.shift();

        // Use shared playAudio — handles activeAudio conflict management
        if (typeof window.playAudioFromBase64 === 'function') {
            window.playAudioFromBase64(b64, () => this._playNextFvmTts());
        }
    }

    async _restartListening() {
        // Small delay to avoid immediate mic capture after TTS
        await new Promise(r => setTimeout(r, 300));
        if (this._isActive) {
            await this._startListening();
        }
    }

    // ── Error Handling ───────────────────────────────────────

    _handleError(message) {
        this._stopListening();
        this._clearTimers();

        this._setState(FVM_STATES.ERROR);
        if (this._statusEl) {
            this._statusEl.textContent = `⚠️ ${message}`;
        }

        window.VoxChat.addMessage('assistant', `⚠️ ${message}`);

        // Auto-recover after delay
        this._errorTimer = setTimeout(() => {
            if (this._isActive) {
                this._restartListening();
            }
        }, FVM_ERROR_RECOVERY_MS);
    }

    // ── Beep (Turn-End Signal) ────────────────────────────────

    _playBeep() {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.frequency.value = 880;
            gain.gain.value = 0.15;
            osc.start();
            osc.stop(ctx.currentTime + 0.08);
            // Cleanup
            setTimeout(() => ctx.close().catch(() => {}), 200);
        } catch (e) {
            // Beep is non-critical
            console.warn('[FVM] Beep failed:', e);
        }
    }

    // ── Waveform Animation ───────────────────────────────────

    _startAnimation() {
        if (this._animFrameId) return;
        const animate = () => {
            this._updateBars();
            this._animFrameId = requestAnimationFrame(animate);
        };
        this._animFrameId = requestAnimationFrame(animate);
    }

    _stopAnimation() {
        if (this._animFrameId) {
            cancelAnimationFrame(this._animFrameId);
            this._animFrameId = null;
        }
        // Reset bars to flat
        this._bars.forEach(bar => {
            bar.style.height = '4px';
        });
    }

    _updateBars() {
        const rms = this._currentRms;
        const isActive = rms > FVM_SILENCE_RMS_THRESHOLD;
        const center = (FVM_BAR_COUNT - 1) / 2;

        for (let i = 0; i < this._bars.length; i++) {
            // Sinusoidal modulation — center bars taller
            const distFromCenter = Math.abs(i - center) / center;
            const sinMod = Math.cos(distFromCenter * Math.PI * 0.5);

            let height;
            if (isActive) {
                // Scale RMS (0-0.5 typical range) to pixel height
                const scaled = Math.min(rms * 200, 60); // max 60px
                // Add slight randomness for organic feel
                const rand = 0.8 + Math.random() * 0.4;
                height = Math.max(4, scaled * sinMod * rand);
            } else {
                height = 4; // Flat line when silent
            }

            this._bars[i].style.height = `${height}px`;
        }
    }

    // ── Cleanup ──────────────────────────────────────────────

    _clearProcessingTimer() {
        if (this._processingTimer) {
            clearTimeout(this._processingTimer);
            this._processingTimer = null;
        }
    }

    _clearLlmTtsGraceTimer() {
        if (this._llmTtsGraceTimer) {
            clearTimeout(this._llmTtsGraceTimer);
            this._llmTtsGraceTimer = null;
        }
    }

    _clearTimers() {
        this._clearSilenceTimer();
        this._clearProcessingTimer();
        this._clearLlmTtsGraceTimer();
        if (this._errorTimer) {
            clearTimeout(this._errorTimer);
            this._errorTimer = null;
        }
    }
}

// Global init — will be wired by app.js
if (typeof window !== 'undefined') {
    window.FullVoiceMode = FullVoiceMode;
    // FVM TTS queue (separate from dictation TTS queue)
    window._fvmTtsQueue = [];
    window._fvmTtsPlaying = false;
}
