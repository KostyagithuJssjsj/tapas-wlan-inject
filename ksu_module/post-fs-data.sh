#!/system/bin/sh
MODDIR=${0%/*}
KO="$MODDIR/vendor_dlkm/lib/modules/qca_cld3_wlan.ko"
[ -f "$KO" ] || KO="$MODDIR/qca_cld3_wlan.ko"
if [ -f "$KO" ]; then
    chcon u:object_r:vendor_file:s0 "$KO" 2>/dev/null
    mount --bind "$KO" /vendor_dlkm/lib/modules/qca_cld3_wlan.ko
fi
