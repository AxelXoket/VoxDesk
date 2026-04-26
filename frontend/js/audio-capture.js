/**
 * VoxDesk — Audio Capture Client
 * AudioWorklet + binary WebSocket transfer.
 * MediaRecorder fallback AudioWorklet desteklenmediyse.
 *
 * Kullanım:
 *   const capture = new AudioCapture(ws);
 *   await capture.start();
 *   capture.stop();
 *
 * Güvenlik:
 *   - WebSocket URL sadece localhost/127.0.0.1
 *   - External URL/fetch YOK
 *   - Audio data disk'e yazılmaz
 */

// ══════════════════════════════════════════════════════════════
//  Resampler — 48kHz/44.1kHz → 16kHz
// ══════════════════════════════════════════════════════════════

/**
 * Basit linear-interpolation downsampler.
 * Web Audio API sample rate (genellikle 48000 veya 44100) → 16000 Hz.
 *
 * @param {Int16Array} pcmData - Kaynak PCM data
 * @param {number} fromRate - Kaynak sample rate
 * @param {number} toRate - Hedef sample rate (16000)
 * @returns {Int16Array} Resampled PCM data
 */
function resample(pcmData, fromRate, toRate) {
    if (fromRate === toRate) return pcmData;

    const ratio = fromRate / toRate;
    const newLength = Math.round(pcmData.length / ratio);
    const result = new Int16Array(newLength);

    for (let i = 0; i < newLength; i++) {
        const srcIndex = i * ratio;
        const srcIndexFloor = Math.floor(srcIndex);
        const srcIndexCeil = Math.min(srcIndexFloor + 1, pcmData.length - 1);
        const frac = srcIndex - srcIndexFloor;

        result[i] = Math.round(
            pcmData[srcIndexFloor] * (1 - frac) +
            pcmData[srcIndexCeil] * frac
        );
    }

    return result;
}


// ══════════════════════════════════════════════════════════════
//  Audio Capture — AudioWorklet + MediaRecorder Fallback
// ══════════════════════════════════════════════════════════════

const PROTOCOL_VERSION = 1;
const TARGET_SAMPLE_RATE = 16000;
const CHUNK_MS = 20;

class AudioCapture {
    /**
     * @param {WebSocket} ws - WebSocket bağlantısı
     * @param {Object} options
     * @param {boolean} options.useBinary - Binary transfer kullan (default: true)
     * @param {number} options.maxRecordMs - Maksimum kayıt süresi (ms)
     */
    constructor(ws, options = {}) {
        this.ws = ws;
        this.useBinary = options.useBinary !== false;
        this.maxRecordMs = options.maxRecordMs || 30000; // 30s max

        this._stream = null;
        this._audioContext = null;
        this._workletNode = null;
        this._mediaRecorder = null;
        this._handshakeAcked = false;
        this._recording = false;
        this._mode = null; // 'worklet' | 'mediarecorder'
        this._startTime = null;
        this._chunkCount = 0;
    }

