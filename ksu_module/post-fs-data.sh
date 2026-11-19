#!/system/bin/sh
MODDIR=${0%/*}
if [ -f "$MODDIR/qca_cld3_wlan.ko" ]; then
    mount --bind "$MODDIR/qca_cld3_wlan.ko" /vendor_dlkm/lib/modules/qca_cld3_wlan.ko
fi
