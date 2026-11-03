#!/bin/sh
# wpa_cli action script (I-Sora). Called as: <ifname> CONNECTED|DISCONNECTED
# Installed to /etc/wifi_roam.sh by `tools/run.py --autostart`; source of truth
# is device/system/wifi_roam.sh in the repo.
#
# udhcpc does not notice when wpa_supplicant moves to another network (e.g.
# NETGEAR30 -> a phone hotspot): it keeps the old IP + gateway until the lease
# runs out, so the device is "connected" with no internet and the app stalls.
# On CONNECTED to a DIFFERENT access point, drop the old lease (USR2) and ask
# for a new one (USR1).
#
# Reconnecting to the SAME access point (a weak-signal blip) keeps the lease:
# the address is still valid there, and releasing it would cut every open
# connection (a describe request, the cloud long-poll) for nothing. Compared by
# BSSID, not by network id or SSID: a phone hotspot named like the router
# shares both, and that is exactly the case that needs a new lease.
#
# At boot wlan0 has no IP yet and S30wifi's udhcpc is mid-DISCOVER — leave it
# alone, there is no stale lease to drop.
IF="$1"
[ "$2" = "CONNECTED" ] || exit 0

RUN=${WIFI_ROAM_RUN:-/run}
TRACE=${WIFI_ROAM_TRACE:-/root/wifi_roam.trace}

STATUS=$(wpa_cli -i "$IF" status 2>/dev/null)
SSID=$(echo "$STATUS" | sed -n 's/^ssid=//p')
BSSID=$(echo "$STATUS" | sed -n 's/^bssid=//p')
LAST="$RUN/wifi_roam.$IF.bssid"
PREV=$(cat "$LAST" 2>/dev/null)
echo "$BSSID" > "$LAST"
PIDF="$RUN/udhcpc.$IF.pid"
PID=$(cat "$PIDF" 2>/dev/null)

note() {
    echo "$(date +%F_%T) $IF CONNECTED ssid=$SSID bssid=$BSSID $1" >> "$TRACE"
    # The trace lives on the SD card; keep it bounded.
    if [ "$(wc -c < "$TRACE" | tr -d ' ')" -gt 65536 ]; then
        tail -n 200 "$TRACE" > "$TRACE.tmp" && mv "$TRACE.tmp" "$TRACE"
    fi
}

udhcpc_alive() { [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; }

# Same flags as S30wifi. Backgrounded: with -b udhcpc stays in the foreground
# until it has a lease, and wpa_cli processes no events while this script runs.
start_udhcpc() { (udhcpc -i "$IF" -t 10 -T 1 -A 5 -b -p "$PIDF" >/dev/null 2>&1) & }

if ! ip -4 addr show "$IF" | grep -q "inet "; then
    if udhcpc_alive; then
        note "(belum ada IP, udhcpc sedang mencari)"
    else
        start_udhcpc
        note "(belum ada IP dan udhcpc mati -> udhcpc dinyalakan)"
    fi
    exit 0
fi

if [ -n "$BSSID" ] && [ "$BSSID" = "$PREV" ]; then
    note "(AP sama, lease dipertahankan)"
    exit 0
fi

# Nothing remembered yet: this is the first event since wpa_cli attached,
# which at boot is usually a few seconds AFTER S30wifi's udhcpc got its lease.
# If that lease's gateway answers, the lease belongs to this network — keep
# it. Releasing a seconds-old lease left isora-iiot with no IP at all for
# 3-10 minutes on a phone hotspot (wifi_roam.trace, 22 Oct 2026).
gateway_answers() {
    GW=$(ip -4 route show default dev "$IF" 2>/dev/null \
         | sed -n 's/^default via \([0-9.]*\).*/\1/p' | head -n 1)
    [ -n "$GW" ] && ping -c 1 -W 2 "$GW" >/dev/null 2>&1
}
if [ -z "$PREV" ] && gateway_answers; then
    note "(lease awal, gateway $GW menjawab, dipertahankan)"
    exit 0
fi

if udhcpc_alive; then
    kill -USR2 "$PID"
    sleep 1
    kill -USR1 "$PID"
else
    start_udhcpc
fi
logger -t wifi_roam "$IF connected to '$SSID' ($BSSID) -> DHCP lease baru" 2>/dev/null
note "-> DHCP lease baru"
