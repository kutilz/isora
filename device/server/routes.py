"""
Routes — Definisi semua endpoint dan handler-nya.
Diimport oleh web_server.py.

Endpoint Map:
  GET  /            → Dashboard HTML
  GET  /snapshot    → JPEG frame
  GET  /status      → JSON status
  POST /command     → Kirim command ke AI loop
  GET  /audio/{f}   → Serve WAV file
  GET  /logs        → Log stream (JSON)
  POST /config      → Update config runtime
"""

# Semua logika handler sudah ada di web_server.py (AuralAIHandler).
# File ini berfungsi sebagai dokumentasi route map dan bisa dikembangkan
# menjadi router terpisah jika server makin kompleks.

ROUTES = {
    "GET": {
        "/":            "serve_dashboard",
        "/snapshot":    "serve_snapshot",
        "/status":      "serve_status",
        "/logs":        "serve_logs",
        "/audio/<f>":   "serve_audio",
    },
    "POST": {
        "/command":     "handle_command",
        "/config":      "handle_config",
    },
}
