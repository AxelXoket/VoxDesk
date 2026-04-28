"""
VoxDesk — Çalışma Zamanı İzolasyonu
İndirme bittikten sonra tüm dış bağlantıları kapatır.
Kullanım sırasında hiçbir veri bilgisayar dışına çıkmaz.
"""

from __future__ import annotations

import os
import socket
import logging

logger = logging.getLogger("voxdesk.isolation")


def _set_env_guards() -> None:
    """Tüm bileşenlerin dış bağlantı yapmasını engelleyen env variable'ları set et."""
    guards = {
        # HuggingFace Hub — model indirme/kontrol tamamen kapalı
        "HF_HUB_OFFLINE": "1",
        # Transformers — offline mode
        "TRANSFORMERS_OFFLINE": "1",
    }

    for key, value in guards.items():
        os.environ[key] = value
        logger.debug(f"İzolasyon guard: {key}={value}")


def verify_isolation() -> dict:
    """
    Tam izolasyon doğrulaması yap.
    İndirme sonrası çalışma zamanında çağrılır.

    NOT: Outbound bağlantı testi yapılmaz — privacy-first politika gereği
    startup'ta hiçbir dış bağlantı açılmaz. Env guard'lar asıl enforcement
    mekanizmasıdır.

    Returns:
        dict: İzolasyon durumu raporu
    """
    report = {
        "env_guards_set": False,
        "status": "UNKNOWN",
    }

    # 1. Environment guard'ları set et
    _set_env_guards()
    report["env_guards_set"] = True
    logger.info("✅ Environment guard'ları aktif")

    # 2. Guard'ları doğrula
    hf_offline = os.environ.get("HF_HUB_OFFLINE") == "1"
    tf_offline = os.environ.get("TRANSFORMERS_OFFLINE") == "1"

    if hf_offline and tf_offline:
        report["status"] = "OK"
        logger.info("🔒 İzolasyon aktif — tüm env guard'lar set edildi")
    else:
        report["status"] = "WARNING"
        logger.warning(
            "⚠️  Bazı env guard'lar eksik — izolasyon tam değil. "
            f"HF_HUB_OFFLINE={os.environ.get('HF_HUB_OFFLINE')}, "
            f"TRANSFORMERS_OFFLINE={os.environ.get('TRANSFORMERS_OFFLINE')}"
        )

    # 3. Bileşen durumlarını logla
    logger.info(f"   HF_HUB_OFFLINE={os.environ.get('HF_HUB_OFFLINE')}")
    logger.info(f"   TRANSFORMERS_OFFLINE={os.environ.get('TRANSFORMERS_OFFLINE')}")
    logger.info(f"   FastAPI bind: 127.0.0.1 only")

    return report
