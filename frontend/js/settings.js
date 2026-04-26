/**
 * VoxDesk — Settings Panel
 * Model, ses, kişilik, history yönetimi.
 */

class VoxSettings {
    constructor() {
        this.modelSelect = document.getElementById('modelSelect');
        this.voiceSelect = document.getElementById('voiceSelect');
        this.speedSlider = document.getElementById('speedSlider');
        this.speedValue = document.getElementById('speedValue');
        this.ttsToggle = document.getElementById('ttsToggle');
        this.vaToggle = document.getElementById('vaToggle');
        this.personalitySelect = document.getElementById('personalitySelect');
        this.exportBtn = document.getElementById('btnExportHistory');
        this.clearBtn = document.getElementById('btnClearHistory');

        this.init();
    }

    init() {
        // Speed slider
        this.speedSlider.addEventListener('input', (e) => {
            this.speedValue.textContent = `${e.target.value}x`;
            this.updateVoice();
        });

        // Voice select
        this.voiceSelect.addEventListener('change', () => this.updateVoice());

        // Model select
        this.modelSelect.addEventListener('change', () => this.updateModel());

        // Personality select
        this.personalitySelect.addEventListener('change', () => this.updatePersonality());

        // Export history
        this.exportBtn.addEventListener('click', () => this.exportHistory());

        // Clear history
        this.clearBtn.addEventListener('click', () => this.clearHistory());

        // Load initial data
        this.loadSettings();
        this.loadVoices();
        this.loadModels();
        this.loadPersonalities();
    }

    async loadSettings() {
        try {
            const res = await fetch('/api/settings');
            const data = await res.json();

            this.modelSelect.value = data.model;
            this.voiceSelect.value = data.voice;
            this.speedSlider.value = data.tts_speed;
            this.speedValue.textContent = `${data.tts_speed}x`;
            this.ttsToggle.checked = data.tts_enabled;
            this.vaToggle.checked = data.voice_activation_enabled;
        } catch (e) {
            console.error('Settings yüklenemedi:', e);
        }
    }

    async loadVoices() {
        try {
            const res = await fetch('/api/voices');
            const voices = await res.json();

            this.voiceSelect.innerHTML = '';
            for (const [category, voiceList] of Object.entries(voices)) {
                const group = document.createElement('optgroup');
                group.label = category;
                voiceList.forEach(v => {
                    const opt = document.createElement('option');
                    opt.value = v;
                    opt.textContent = v;
                    group.appendChild(opt);
                });
                this.voiceSelect.appendChild(group);
            }
        } catch (e) {
            console.error('Sesler yüklenemedi:', e);
        }
    }

    async loadModels() {
        try {
            const res = await fetch('/api/models');
            const models = await res.json();

            if (models.length > 0) {
                this.modelSelect.innerHTML = '';
                models.forEach(m => {
                    const opt = document.createElement('option');
                    opt.value = m.name;
                    opt.textContent = m.name;
                    this.modelSelect.appendChild(opt);
                });
            }
        } catch (e) {
            console.error('Modeller yüklenemedi:', e);
        }
    }

    async loadPersonalities() {
        try {
            const res = await fetch('/api/personalities');
            const profiles = await res.json();

            if (profiles.length > 0) {
                this.personalitySelect.innerHTML = '';
                profiles.forEach(p => {
                    const opt = document.createElement('option');
                    opt.value = p.id;
                    opt.textContent = `🤖 ${p.name}`;
                    this.personalitySelect.appendChild(opt);
                });
            }
        } catch (e) {
            console.error('Kişilikler yüklenemedi:', e);
        }
    }

    async updateVoice() {
        try {
            await fetch('/api/voice', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    voice: this.voiceSelect.value,
                    speed: parseFloat(this.speedSlider.value),
                }),
            });
        } catch (e) { /* silent */ }
    }

    async updateModel() {
        try {
            await fetch('/api/model', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model: this.modelSelect.value }),
            });
        } catch (e) { /* silent */ }
    }

    async updatePersonality() {
        try {
            await fetch(`/api/personality/${this.personalitySelect.value}`, {
                method: 'PUT',
            });
        } catch (e) { /* silent */ }
    }

    async exportHistory() {
        try {
            const res = await fetch('/api/history/export', { method: 'POST' });
            const data = await res.json();

            if (data.status === 'ok') {
                alert(`💾 Geçmiş kaydedildi!\n${data.file}\n${data.messages} mesaj`);
            } else {
                alert(data.message || 'Kaydetme hatası');
            }
        } catch (e) {
            alert('Kaydetme hatası: ' + e.message);
        }
    }

    async clearHistory() {
        if (!confirm('Konuşma geçmişini silmek istediğine emin misin?')) return;

        try {
            await fetch('/api/history', { method: 'DELETE' });
            // Chat alanını temizle
            const msgs = document.getElementById('chatMessages');
            while (msgs.children.length > 1) {
                msgs.removeChild(msgs.lastChild);
            }
        } catch (e) {
            console.error('Temizleme hatası:', e);
        }
    }
}

window.VoxSettings = null;
