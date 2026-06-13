# System Security Audit Report: Hardware & Software - AuralAI SDK

## 1. Network & Web Server Security

### Primary Vulnerability: Lacking Authentication

- **Location:** `device/server/web_server.py`
- **Findings:** All API endpoints (`/config`, `/command`, `/ai-settings`, `/suite/start`) were historically open to the local network without requiring login or token authentication.
- **Risks:** 
  - Anyone on the same network could fully control the device.
  - Modifying the AI provider settings (`POST /ai-settings`) could leak or exhaust the caregiver's cloud credits (OpenAI/Gemini/Claude).
  - Potential Remote Code Execution (RCE) via benchmark endpoints that trigger system processes.

### Data Security (CORS)

- **Findings:** The header `Access-Control-Allow-Origin: *` was enabled globally for all responses.
- **Risks:** Cross-Site Request Forgery (CSRF). A malicious website visited by a user on the same browser could send unauthorized HTTP requests to the MaixCAM's local IP address and modify configuration parameters silently.

---

## 2. Operating System (Software) Security

### Subprocess & Shell Execution

- **Location:** `device/server/web_server.py` (BenchmarkRunner, StressRunner, BenchmarkSuiteRunner).
- **Findings:** Employs `subprocess.Popen` to run Python scripts. While the arguments are statically defined, the lack of authentication on the calling endpoints makes this execution pattern risky.
- **Other Locations:** `device/core/audio_manager.py` uses `os.system()` to convert audio files via FFmpeg.
- **Risks:** If audio filenames can be influenced by users (via prompt injection or configuration inputs), an attacker could perform command injection by writing shell metacharacters (e.g., `;`, `&`, `|`, `$`).

### File Management & Credentials

- **Location:** `/root/config.json`
- **Findings:** API keys and credentials were saved in plain text within the configuration JSON file.
- **Risks:** Anyone with physical access to the device or local shell access can read the plain text API keys.

---

## 3. Hardware & Physical Security

### GPIO Access

- **Location:** `device/core/orchestrator.py`
- **Findings:** The device listens to hardware inputs from physical buttons via GPIO (`button_pin_mode`).
- **Analysis:** By design, this is a feature. However, if the GPIO pins are physically exposed, these "buttons" could be triggered electrically to toggle the device into unwanted operating states.

### Thermal Management & Stability

- **Location:** `device/utils/health.py` and `device/core/watchdog.py`
- **Findings:** A dedicated `HealthMonitor` checks CPU temperature (throttles at 80°C) and a `Watchdog` automatically restarts frozen threads or services.
- **Quality:** Excellent. This prevents thermal degradation or permanent hardware damage during continuous executions of heavy deep-learning models on the SoC.

### I2C Probing

- **Location:** `device/utils/health.py`
- **Findings:** Battery fuel gauge querying is performed by writing directly to the system I2C buses (`/dev/i2c-1` & `/dev/i2c-2`).
- **Risks:** If other sensitive I2C devices share the same target addresses (e.g., 0x36, 0x40), generic probing writes can cause these devices to enter undefined or glitched states.

---

## 4. Risk Summary

| Category | Risk Level | Impact |
|:---|:---|:---|
| **API Authentication** | Critical | Full device control by unauthorized network peers. |
| **API Key Theft** | High | Financial theft/resource exhaustion on Cloud AI accounts. |
| **Command Injection** | Medium | Potential execution of arbitrary OS shell commands. |
| **Thermal Safety** | Low | Effectively managed by active monitoring software. |

---

## 5. Recommendations

1. **Implement API Token/Key Authentication:** Add a lightweight authentication layer (e.g., matching a custom `device_token` or checking `X-API-KEY` headers) for all mutating API requests.
2. **Bind Web Server to Localhost (If Proxying):** If the dashboard is accessed through a secure tunnel or proxy, do not bind the server to `0.0.0.0` (all interfaces); bind only to `127.0.0.1`.
3. **Subprocess Argument Sanitization:** Ensure all dynamic inputs passed to shell-executing commands are strictly sanitized against shell command injection sequences.
4. **Encrypt Local Config Credentials:** Encrypt API keys and credentials before writing them to `config.json` using a device-specific hardware key (e.g., CPU unique ID).
5. **CORS Restrictions:** Enforce strict CORS policies rather than a wildcard `*`. Restrict origins to trusted companion application host addresses.

---

*This report was automatically generated for the AuralAI-SDK system security audit.*
