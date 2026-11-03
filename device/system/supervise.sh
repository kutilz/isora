#!/bin/sh
# I-Sora app supervisor. Installed to /etc/isora/supervise.sh by
# `tools/run.py --autostart` and started by /etc/init.d/S26isoraapp; source of
# truth is device/system/supervise.sh.
#
# A blind user cannot see why the glasses went quiet, and a demo cannot wait
# for someone to pull the power. This keeps main.py running:
#
#   crashed       SIGSEGV in NN model load, the OOM killer on the 128 MB board,
#                 an uncaught error -> started again after a short backoff, so
#                 a crash at start cannot spin the CPU.
#   wedged        a camera/NPU call that blocks holding the GIL stops EVERY
#                 Python thread, core/watchdog.py included. utils/liveness.py
#                 then stops refreshing $ALIVE, and a stale file gets the
#                 process SIGKILLed and started again.
#   still broken  repeated quick failures (a leaked VI channel makes every new
#                 start segfault until the board resets), or a process that
#                 even SIGKILL cannot end -> ONE reboot. Not another until a
#                 start has stayed healthy for $HEALTHY_S, so a bug that
#                 survives a reboot can never become a reboot loop.
#
# A deliberate stop is not a crash: exit 0 (main.py catches SIGTERM and shuts
# down cleanly), 130 (SIGINT) and 143 (SIGTERM before the handler exists) end
# the supervisor, so `kill <pid>`, `S26isoraapp stop` and `tools/run.py
# --stop` stop the app as they always did.
#
# Every start goes through the release helper first, exactly like the init
# script's own start: a trial release that keeps crashing is rolled back after
# release.py's MAX_TRIES starts by the respawns themselves.
#
# Times come from /proc/uptime, never the wall clock: S03isoraclock and NTP
# move the clock by years after boot.
#
# ISORA_* variables exist for device/tests/test_supervisor.py.

RUN=${ISORA_RUN:-/tmp}
STATE=${ISORA_STATE:-/root}
APP_DIR=${ISORA_APP_DIR:-/root/isora}
APP_CMD=${ISORA_APP_CMD:-python3 -u /root/isora/main.py}
H=${ISORA_HELPER:-/etc/isora/release.py}
R=${ISORA_RELEASES:-/root/isora-releases}
STALE_S=${ISORA_STALE_S:-30}       # heartbeat age that counts as wedged
GRACE_S=${ISORA_GRACE_S:-180}      # time a start gets to write its first beat
HEALTHY_S=${ISORA_HEALTHY_S:-300}  # a run this long resets the failure count
GUARD_S=${ISORA_GUARD_S:-240}      # trial guard delay (see core/updater.py)
POLL_S=${ISORA_POLL_S:-5}
REBOOT_CMD=${ISORA_REBOOT_CMD:-sync; reboot -f}
# Backoff after the 1st, 2nd and later failures in a row.
set -- ${ISORA_DELAYS:-2 5 30}
D1=$1 D2=$2 D3=$3

LOG=$RUN/isora_main.log
PID=$RUN/isora_main.pid
ALIVE=$RUN/isora_alive
STOPPING=$RUN/isora_stopping
STOP=$RUN/isora_stop
RESPAWN=$RUN/isora_respawn
CHIME=$RUN/.boot_chime_played
REBOOTED=$STATE/.isora_autoreboot
SLOG=$STATE/isora_supervisor.log

# /tmp is RAM on this board: a stdout log that grows all day is memory the
# app no longer has. Trimmed in place (same inode), so the app's O_APPEND
# writes keep landing at the end.
LOG_MAX=2097152
LOG_KEEP=262144

uptime_s() { cut -d. -f1 /proc/uptime; }

trim() {   # FILE MAX KEEP
    size=$(wc -c < "$1" 2>/dev/null | tr -dc 0-9)
    [ "${size:-0}" -gt "$2" ] || return 0
    tail -c "$3" "$1" > "$1.trim" && cat "$1.trim" > "$1"
    rm -f "$1.trim"
}

say() {
    echo "[supervisor] $*" >> "$LOG"
    # The persistent log outlives a reboot, so a failure on stage can still be
    # read afterwards. Bounded.
    echo "$(date '+%Y-%m-%d %H:%M:%S') up $(uptime_s)s: $*" >> "$SLOG"
    trim "$SLOG" 65536 16384
}

reboot_once() {
    if [ -e "$REBOOTED" ]; then
        say "would reboot ($1), but already did since the last healthy run"
        return 1
    fi
    echo "$1" > "$REBOOTED"
    say "rebooting: $1"
    eval "$REBOOT_CMD"
}

