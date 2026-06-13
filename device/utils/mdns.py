"""
mDNS publisher — makes the dashboard reachable at http://<device_name>.local:<port>
regardless of the DHCP IP, and gives each unit a unique `.local` name so 5 devices
on one LAN never collide.

Primary:  in-process python `zeroconf` responder (shipped on the MaixCAM image).
          Publishes an A record for <name>.local plus an _http._tcp service.
Fallback: best-effort `avahi-set-host-name` + `avahi-publish-service` if zeroconf
          is unavailable. Either way the system hostname is set so the box
          self-identifies as <name>.

Never raises — every failure is logged and swallowed so it can't break boot.
"""

import socket
import threading
from typing import Callable


class MdnsPublisher:
    def __init__(self, logger, port: int,
                 name_provider: Callable[[], str],
                 ip_provider: Callable[[], str]):
        self.logger = logger
        self.port = port
        self._name_provider = name_provider   # () -> "aural-bfe2"
        self._ip_provider = ip_provider       # () -> "10.146.235.103"
        self._zc = None
        self._info = None
        self._avahi_proc = None
        self._name = ""
        self._lock = threading.Lock()

    # ─── lifecycle ────────────────────────────────────────────────────────────

    def start(self):
        try:
            with self._lock:
                self._name = self._name_provider()
                self._set_system_hostname(self._name)
                if self._start_zeroconf(self._name):
                    self.logger.ok(
                        f"mDNS active (zeroconf) → http://{self._name}.local:{self.port}",
                        module="Mdns")
                    return
                if self._start_avahi(self._name):
                    self.logger.ok(
                        f"mDNS active (avahi) → http://{self._name}.local:{self.port}",
                        module="Mdns")
                    return
            self.logger.warn(
                "mDNS unavailable — dashboard reachable by IP only", module="Mdns")
        except Exception as e:
            self.logger.warn(f"mDNS start failed: {e}", module="Mdns")

    def update_name(self, new_name: str):
        """Re-publish under a new name (called when the user renames in setup)."""
        try:
            with self._lock:
                if not new_name or new_name == self._name:
                    return
                self._teardown_locked()
                self._name = new_name
                self._set_system_hostname(new_name)
                if not self._start_zeroconf(new_name):
                    self._start_avahi(new_name)
            self.logger.info(f"mDNS renamed → {new_name}.local", module="Mdns")
        except Exception as e:
            self.logger.warn(f"mDNS rename failed: {e}", module="Mdns")

    def stop(self):
        try:
            with self._lock:
                self._teardown_locked()
        except Exception:
            pass

    # ─── zeroconf (primary) ───────────────────────────────────────────────────

    def _start_zeroconf(self, name: str) -> bool:
        try:
            from zeroconf import Zeroconf, ServiceInfo
        except Exception:
            return False
        try:
            ip = self._ip_provider() or self._fallback_ip()
            if not ip:
                return False
            self._zc = Zeroconf()
            self._info = ServiceInfo(
                "_http._tcp.local.",
                f"{name}._http._tcp.local.",
                addresses=[socket.inet_aton(ip)],
                port=self.port,
                properties={"path": "/"},
                server=f"{name}.local.",
            )
            self._zc.register_service(self._info, allow_name_change=True)
            return True
        except Exception as e:
            self.logger.warn(f"zeroconf publish failed: {e}", module="Mdns")
            try:
                if self._zc:
                    self._zc.close()
            except Exception:
                pass
            self._zc = None
            self._info = None
            return False

    # ─── avahi (fallback) ─────────────────────────────────────────────────────

    def _start_avahi(self, name: str) -> bool:
        import shutil
        import subprocess
        if not shutil.which("avahi-publish-service"):
            return False
        # The image ships avahi but the daemon may be stopped — try to start it.
        try:
            subprocess.run(["/etc/init.d/S50avahi-daemon", "start"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=8)
        except Exception:
            pass
        try:
            setname = shutil.which("avahi-set-host-name")
            if setname:
                subprocess.run([setname, name], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=5)
        except Exception:
            pass
        try:
            self._avahi_proc = subprocess.Popen(
                ["avahi-publish-service", name, "_http._tcp", str(self.port)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            self.logger.warn(f"avahi publish failed: {e}", module="Mdns")
            return False

    # ─── helpers ──────────────────────────────────────────────────────────────

    def _set_system_hostname(self, name: str):
        try:
            socket.sethostname(name)
        except Exception:
            pass
        try:  # persist (rootfs is writable on this image)
            with open("/etc/hostname", "w") as f:
                f.write(name + "\n")
        except Exception:
            pass

    def _fallback_ip(self) -> str:
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return ""
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass

    def _teardown_locked(self):
        try:
            if self._zc and self._info:
                self._zc.unregister_service(self._info)
        except Exception:
            pass
        try:
            if self._zc:
                self._zc.close()
        except Exception:
            pass
        self._zc = None
        self._info = None
        try:
            if self._avahi_proc:
                self._avahi_proc.terminate()
        except Exception:
            pass
        self._avahi_proc = None
