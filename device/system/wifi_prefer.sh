#!/bin/sh
# I-Sora: if after boot the device is stuck on a network that is not the
# highest priority (e.g. the router, while the phone hotspot is already on),
# request a full scan AT MOST 3 times (every 60 s) and then stop. A scan costs
# radio time and CPU on this 128 MB board, so this deliberately does not run
# forever. Switching is still wpa_supplicant's decision (it picks the highest
# priority network it can see).
# Installed to /etc/wifi_prefer.sh by `tools/run.py --autostart`; source of
# truth is device/system/wifi_prefer.sh in the repo.
W="wpa_cli -i wlan0"
n=0
while [ $n -lt 3 ]; do
    sleep 60
    CUR=$($W status 2>/dev/null | sed -n 's/^id=//p')
    [ -n "$CUR" ] || continue      # not connected: wpa_supplicant scans by itself
    BEST=0; CURP=0
    for id in $($W list_networks | awk 'NR>1 && !/DISABLED/ {print $1}'); do
        p=$($W get_network "$id" priority); p=${p:-0}
        [ "$p" -gt "$BEST" ] 2>/dev/null && BEST=$p
        [ "$id" = "$CUR" ] && CURP=$p
    done
    [ "$CURP" -ge "$BEST" ] 2>/dev/null && exit 0   # already on the top network
    $W scan >/dev/null
    n=$((n+1))
done
