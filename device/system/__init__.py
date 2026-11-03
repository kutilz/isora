"""
Files that run OUTSIDE the app tree (/root/isora) on the MaixCAM.

`tools/run.py --autostart` installs them:

  wifi_roam.sh   → /etc/wifi_roam.sh          (wpa_cli action script)
  wifi_prefer.sh → /etc/wifi_prefer.sh        (bounded post-boot scan)
  S31wifiroam    → /etc/init.d/S31wifiroam    (starts the two above)
  S03isoraclock  → /etc/init.d/S03isoraclock  (wall clock kept across
                                               restarts; no RTC battery)
  release.py     → /etc/isora/release.py      (boot-time release switch +
                                               rollback, see release.py)

They ride along in /root/isora/system/ too, because the whole device/ tree is
deployed. The copies under /etc are the ones that run; the app only imports
`system.release` for the shared on-disk layout.
"""
