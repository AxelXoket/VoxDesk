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
            window.voxWs.connectVoice();
        }
    });

    // Mic button — Push-to-talk
    const micBtn = document.getElementById('btnMic');
    let isRecording = false;
    let mediaRecorder = null;
    let audioChunks = [];

    micBtn.addEventListener('mousedown', async () => {
        if (isRecording) return;
        isRecording = true;
        micBtn.classList.add('recording');
        audioChunks = [];

        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });

            mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) audioChunks.push(e.data);
            };

            mediaRecorder.onstop = async () => {
                const blob = new Blob(audioChunks, { type: 'audio/webm' });
                const arrayBuf = await blob.arrayBuffer();
                // btoa large blob'larda çöker — chunk'lı encode
                const base64 = arrayBufferToBase64(arrayBuf);

                // WS voice endpoint'e format bilgisi ile gönder
                window.voxWs.sendVoiceAudio(base64, 'webm');

                // Stream'i kapat
                stream.getTracks().forEach(t => t.stop());
            };

            mediaRecorder.start();
        } catch (e) {
            console.error('Mikrofon hatası:', e);
            isRecording = false;
            micBtn.classList.remove('recording');
        }
    });

    micBtn.addEventListener('mouseup', () => {
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
        }
        isRecording = false;
        micBtn.classList.remove('recording');
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
        if (data.type === 'stt_result') {
            window.VoxChat.addMessage('user', `🎤 ${data.text}`);
        } else if (data.type === 'llm_response') {
            window.VoxChat.addMessage('assistant', data.text);
        } else if (data.type === 'tts_audio') {
            ttsQueue.push(data.audio);
            if (!ttsPlaying) playNextTTS();
        }
    });

    // Settings panel toggle
    const settingsBtn = document.getElementById('btnSettings');
    const settingsPanel = document.getElementById('settingsPanel');
    settingsBtn.addEventListener('click', () => {
        settingsPanel.style.display =
            settingsPanel.style.display === 'none' ? 'block' : 'none';
    });

    console.log('✅ VoxDesk UI hazır!');
});

async function checkHealth() {
    try {
        const res = await fetch('/api/health');
        const data = await res.json();

        const statusEl = document.getElementById('statusText');
        const dotEl = document.getElementById('captureDot');

        if (data.status === 'ok') {
            statusEl.textContent = `Aktif — ${data.model.split('/').pop()}`;
            if (data.capture_running) dotEl.classList.add('active');
        }
    } catch (e) {
        document.getElementById('statusText').textContent = 'Bağlantı bekleniyor...';
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
        audio.play();
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
