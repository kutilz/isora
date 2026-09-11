"""Pytest bootstrap for device-side unit tests.

The on-device app runs with `device/` as the import root (main.py lives in
/root/aural-ai and does `from core...`, `from utils...`, `from config...`).
Mirror that here so tests import the same way the device does.
"""

import os
import sys

_DEVICE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _DEVICE_ROOT not in sys.path:
    sys.path.insert(0, _DEVICE_ROOT)
