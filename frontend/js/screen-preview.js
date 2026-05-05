/**
 * VoxDesk — Screen Preview
 * WebSocket üzerinden canlı ekran görüntüsü.
 * Sprint 7.2: Honors window.voxScreenEnabled flag.
 */

class VoxScreenPreview {
    constructor() {
        this.previewImg = document.getElementById('previewImage');
        this.placeholder = document.querySelector('.preview-placeholder');
        this.captureDot = document.getElementById('captureDot');
        this.lastFrameTime = 0;

        this.init();
    }

    init() {
        window.voxWs.on('screen:frame', (data) => this.handleFrame(data));
    }

    handleFrame(data) {
        // Sprint 7.2: Skip frame updates when screen capture is disabled
        if (window.voxScreenEnabled === false) return;

        if (data.type === 'frame' && data.image) {
            // Base64 image göster
            this.previewImg.src = `data:image/jpeg;base64,${data.image}`;
            this.previewImg.style.display = 'block';
            this.previewImg.style.opacity = '1';
            if (this.placeholder) this.placeholder.style.display = 'none';

            // Live dot aktif
            this.captureDot.classList.add('active');
            this.lastFrameTime = Date.now();

            // 3 saniye frame gelmezse inactive yap
            clearTimeout(this._dotTimeout);
            this._dotTimeout = setTimeout(() => {
                this.captureDot.classList.remove('active');
            }, 3000);
        }
    }
}

window.VoxScreenPreview = null;
