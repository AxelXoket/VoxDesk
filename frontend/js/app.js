/**
 * VoxDesk — Main Application
 * Tüm bileşenleri başlatır ve bağlar.
 */

document.addEventListener('DOMContentLoaded', () => {
    console.log('🌐 VoxDesk UI starting...');

    // Initialize components
    window.VoxChat = new VoxChat();
    window.VoxSettings = new VoxSettings();
    window.VoxScreenPreview = new VoxScreenPreview();

    // Connect WebSockets
    window.voxWs.connectChat();
    window.voxWs.connectScreen();

    // Health check
    checkHealth();
    setInterval(checkHealth, 30000);

    // Sprint 7: Full Voice Mode — initialize
    let voxFullVoice = null;
    if (window.FullVoiceMode) {
        voxFullVoice = new FullVoiceMode();
        window.VoxFullVoice = voxFullVoice;
    }

    // Voice mode button — now toggles Full Voice Mode
    const voiceModeBtn = document.getElementById('btnVoiceMode');

    voiceModeBtn.addEventListener('click', () => {
        // Sprint 7: If FVM is available, use it instead of legacy indicator
        if (voxFullVoice) {
            if (voxFullVoice.isActive) {
                voxFullVoice.deactivate();
                voiceModeBtn.style.background = 'var(--glass-bg)';
            } else {
                voxFullVoice.activate();
                voiceModeBtn.style.background = 'rgba(0, 245, 255, 0.15)';
            }
            return;
        }

        // Legacy fallback (no FVM) — Sprint 7.1: simplified, voiceModeActive removed
        const voiceIndicator = document.getElementById('voiceIndicator');
        const nowActive = voiceIndicator && voiceIndicator.style.display !== 'flex';
        if (voiceIndicator) voiceIndicator.style.display = nowActive ? 'flex' : 'none';
        voiceModeBtn.style.background = nowActive
            ? 'rgba(0, 245, 255, 0.15)'
            : 'var(--glass-bg)';

        if (nowActive) {
            const features = _cachedFeatures;
            if (features && !features.enable_binary_audio && !features.enable_mediarecorder_fallback) {
                console.warn('[App] Voice disabled by config');
                window.VoxChat.addMessage('assistant', '⚠️ Voice is currently disabled in configuration.');
                if (voiceIndicator) voiceIndicator.style.display = 'none';
                voiceModeBtn.style.background = 'var(--glass-bg)';
                return;
            }
            window.voxWs.connectVoice();
        }
    });

    // Mic button — Click toggle recording (click to start, click to stop)
    const micBtn = document.getElementById('btnMic');
    let audioCapture = null;
    let silenceTimer = null;

    async function startRecording() {
        // Ensure voice WS is connected
        if (!window.voxWs.isVoiceConnected()) {
            window.voxWs.connectVoice();
            await new Promise(r => setTimeout(r, 500));
            if (!window.voxWs.isVoiceConnected()) {
                console.error('[App] Voice WS not connected');
                window.VoxChat.addMessage('assistant', '⚠️ Ses bağlantısı kurulamadı. Tekrar deneyin.');
                return;
            }
        }

        micBtn.classList.add('recording');

        try {
            const transport = {
                sendControl: (payload) => window.voxWs.sendVoiceControl(payload),
                sendBinary: (buffer) => window.voxWs.sendVoiceBinary(buffer),
                isOpen: () => window.voxWs.isVoiceConnected(),
            };
            const useBinary = _cachedFeatures != null
                ? _cachedFeatures.enable_binary_audio !== false
                : true;  // Default to binary if features not yet loaded
            audioCapture = new AudioCapture(transport, { useBinary });
            await audioCapture.start();

            // 5-second silence warning — only if mic failed silently
            silenceTimer = setTimeout(() => {
                if (audioCapture && audioCapture.isRecording && !audioCapture._mode) {
                    window.VoxChat.addMessage('assistant', '⚠️ Mikrofon başlatılamadı. Tarayıcı izinlerini kontrol edin.');
                }
            }, 5000);

        } catch (e) {
            console.error('Mikrofon hatası:', e);
            window.VoxChat.addMessage('assistant', `⚠️ Mikrofon erişimi reddedildi: ${e.message}`);
            micBtn.classList.remove('recording');
            audioCapture = null;
        }
    }

    function stopRecording() {
        if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null; }
        if (audioCapture && audioCapture.isRecording) {
            audioCapture.stop();
        }
        micBtn.classList.remove('recording');
    }

    micBtn.addEventListener('click', async () => {
        // Sprint 7.1: Block dictation while Full Voice Mode is active
        if (voxFullVoice && voxFullVoice.isActive) {
            console.warn('[App] Dictation blocked — Full Voice Mode is active');
            return;
        }
        if (audioCapture && audioCapture.isRecording) {
            stopRecording();
        } else {
            await startRecording();
        }
    });

    // Voice WS events — TTS audio queue (chunk'lar sıralı çalınır)
    const ttsQueue = [];
    let ttsPlaying = false;

    function playNextTTS() {
        if (ttsQueue.length === 0) { ttsPlaying = false; return; }
        ttsPlaying = true;
        const b64 = ttsQueue.shift();
        playAudio(b64, () => playNextTTS());
    }

    window.voxWs.on('voice:message', (data) => {
        // Sprint 7: FVM active → FVM handles all voice messages
        if (voxFullVoice && voxFullVoice.isActive) {
            voxFullVoice.handleVoiceMessage(data);
            return;
        }

        // Sprint 2: Route ACK/error to AudioCapture (dictation mode)
        if (audioCapture) {
            audioCapture.handleMessage(data);
        }

        if (data.type === 'stt_result') {
            window.VoxChat.addMessage('user', data.text);
        } else if (data.type === 'llm_response') {
            window.VoxChat.addMessage('assistant', data.text);
        } else if (data.type === 'tts_audio') {
            ttsQueue.push(data.audio);
            if (!ttsPlaying) playNextTTS();
        } else if (data.type === 'voice_error') {
            window.VoxChat.addMessage('assistant', `⚠️ ${data.message || 'Voice error occurred'}`);
        }
    });

    // Sprint 3.5: Voice close/error cleanup — stop AudioCapture safely
    function _cleanupVoiceCapture(reason) {
        console.log(`[App] Voice cleanup: ${reason}`);
        if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null; }
        if (audioCapture && audioCapture.isRecording) {
            audioCapture.stop();
        }
        audioCapture = null;
        micBtn.classList.remove('recording');
        ttsQueue.length = 0;
        ttsPlaying = false;
    }

    window.voxWs.on('voice:disconnected', () => _cleanupVoiceCapture('disconnected'));
    window.voxWs.on('voice:error', (err) => _cleanupVoiceCapture(`error: ${err}`));

    // Settings panel toggle
    const settingsBtn = document.getElementById('btnSettings');
    const settingsPanel = document.getElementById('settingsPanel');
    settingsBtn.addEventListener('click', () => {
        settingsPanel.style.display =
            settingsPanel.style.display === 'none' ? 'block' : 'none';
    });

    // Sprint 7: Read-aloud event handler
    window.addEventListener('readAloud', async (e) => {
        const { text, button } = e.detail || {};
        if (!text) return;

        // Visual feedback
        if (button) button.classList.add('playing');

        try {
            const res = await fetch('/api/tts/read', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text }),
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                console.warn('[ReadAloud] Error:', err.error || res.status);
                // Sprint 7.2: User-visible feedback when TTS unavailable
                if (res.status === 503) {
                    window.VoxChat?.addMessage('assistant', '⚠️ Sesli okuma şu an kullanılamıyor (TTS yüklenmedi).');
                }
                if (button) button.classList.remove('playing');
                return;
            }

            const blob = await res.blob();
            const url = URL.createObjectURL(blob);

            // Sprint 7.1: Stop active audio + reset both queues so no stale callbacks remain
            voxStopAudio();
            resetTtsPlayback(ttsQueue);

            const audio = new Audio(url);
            activeAudio = audio;
            audio.play().catch(err => {
                console.warn('[ReadAloud] Autoplay blocked:', err);
                URL.revokeObjectURL(url);
                activeAudio = null;
                if (button) button.classList.remove('playing');
            });
            audio.onended = () => {
                URL.revokeObjectURL(url);
                activeAudio = null;
                if (button) button.classList.remove('playing');
            };
        } catch (e) {
            console.error('[ReadAloud] Fetch error:', e);
            if (button) button.classList.remove('playing');
        }
    });

    console.log('✅ VoxDesk UI hazır!');
});

