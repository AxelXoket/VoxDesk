# VoxDesk — Security & Privacy Policy

> **Kısa karar:** İndirme için internet kullanılabilir; kullanıcı verisi için dışarı çıkış yok.

---

## Outbound Network — Deny-by-Default

Runtime'da **dış internet** çıkışı **yasaktır.** Aşağıdakiler çalışma zamanında **bulunmaz:**

- External LLM provider (OpenAI, Anthropic, Google vb.)
- Telemetry / analytics / tracking
- Otomatik güncelleme kontrolü
- Crash report upload
- CDN asset yükleme
- Runtime model download (model eksikse Setup Wizard'a yönlendir)

### Localhost-Only HTTP Client (httpx)

> **Sprint 8 :** `httpx` artık runtime'da **mevcuttur** ancak yalnızca
> yerel llama-server sidecar ile iletişim için kullanılır.

| Kural | Değer |
|:------|:------|
| İzin verilen hedef | Yalnızca `http://127.0.0.1:<port>` ve `http://localhost:<port>` |
| Yasaklanan hedefler | `http://0.0.0.0`, LAN IP'leri, public IP'ler, `https://api.openai.com`, tüm dış domainler |
| Enforasyon | `LocalLlamaServerProvider` constructor'ında hostname doğrulanır — uzak URL'ler `ValueError` ile reddedilir |
| "OpenAI-compatible" | Yalnızca yerel JSON/API formatı anlamına gelir — OpenAI bulut hizmeti değil |
| Base64 loglama | **Yasak** — görüntü/ses verileri asla loglanmaz, sadece metadata (boyut, kaynak, endpoint) |
| Sidecar bind | llama-server daima `--host 127.0.0.1` ile başlatılır — `0.0.0.0` yasak |

### İzin Verilen Outbound (Sadece Setup)

| Koşul | Şart |
|:------|:-----|
| Ne zaman? | Sadece Setup Wizard / Model Downloader |
| Kullanıcı onayı? | Zorunlu — açık onay olmadan indirme başlamaz |
| Kaynak? | Sadece allowlisted domain (HuggingFace vb.) |
| Doğrulama? | SHA256 checksum zorunlu |
| Hedef? | Sadece `models/` klasörüne |

---

## Inbound Network — Localhost Only

| Kural | Değer | Config |
|:------|:------|:-------|
| Bind address | `127.0.0.1` | `network.bind_host` |
| `0.0.0.0` | **Yasak** (explicit dev-mode gerektirir) | — |
| CORS | Sadece `localhost` / `127.0.0.1` | — |
| WS Origin | Allowlist: `http://127.0.0.1:*`, `http://localhost:*` | `network.allowed_ws_origins` |
| Debug endpoints | Default **kapalı** | `features.enable_debug_metrics: false` |
| `/api/status` | Model adı + state döndürür, **path/credential yok** | — |
| `/api/settings` | Yapılandırma döndürür, **secret yok** | — |

---

## Local Data — Hiçbir Şey Dışarı Çıkmaz

| Veri | Konum | Upload? |
|:-----|:------|:--------|
| Conversation history | In-memory (`_history`) | ❌ Yok |
| Screen capture | Ring buffer (process içi) | ❌ Yok |
| Audio data | PCM buffer (process içi) | ❌ Yok |
| Logs | Python logging (stdout/file) | ❌ Yok |
| Model dosyaları | `models/` klasörü | ❌ Yok |
| Personality/config | `config/` klasörü | ❌ Yok |

---

## Config Enforcement

```yaml
# config/default.yaml — Privacy section
privacy:
  offline_mode: true
  allow_cloud_providers: false
  allow_runtime_model_downloads: false
  allow_external_telemetry: false
  allow_cdn_assets: false

model_loading:
  local_files_only: true
  fail_if_model_missing: true
```

---

## Denetim Geçmişi

| Tarih | Denetim | Sonuç |
|:------|:--------|:------|
| 2026-04-27 | Sprint 3 Post-Audit + Cross-Reference | ✅ Uyumlu — bilinçli veri çıkışı yok |
| 2026-04-28 | Sprint 5.2+5.3 Audit Triage (100 bug) | ✅ Path leak kapatıldı, DNS çıkışı kaldırıldı, origin bypass düzeltildi |
| 2026-04-29 | Sprint 5.3 Part 5b — Qwen3-VL Feasibility | ✅ Runtime download yok, handler resolution silently-fallback engellendi |
| — | Sprint 4 model downloader | ⏳ Henüz yazılmadı — policy uygulanacak |

---

## İlke

VoxDesk tamamen kişisel, tamamen lokal bir masaüstü asistanıdır.
Hiç kimse — geliştirici dahil — kullanıcının verisine uzaktan erişemez.
