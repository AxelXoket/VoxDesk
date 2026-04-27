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
     * Sprint 3.5: Transport adapter pattern.
     * @param {Object} transport - Transport adapter OR raw WebSocket (deprecated)
     * @param {Function} transport.sendControl - JSON gönder
     * @param {Function} transport.sendBinary - ArrayBuffer gönder
     * @param {Function} transport.isOpen - Bağlantı açık mı
     * @param {Object} options
     * @param {boolean} options.useBinary - Binary transfer kullan (default: true)
     * @param {number} options.maxRecordMs - Maksimum kayıt süresi (ms)
     */
    constructor(transport, options = {}) {
        // Sprint 3.5: Backwards compat — raw WebSocket geçilirse adapter'a sar
        // NOT: Bu sadece güvenlik ağıdır. Normal akış transport adapter kullanmalı.
        if (typeof WebSocket !== 'undefined' && transport instanceof WebSocket) {
            console.warn('[AudioCapture] Raw WebSocket deprecated, use transport adapter');
            const ws = transport;
            this._transport = {
                sendControl: (payload) => {
                    if (ws.readyState === WebSocket.OPEN)
                        ws.send(JSON.stringify(payload));
                },
                sendBinary: (buffer) => {
                    if (ws.readyState === WebSocket.OPEN)
                        ws.send(buffer);
                },
                isOpen: () => ws.readyState === WebSocket.OPEN,
            };
        } else {
            this._transport = transport;
        }

        this.useBinary = options.useBinary !== false;
        this.maxRecordMs = options.maxRecordMs || 30000; // 30s max

        this._stream = null;
        this._audioContext = null;
        this._workletNode = null;
        this._mediaRecorder = null;
        this._handshakeAcked = false;
        this._handshakeSent = false;
        this._recording = false;
        this._mode = null; // 'worklet' | 'mediarecorder'
        this._startTime = null;
        this._chunkCount = 0;
        this._pendingChunks = []; // Buffer until ACK
        // Sprint 3.5: ACK bound/timeout
        this._maxPendingChunks = 10;
        this._ackTimeoutMs = 3000;
        this._ackTimer = null;
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
     * Sprint 3.5: Mode-aware stop — MediaRecorder fallback için audio_end göndermez.
     */
    stop() {
        this._recording = false;

        // Sprint 3.5: ACK timer temizliği
        if (this._ackTimer) {
            clearTimeout(this._ackTimer);
            this._ackTimer = null;
        }

        if (this._mode === 'worklet') {
            // Worklet cleanup
            if (this._workletNode) {
                this._workletNode.port.postMessage({ type: 'stop' });
                this._workletNode.disconnect();
                this._workletNode = null;
            }
            if (this._audioContext) {
                this._audioContext.close().catch(() => {});
                this._audioContext = null;
            }
            // Worklet mode: audio_end gönder
            if (this._transport.isOpen()) {
                this._transport.sendControl({ type: 'audio_end' });
            }
        } else if (this._mode === 'mediarecorder') {
            // Sprint 3.5: MediaRecorder mode — audio_end göndermiyoruz
            // onstop callback legacy audio JSON gönderir, audio_end beklenmez
            if (this._mediaRecorder && this._mediaRecorder.state !== 'inactive') {
                this._mediaRecorder.stop();
                this._mediaRecorder = null;
            }
        }

        // Mic stream cleanup (her iki mod için)
        if (this._stream) {
            this._stream.getTracks().forEach(track => track.stop());
            this._stream = null;
        }

        // Sprint 2: Reset handshake state for clean next session
        this._handshakeAcked = false;
        this._handshakeSent = false;
        this._pendingChunks = [];

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

            // Handshake gönderilmemişse gönder
            if (!this._handshakeSent) {
                this._sendHandshake();
            }

            // ACK bekle — buffer'a ekle
            if (!this._handshakeAcked) {
                // Sprint 3.5: Bounded pending buffer
                if (this._pendingChunks.length >= this._maxPendingChunks) {
                    console.warn('[AudioCapture] Max pending chunks — dropping oldest');
                    this._pendingChunks.shift();
                }
                this._pendingChunks.push(finalPcm.buffer);
                return;
            }

            // Binary gönder — Sprint 3.5: transport adapter
            if (this._transport.isOpen()) {
                this._transport.sendBinary(finalPcm.buffer);
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
        if (this._handshakeSent) return;
        if (!this._transport.isOpen()) return;

        this._transport.sendControl({
            type: 'audio_config',
            protocol_version: PROTOCOL_VERSION,
            encoding: 'pcm_s16le',
            sample_rate: TARGET_SAMPLE_RATE,
            channels: 1,
            chunk_ms: CHUNK_MS,
        });

        this._handshakeSent = true;
        // ACK will be received via handleMessage() — do NOT set _handshakeAcked here

        // Sprint 3.5: ACK timeout
        this._ackTimer = setTimeout(() => {
            if (!this._handshakeAcked && this._recording) {
                console.error('[AudioCapture] ACK timeout — stopping');
                this.stop();
            }
        }, this._ackTimeoutMs);
    }

    /**
     * Sprint 2: Process server messages for ACK/error handling.
     * Call this from app.js voice:message event handler.
     * @param {Object} data - Parsed JSON message from server
     */
    handleMessage(data) {
        if (data.type === 'audio_config_ack') {
            this._handshakeAcked = true;
            // Sprint 3.5: Clear ACK timeout
            if (this._ackTimer) {
                clearTimeout(this._ackTimer);
                this._ackTimer = null;
            }
            console.log('[AudioCapture] Handshake ACK received');

            // Flush pending chunks — Sprint 3.5: transport adapter
            if (this._transport.isOpen()) {
                for (const buf of this._pendingChunks) {
                    this._transport.sendBinary(buf);
                    this._chunkCount++;
                }
            }
            this._pendingChunks = [];
        } else if (data.type === 'protocol_error') {
            console.error('[AudioCapture] Protocol error:', data.message || data.code);
            // Reset handshake state on protocol error
            this._handshakeAcked = false;
            this._handshakeSent = false;
            this._pendingChunks = [];
        }
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

            // Legacy base64 path — Sprint 3.5: transport adapter
            if (this._transport.isOpen()) {
                this._transport.sendControl({
                    type: 'audio',
                    audio: base64,
                    format: 'webm',
                });
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