// Sprint 3.5: Feature flags cache from /api/status
let _cachedFeatures = null;

async function checkHealth() {
    const statusEl = document.getElementById('statusText');
    const dotEl = document.getElementById('captureDot');

    try {
        const healthRes = await fetch('/api/health');
        const health = await healthRes.json();

        if (health.status !== 'ok') {
            statusEl.textContent = 'Backend degraded';
            dotEl.classList.remove('active');
            return;
        }

        try {
            const statusRes = await fetch('/api/status');
            const status = await statusRes.json();

            const modelName = status?.models?.llm?.name || 'runtime ready';
            statusEl.textContent = `Aktif — ${String(modelName).split('/').pop()}`;

            // Sprint 3.5: Cache feature flags for voice mode decisions
            _cachedFeatures = status?.features || null;

            if (status?.capture?.running) {
                dotEl.classList.add('active');
            } else {
                dotEl.classList.remove('active');
            }
        } catch (statusError) {
            statusEl.textContent = 'Backend active — runtime status unavailable';
            dotEl.classList.remove('active');
        }
    } catch (e) {
        statusEl.textContent = 'Bağlantı bekleniyor...';
        dotEl.classList.remove('active');
    }
}

// Sprint 7: Global active audio reference — prevents TTS/read-aloud conflicts
let activeAudio = null;

