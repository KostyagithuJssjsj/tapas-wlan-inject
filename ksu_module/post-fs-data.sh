#!/system/bin/sh
MODDIR=${0%/*}
if [ -f "$MODDIR/qca_cld3_wlan.ko" ]; then
    chcon u:object_r:vendor_file:s0 "$MODDIR/qca_cld3_wlan.ko" 2>/dev/null
    mount --bind "$MODDIR/qca_cld3_wlan.ko" /vendor_dlkm/lib/modules/qca_cld3_wlan.ko
fi
