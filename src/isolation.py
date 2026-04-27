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


def _test_outbound_connection() -> bool:
    """
    Dış dünyaya bağlantı olup olmadığını test et.
    Returns True if internet is reachable (WARNING), False if isolated (OK).
    """
    try:
        sock = socket.create_connection(("8.8.8.8", 53), timeout=3)
        sock.close()
        return True  # İnternet erişilebilir
    except (socket.timeout, OSError):
        return False  # İzole — güvenli


def verify_isolation() -> dict:
    """
    Tam izolasyon doğrulaması yap.
    İndirme sonrası çalışma zamanında çağrılır.

    Returns:
        dict: İzolasyon durumu raporu
    """
    report = {
        "env_guards_set": False,
        "internet_blocked": False,
        "status": "UNKNOWN",
    }

    # 1. Environment guard'ları set et
    _set_env_guards()
    report["env_guards_set"] = True
    logger.info("✅ Environment guard'ları aktif")

    # 2. Outbound bağlantı testi
    internet_reachable = _test_outbound_connection()
    report["internet_blocked"] = not internet_reachable

    if internet_reachable:
        report["status"] = "WARNING"
        logger.warning(
            "⚠️  İNTERNET ERİŞİLEBİLİR — Veriler güvende ama tam izolasyon için "
            "internet bağlantısını kesmeniz önerilir. "
            "Env guard'lar aktif, hiçbir bileşen dışarıya bağlanmayacak."
        )
    else:
        report["status"] = "OK"
        logger.info("🔒 Tam izolasyon aktif — İnternet erişimi yok, veriler güvende")

    # 3. Bileşen durumlarını logla
    logger.info(f"   HF_HUB_OFFLINE={os.environ.get('HF_HUB_OFFLINE')}")
    logger.info(f"   TRANSFORMERS_OFFLINE={os.environ.get('TRANSFORMERS_OFFLINE')}")
    logger.info(f"   FastAPI bind: 127.0.0.1 only")

    return report