watch_app() {   # APP_PID START_UPTIME
    trap - TERM INT
    healthy=0
    while kill -0 "$1" 2>/dev/null; do
        sleep "$POLL_S"
        kill -0 "$1" 2>/dev/null || return 0
        trim "$LOG" $LOG_MAX $LOG_KEEP
        # Shutting down on purpose: a slow camera release is not a wedge.
        [ -e "$STOPPING" ] && continue
        t=$(uptime_s)
        last=$(cut -d. -f1 "$ALIVE" 2>/dev/null)
        case "$last" in ''|*[!0-9]*) last= ;; esac
        if [ -n "$last" ]; then
            age=$((t - last))
            if [ "$age" -gt "$STALE_S" ]; then
                kill_wedged "$1" "no heartbeat for ${age}s"
                return 0
            fi
            if [ $healthy = 0 ] && [ $((t - $2)) -ge "$HEALTHY_S" ]; then
                healthy=1
                rm -f "$REBOOTED"
            fi
        elif [ $((t - $2)) -gt "$GRACE_S" ]; then
            kill_wedged "$1" "no heartbeat ${GRACE_S}s after start"
            return 0
        fi
    done
}

kill_wedged() {   # APP_PID REASON
    say "app wedged ($2) - killing pid $1"
    kill -9 "$1" 2>/dev/null
    i=0
    while kill -0 "$1" 2>/dev/null && [ $i -lt 15 ]; do
        sleep 1
        i=$((i + 1))
    done
    # Still there after SIGKILL: stuck inside a driver call (D state). Nothing
    # short of a reset frees the camera from that.
    if kill -0 "$1" 2>/dev/null; then
        reboot_once "pid $1 survived SIGKILL (stuck in a driver)"
    fi
}

# Children inherit the ignore, so an SSH session that started us can hang up.
trap '' HUP
# Stopped by S26isoraapp: end NOW, not after a backoff sleep, or a `restart`
# could start a second supervisor while this one still means to respawn. The
# app itself is the init script's to stop.
mon=
trap 'kill $mon 2>/dev/null; exit 0' TERM INT

# MaixPy userspace override (see tools/run.py APP_INIT_SCRIPT).
if [ -d /root/t451 ]; then
    export PYTHONPATH=/root/t451
    export LD_LIBRARY_PATH=/root/t451/lib
fi

fails=0
while [ ! -e "$STOP" ]; do
    if [ -f "$H" ] && { [ -e "$R/pending" ] || [ -e "$R/trial" ] \
                        || [ ! -f "$APP_DIR/main.py" ]; }; then
        python3 "$H" boot >/dev/null 2>&1
    fi
    rm -f "$ALIVE" "$STOPPING" "$RESPAWN"
    t0=$(uptime_s)
    # cd per start: /root/isora is a symlink the release helper may just have
    # moved to another release.
    ( cd "$APP_DIR" && exec $APP_CMD ) >> "$LOG" 2>&1 </dev/null &
    app=$!
    echo $app > "$PID"
    watch_app "$app" "$t0" </dev/null &
    mon=$!
    # A release on trial must confirm itself healthy in time or be rolled back.
    # One guard per start; it carries the trial as it reads NOW, so a guard
    # outliving its own start leaves the next one alone (release.py guard).
    if [ -f "$H" ] && [ -e "$R/trial" ]; then
        T=$(tr '\n' ' ' < "$R/trial")
        ( sleep "$GUARD_S"
          python3 "$H" guard "$T" >/dev/null 2>&1
          if [ $? -eq 3 ]; then touch "$RESPAWN"; kill "$app" 2>/dev/null; fi
        ) </dev/null >/dev/null 2>&1 &
    fi

    wait "$app"
    rc=$?
    kill "$mon" 2>/dev/null
    mon=

    [ -e "$STOP" ] && break
    if [ ! -e "$RESPAWN" ]; then
        case $rc in
            0|130|143)
                say "app exited ($rc) - stopping, not a crash"
                break ;;
        esac
    fi

    ran=$(($(uptime_s) - t0))
    if [ -e "$RESPAWN" ]; then
        fails=0
        delay=3
        say "release rolled back - starting the previous one"
    else
        if [ "$ran" -ge "$HEALTHY_S" ]; then fails=1; else fails=$((fails + 1)); fi
        case $fails in
            1) delay=$D1 ;;
            2) delay=$D2 ;;
            *) delay=$D3 ;;
        esac
        say "app died (exit $rc after ${ran}s, failure $fails in a row) - restarting in ${delay}s"
        if [ $fails -ge 3 ]; then
            reboot_once "app failed $fails times in a row"
        fi
    fi
    # Let the restarted app say "I-Sora menyala": the user has to know it is
    # back, and why it went quiet for a moment.
    rm -f "$CHIME"
    sleep "$delay" &
    wait $!
done
rm -f "$PID"
exit 0
