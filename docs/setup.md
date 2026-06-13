# AuralAI SDK — Setup Guide

## Prerequisites

- Sipeed MaixCAM (regular variant) running the latest MaixPy image
- Python 3.10+ installed on your laptop/PC
- MaixVision IDE (for deployment and monitoring)
- Active WiFi connection sharing the same network between your laptop and the MaixCAM

---

## 1. Setup on PC (Laptop)

```bash
# Clone the repository
git clone https://github.com/<username>/AuralAI-SDK.git
cd AuralAI-SDK

# Install PC-side dependencies
pip install -r requirements_pc.txt
```

---

## 2. Generate Audio Files

Run this command once before deployment (requires an internet connection for Google TTS):

```bash
# Generate the full set from audio/AuralAI_Audio_Wordlist.md (~137 files)
python tools/generate_audio.py --from-wordlist

# Generate the legacy set (objects × position + system cues)
python tools/generate_audio.py --legacy
```

The generated WAV files will be saved to the `audio/` directory.

To preview without saving files:
```bash
python tools/generate_audio.py --dry-run --from-wordlist
```

---

## 3. Download Models

### For `device/main.py` (orchestrator + YOLOv8)

1. Visit the [MaixHub Model Zoo](https://maixhub.com/model/zoo/196)
2. Download the **YOLO11n COCO 320×224** model (in `.mud` format)
3. Save it as `models/yolo11n.mud` and adjust `MODEL_PATH` in `device/config.py` accordingly.

### For `device/aural_maix.py` (MVP stack / YOLOv5)

The script looks for model files in the following order:

- `/root/models/yolov5s_320x224_int8.cvimodel`
- `/root/models/yolov5s.mud`

Download a compatible YOLOv5 COCO 320×224 model from MaixHub, and place it at one of the paths above on your MaixCAM.

---

## 4. Deploy to MaixCAM

### 4a. Via MaixVision (Manual)

1. Open MaixVision → Connect to your MaixCAM
2. Upload the `device/` folder to `/root/aural-ai/` via the File Manager
3. Upload the `audio/` folder to `/root/audio/`
4. Upload the YOLO model to `/root/models/yolo11n.mud`

### 4b. Via Deploy Script (Automatic)

Ensure both MaixCAM and your laptop are on the same WiFi network:

```bash
# Deploy everything (device code + audio files)
python tools/deploy.py

# Specify a custom IP address if mDNS is not functioning
python tools/deploy.py --host 192.168.1.100

# Run a preview/dry run
python tools/deploy.py --dry-run
```

---

## 5. Set API Keys (Optional — for Context Mode)

On your MaixCAM, create a `/root/.env` file:

```bash
# In the MaixCAM terminal or via the MaixVision terminal:
echo 'OPENAI_API_KEY=sk-...' > /root/.env
```

In `device/main.py`, load the `.env` file before importing other modules:

```python
from dotenv import load_dotenv
load_dotenv("/root/.env")
```

---

## 6. Run AuralAI SDK

### Via MaixVision
1. Open `device/main.py` in MaixVision
2. Click **Run**

### Via SSH / MaixCAM Terminal
```bash
cd /root/aural-ai/
python main.py
```

---

## 7. Access Web Dashboard

Open a browser on your phone or laptop:
```
http://maixcam.local:8080
```

Alternatively, use the direct IP address if mDNS is not working:
```
http://192.168.1.XXX:8080
```

---

## 7b. Cloud Pairing (recommended for first-time setup)

Instead of typing a `*.local` address, let the device pair through the **AuralAI
web hub**. Once the device is on WiFi it speaks a short **pairing code**; open the
hub, sign in, and enter the code to configure the AI provider/key and audio
preferences remotely (pushed back to the device, API keys end-to-end encrypted).

- Deploy / run the hub: see [`web/README.md`](../web/README.md) and the
  *Cloud Pairing & Web Hub* section in the [main README](../README.md).
- Point the device at your hub via `cloud_base_url` in
  [`device/config.py`](../device/config.py) (defaults to `https://auralai.app`;
  use your PC's LAN IP, e.g. `http://192.168.1.50:3000`, for local testing).
- Test the whole relay **without hardware**:
  ```bash
  pip install cryptography
  python tools/mock_device.py --base-url http://localhost:3000
  ```
- Cloud is **optional and offline-safe**: set `cloud_enabled=false` (or simply
  leave the device offline) and the local spoken-URL `/setup` flow above still works.

---

## 8. Companion PC — MVP Stack (MaixCAM + PC)

This architecture splits **lightweight inference (YOLO on MaixCAM)** and **heavy logic (OpenAI Vision / Browser TTS)**. It runs a Flask server on your laptop (`companion/webserver.py`). This pattern aligns with MaixPy documentation using the standard `requests` module on the device.

### 8a. PC (Laptop) Setup

```bash
cd aural-ai-sdk
pip install -r requirements_pc.txt
cp companion/.env.example companion/.env    # On Windows: copy companion\.env.example companion\.env
# Edit companion/.env and fill in your OPENAI_API_KEY

python companion/webserver.py
```

Note the **LAN IP** printed in the terminal (e.g., `192.168.1.78`).

### 8b. MaixCAM Setup

Set these environment variables **before** running `aural_maix.py` (you can do this via terminal shell or wrapper in MaixVision):

| Variable | Example | Function |
|----------|--------|----------|
| `AURAL_WIFI_SSID` | SSID | Leave empty if already connected via **Settings → WiFi** (recommended if script DHCP hangs) |
| `AURAL_WIFI_PASSWORD` | Password | — |
| `AURAL_COMPANION_HOST` | Laptop IP | Must be on the same subnet as the MaixCAM |
| `AURAL_COMPANION_PORT` | `5000` | Companion Flask port |

Run on MaixCAM (assuming code is deployed to `/root/aural-ai/`):

```bash
cd /root/aural-ai/
export AURAL_COMPANION_HOST=192.168.x.x
python aural_maix.py
```

Open the Dashboard Observer: `http://<PC-IP>:5000` (from any phone or browser on the same network).

### 8c. Test without MaixCAM (PC Webcam Simulation)

With `webserver.py` running in the background:

```bash
python companion/run_desktop.py
```

### 8d. Isolate and Test MaixCAM → PC Network Connections

If MaixCAM is connected to WiFi but fails with `Network unreachable` or heartbeat timeouts, **do not use `127.0.0.1` or WSL virtual adapter IPs** (`10.207.x.x` are usually virtual adapters that the device cannot reach over WiFi). Use your PC's **physical WiFi/Ethernet IPv4 address** (run `ipconfig` on Windows, look for *Wireless LAN adapter Wi-Fi*).

1. **PC** — Run the minimal debug server (listens on port 8765, avoiding conflicts with the main dashboard):

```bash
python companion/minimal_server.py
```

2. **MaixCAM** — Point the probe host to your PC's Wi-Fi IP and test:

```bash
export AURAL_PROBE_HOST=192.168.x.x
export AURAL_PROBE_PORT=8765
python device/network_probe.py
```

If the connection is successful, stop the test, start `companion/webserver.py`, and run `aural_maix.py` with `AURAL_COMPANION_HOST` set to the **same PC IP** and port `5000`. Ensure your Windows Firewall allows inbound connections to python on those ports.

---

## 9. Mockup Preview (No MaixCAM Required)

To preview the **on-device** Web UI dashboard directly in your browser without any hardware:

1. Open `device/server/static/index.html` in your browser.
2. The dashboard will run in **MOCK MODE** — all hardware metrics are simulated.
3. Audio announcements are rendered using the browser's Web Speech API.

---

## Troubleshooting

| Problem | Solution |
|---------|--------|
| `maixcam.local` is inaccessible | Use the direct IP address instead. |
| Model not found | Double check that `MODEL_PATH` in `config.py` is configured correctly. |
| Audio output is missing | Ensure the `/root/audio/` directory contains WAV files. |
| Web UI does not refresh | Check that port 8080 is not blocked by a firewall. |
| Inference latency is high | Expected. MaixCAM averages ~85-120ms per frame. |
| `[Errno 101] Network unreachable` to PC IP | **Subnet must match** MaixCAM's subnet (typically the first 3 octets, e.g. both `192.168.1.*`). `network_probe.py` will print local vs target IPs. Use the same router/AP; avoid guest networks or AP isolation. Ensure firewall allows TCP port 5000/8765. |
