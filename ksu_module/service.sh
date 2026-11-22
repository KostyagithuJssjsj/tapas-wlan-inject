#!/system/bin/sh
MODDIR=${0%/*}
LOG=/data/local/tmp/tapas_ksu.log
KO="$MODDIR/vendor_dlkm/lib/modules/qca_cld3_wlan.ko"
[ -f "$KO" ] || KO="$MODDIR/qca_cld3_wlan.ko"
[ -f "$KO" ] || { echo "KO not found in $MODDIR" > "$LOG"; exit 0; }

i=0
while [ "$(getprop sys.boot_completed)" != "1" ] && [ $i -lt 60 ]; do
    sleep 1
    i=$((i+1))
done
sleep 5

svc wifi disable
sleep 3

r=0
while grep -q "^wlan " /proc/modules && [ $r -lt 10 ]; do
    rmmod wlan 2>/dev/null && break
    sleep 1
    r=$((r+1))
done

insmod "$KO"
RC=$?
echo "$(date): KO=$KO rmmod_tries=$r insmod_rc=$RC" > "$LOG"

sleep 2
svc wifi enable