/**
 * Sprint 7.1: Stop currently playing audio without triggering stale onended
 * callbacks.  Always call this before starting a new Audio() so queued
 * `playNextTTS` / FVM chain functions are not re-invoked for interrupted audio.
 */
function voxStopAudio() {
    if (activeAudio) {
        activeAudio.onended = null; // nullify before pause — prevents stale callback
        activeAudio.pause();
        activeAudio = null;
    }
}

/**
 * Sprint 7.1: Drain a TTS queue array and reset its playing flag.
 * Pass the queue array that owns the audio that was interrupted.
 * @param {Array} queue  - the ttsQueue array to drain
 */
function resetTtsPlayback(queue) {
    if (Array.isArray(queue)) queue.length = 0;
    // FVM queue is global — also clear it so next FVM activation starts clean
    if (window._fvmTtsQueue) window._fvmTtsQueue.length = 0;
    window._fvmTtsPlaying = false;
}

// Expose helpers globally so FVM deactivate can call them without a closure
window.voxStopAudio = voxStopAudio;
window.resetTtsPlayback = resetTtsPlayback;

function playAudio(base64Audio, onEnded) {
    try {
        // Sprint 7.1: Stop previous audio + nullify stale onended before starting new
        voxStopAudio();

        const audioData = atob(base64Audio);
        const arrayBuf = new ArrayBuffer(audioData.length);
        const view = new Uint8Array(arrayBuf);
        for (let i = 0; i < audioData.length; i++) {
            view[i] = audioData.charCodeAt(i);
        }

        const blob = new Blob([arrayBuf], { type: 'audio/wav' });
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        activeAudio = audio;
        audio.play().catch(err => {
            console.warn('Audio autoplay blocked:', err);
            URL.revokeObjectURL(url);
            activeAudio = null;
            if (onEnded) onEnded();
        });
        audio.onended = () => {
            URL.revokeObjectURL(url);
            activeAudio = null;
            if (onEnded) onEnded();
        };
    } catch (e) {
        console.error('Audio çalma hatası:', e);
        activeAudio = null;
        if (onEnded) onEnded();
    }
}

// Sprint 7: Global alias for FVM TTS queue
window.playAudioFromBase64 = playAudio;

// Büyük ArrayBuffer'ları güvenli base64'e çevir (btoa 2MB+ crash'leri önler)
function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    const chunkSize = 8192;
    let binary = '';
    for (let i = 0; i < bytes.length; i += chunkSize) {
        const chunk = bytes.subarray(i, i + chunkSize);
        binary += String.fromCharCode.apply(null, chunk);
    }
    return btoa(binary);
}
