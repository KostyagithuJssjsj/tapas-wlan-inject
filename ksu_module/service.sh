#!/system/bin/sh
MODDIR=${0%/*}
[ -f "$MODDIR/qca_cld3_wlan.ko" ] || exit 0
i=0
while [ "$(getprop sys.boot_completed)" != "1" ] && [ $i -lt 60 ]; do
    sleep 1
    i=$((i+1))
done
sleep 5
svc wifi disable
sleep 3
rmmod wlan 2>/dev/null
sleep 1
insmod "$MODDIR/qca_cld3_wlan.ko"
sleep 2
svc wifi enable
