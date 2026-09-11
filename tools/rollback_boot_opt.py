"""Rollback boot optimization — restore original rc.local and main.py on device.

Usage: python tools/rollback_boot_opt.py [--host IP]

This restores the backups created by the deploy script:
  /etc/rc.local.pre-boot-opt.bak → /etc/rc.local
  /root/isora/main.py.pre-boot-opt.bak → /root/isora/main.py
Then reboots the device.
"""
import os
import sys
import argparse
import time

# Load .env
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

DEFAULT_HOST = os.environ.get("ISORA_MAIX_HOST", "10.144.124.103")


def main():
    parser = argparse.ArgumentParser(description="Rollback boot optimization")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Device IP")
    parser.add_argument("--no-reboot", action="store_true", help="Don't reboot after rollback")
    args = parser.parse_args()

    try:
        import paramiko
    except ImportError:
        print("ERROR: pip install paramiko")
        sys.exit(1)

    print(f"Connecting to {args.host}...")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(args.host, username='root', password='root', timeout=10,
              banner_timeout=20, auth_timeout=15, look_for_keys=False, allow_agent=False)

    def run(cmd):
        _, out, err = c.exec_command(cmd, timeout=30)
        return out.read().decode('utf-8', 'replace').strip()

    # Check backups exist
    rc_bak = run('test -f /etc/rc.local.pre-boot-opt.bak && echo yes || echo no')
    main_bak = run('test -f /root/isora/main.py.pre-boot-opt.bak && echo yes || echo no')

    if rc_bak != 'yes':
        print("WARNING: /etc/rc.local.pre-boot-opt.bak not found!")
    if main_bak != 'yes':
        print("WARNING: /root/isora/main.py.pre-boot-opt.bak not found!")

    if rc_bak != 'yes' and main_bak != 'yes':
        print("ERROR: No backups found. Cannot rollback.")
        sys.exit(1)

    # Restore
    if rc_bak == 'yes':
        run('cp /etc/rc.local.pre-boot-opt.bak /etc/rc.local && chmod +x /etc/rc.local')
        print("Restored /etc/rc.local from backup")
    if main_bak == 'yes':
        run('cp /root/isora/main.py.pre-boot-opt.bak /root/isora/main.py')
        print("Restored /root/isora/main.py from backup")

    run('sync')

    # Verify
    rc_content = run('cat /etc/rc.local')
    if 'sleep 5' in rc_content:
        print("VERIFIED: rc.local has sleep 5 (original)")
    else:
        print("WARNING: rc.local doesn't have sleep 5 — check manually")

    if not args.no_reboot:
        print("\nRebooting device...")
        try:
            c.exec_command('reboot', timeout=3)
        except Exception:
            pass
        print("Reboot command sent. Device will restart with original boot behavior.")
    else:
        print("\nSkipped reboot. Restart the device manually to apply.")

    c.close()


if __name__ == "__main__":
    main()