    /**
     * Audio capture başlat.
     * Önce AudioWorklet dener, desteklenmezse MediaRecorder'a düşer.
     */
    async start() {
        if (this._recording) return;

        try {
            this._stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    sampleRate: { ideal: TARGET_SAMPLE_RATE },
                    echoCancellation: true,
                    noiseSuppression: true,
                },
                video: false,
            });
        } catch (err) {
            console.error('[AudioCapture] Mikrofon erişimi reddedildi:', err);
            throw new Error('Mikrofon erişimi reddedildi: ' + err.message);
        }

        this._recording = true;
        this._startTime = Date.now();
        this._chunkCount = 0;

        if (this.useBinary && this._supportsAudioWorklet()) {
            try {
                await this._startWorklet();
                return;
            } catch (err) {
                console.warn('[AudioCapture] AudioWorklet başarısız, fallback:', err);
            }
        }

        // Fallback: MediaRecorder
        this._startMediaRecorder();
    }

    /**
     * Audio capture durdur.
     */
    stop() {
        this._recording = false;

        if (this._workletNode) {
            this._workletNode.port.postMessage({ type: 'stop' });
            this._workletNode.disconnect();
            this._workletNode = null;
        }

        if (this._audioContext) {
            this._audioContext.close().catch(() => {});
            this._audioContext = null;
        }

        if (this._mediaRecorder && this._mediaRecorder.state !== 'inactive') {
            this._mediaRecorder.stop();
            this._mediaRecorder = null;
        }

        if (this._stream) {
            this._stream.getTracks().forEach(track => track.stop());
            this._stream = null;
        }

        // audio_end gönder
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: 'audio_end' }));
        }

        console.log(`[AudioCapture] Durduruldu — ${this._chunkCount} chunks, mode: ${this._mode}`);
    }

    /** @returns {string} 'worklet' | 'mediarecorder' | null */
    get mode() { return this._mode; }

    /** @returns {boolean} */
    get isRecording() { return this._recording; }

    // ── AudioWorklet Path ───────────────────────────────────

    _supportsAudioWorklet() {
        return typeof AudioContext !== 'undefined' &&
               typeof AudioWorkletNode !== 'undefined';
    }

    async _startWorklet() {
        this._audioContext = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });

        // AudioWorklet module yükle (localhost'tan)
        await this._audioContext.audioWorklet.addModule('/static/js/audio-processor.js');

        // Source → Worklet bağla
        const source = this._audioContext.createMediaStreamSource(this._stream);
        this._workletNode = new AudioWorkletNode(this._audioContext, 'audio-processor');

        // Worklet'ten gelen PCM data'yı WS'e gönder
        this._workletNode.port.onmessage = (event) => {
            if (!this._recording) return;
            if (event.data.type !== 'pcm_data') return;

            // Max süre kontrolü
            if (Date.now() - this._startTime > this.maxRecordMs) {
                this.stop();
                return;
            }

            const pcmBuffer = new Int16Array(event.data.buffer);

            // Resample gerekiyorsa
            const actualRate = this._audioContext.sampleRate;
            const finalPcm = actualRate !== TARGET_SAMPLE_RATE
                ? resample(pcmBuffer, actualRate, TARGET_SAMPLE_RATE)
                : pcmBuffer;

            // Handshake yapılmamışsa gönder
            if (!this._handshakeAcked) {
                this._sendHandshake();
            }

            // Binary gönder
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(finalPcm.buffer);
                this._chunkCount++;
            }
        };

        this._workletNode.onprocessorerror = (err) => {
            console.error('[AudioCapture] Worklet processor error:', err);
            // Fallback to MediaRecorder
            this._workletNode.disconnect();
            this._startMediaRecorder();
        };

        source.connect(this._workletNode);
        // Worklet'i destination'a bağlama — sadece capture, playback yok
        this._mode = 'worklet';
        this._sendHandshake();

        console.log('[AudioCapture] AudioWorklet başlatıldı');
    }

    _sendHandshake() {
        if (this._handshakeAcked) return;
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;

        this.ws.send(JSON.stringify({
            type: 'audio_config',
            protocol_version: PROTOCOL_VERSION,
            encoding: 'pcm_s16le',
            sample_rate: TARGET_SAMPLE_RATE,
            channels: 1,
            chunk_ms: CHUNK_MS,
        }));

        // ACK dinle (ws.onmessage handler dışarıdan set edilmiş olmalı)
        this._handshakeAcked = true; // Optimistic — server reject ederse error gelir
    }

    // ── MediaRecorder Fallback ──────────────────────────────

    _startMediaRecorder() {
        this._mode = 'mediarecorder';

        const options = { mimeType: 'audio/webm;codecs=opus' };
        if (!MediaRecorder.isTypeSupported(options.mimeType)) {
            options.mimeType = 'audio/webm';
        }

        this._mediaRecorder = new MediaRecorder(this._stream, options);
        const chunks = [];

        this._mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0 && event.data.size <= 65536) {
                chunks.push(event.data);
            }
        };

        this._mediaRecorder.onstop = async () => {
            if (chunks.length === 0) return;

            const blob = new Blob(chunks, { type: options.mimeType });
            const buffer = await blob.arrayBuffer();
            const base64 = btoa(
                new Uint8Array(buffer).reduce(
                    (data, byte) => data + String.fromCharCode(byte), ''
                )
            );

            // Legacy base64 path
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({
                    type: 'audio',
                    audio: base64,
                    format: 'webm',
                }));
            }
        };

        // timeslice: her 250ms'de chunk oluştur
        this._mediaRecorder.start(250);
        console.log('[AudioCapture] MediaRecorder fallback başlatıldı');
    }
}

// Export for use in other modules
if (typeof window !== 'undefined') {
    window.AudioCapture = AudioCapture;
}
