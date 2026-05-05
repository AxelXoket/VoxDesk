/**
 * VoxDesk — AudioWorklet Processor
 * Float32 → Int16 PCM dönüşümü ve binary WebSocket transfer.
 * Sprint 7 : RMS level hesabı — silence detection ve waveform görselleştirme.
 *
 * Bu dosya AudioWorkletGlobalScope'ta çalışır (main thread DIŞI).
 * getUserMedia'dan gelen Float32 audio'yu Int16 PCM'e çevirir
 * ve main thread'e port.postMessage ile gönderir.
 *
 * Güvenlik:
 *   - Tüm işlem localhost'ta — dış domain yok
 *   - Audio data disk'e yazılmaz
 *   - External fetch/import yok
 */

class AudioProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this._active = true;

        // Sprint 7: RMS accumulator — her 8 frame'de bir rms_level gönder
        this._rmsAccum = 0;
        this._frameCount = 0;
        this._RMS_REPORT_INTERVAL = 8; // 8 × 128 samples ≈ 21ms

        this.port.onmessage = (event) => {
            if (event.data.type === 'stop') {
                this._active = false;
            }
        };
    }

    /**
     * AudioWorklet process callback.
     * Her 128 sample'da bir çağrılır (render quantum).
     *
     * @param {Float32Array[][]} inputs - Girdi kanalları
     * @param {Float32Array[][]} outputs - Çıktı kanalları (kullanılmaz)
     * @returns {boolean} - true = devam, false = dur
     */
    process(inputs, outputs) {
        if (!this._active) return false;

        const input = inputs[0];
        if (!input || input.length === 0) return true;

        // Mono kanal (index 0)
        const channelData = input[0];
        if (!channelData || channelData.length === 0) return true;

        // Float32 → Int16 PCM (clamp + convert)
        const pcmData = new Int16Array(channelData.length);
        let sumSquares = 0;
        for (let i = 0; i < channelData.length; i++) {
            // Clamp to [-1.0, 1.0]
            const sample = Math.max(-1.0, Math.min(1.0, channelData[i]));
            // Scale to Int16 range
            pcmData[i] = sample < 0
                ? sample * 32768
                : sample * 32767;
            // RMS accumulation (on Float32 for precision)
            sumSquares += sample * sample;
        }

        // Main thread'e PCM gönder
        this.port.postMessage({
            type: 'pcm_data',
            buffer: pcmData.buffer,
        }, [pcmData.buffer]); // Transfer ownership — zero-copy

        // Sprint 7: RMS level — her _RMS_REPORT_INTERVAL frame'de bir raporla
        const frameRms = Math.sqrt(sumSquares / channelData.length);
        this._rmsAccum += frameRms;
        this._frameCount++;

        if (this._frameCount >= this._RMS_REPORT_INTERVAL) {
            const avgRms = this._rmsAccum / this._frameCount;
            this.port.postMessage({
                type: 'rms_level',
                rms: avgRms,
            });
            this._rmsAccum = 0;
            this._frameCount = 0;
        }

        return true;
    }
}

registerProcessor('audio-processor', AudioProcessor);

