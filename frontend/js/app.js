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

    // Voice mode button
    const voiceModeBtn = document.getElementById('btnVoiceMode');
    const voiceIndicator = document.getElementById('voiceIndicator');
    let voiceModeActive = false;

    voiceModeBtn.addEventListener('click', () => {
        voiceModeActive = !voiceModeActive;
        voiceIndicator.style.display = voiceModeActive ? 'flex' : 'none';
        voiceModeBtn.style.background = voiceModeActive
            ? 'rgba(0, 245, 255, 0.15)'
            : 'var(--glass-bg)';

        if (voiceModeActive) {
            // Sprint 3.5: Feature flag check before connecting voice
            const features = _cachedFeatures;
            if (features && !features.enable_binary_audio && !features.enable_mediarecorder_fallback) {
                console.warn('[App] Voice disabled by config');
                window.VoxChat.addMessage('assistant', '⚠️ Voice is currently disabled in configuration.');
                voiceModeActive = false;
                voiceIndicator.style.display = 'none';
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
        // Sprint 2: Route ACK/error to AudioCapture
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

function playAudio(base64Audio, onEnded) {
    try {
        const audioData = atob(base64Audio);
        const arrayBuf = new ArrayBuffer(audioData.length);
        const view = new Uint8Array(arrayBuf);
        for (let i = 0; i < audioData.length; i++) {
            view[i] = audioData.charCodeAt(i);
        }

        const blob = new Blob([arrayBuf], { type: 'audio/wav' });
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audio.play().catch(err => {
            console.warn('Audio autoplay blocked:', err);
            URL.revokeObjectURL(url);
            if (onEnded) onEnded();
        });
        audio.onended = () => {
            URL.revokeObjectURL(url);
            if (onEnded) onEnded();
        };
    } catch (e) {
        console.error('Audio çalma hatası:', e);
        if (onEnded) onEnded();
    }
}

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
