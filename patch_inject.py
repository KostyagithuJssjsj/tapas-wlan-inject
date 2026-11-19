import os, re, sys

root = sys.argv[1] if len(sys.argv) > 1 else "qcacld-3.0"
kbuild = os.path.join(root, "Kbuild")
hdd_main = os.path.join(root, "core/hdd/src/wlan_hdd_main.c")

if not os.path.exists(hdd_main):
    sys.exit(f"[ERR] Не найден файл {hdd_main}")

# 1. Включаем FEATURE_MONITOR_MODE_SUPPORT в Kbuild
if os.path.exists(kbuild):
    txt = open(kbuild).read()
    if "CONFIG_FEATURE_MONITOR_MODE_SUPPORT := y" not in txt:
        txt += "\nCONFIG_FEATURE_MONITOR_MODE_SUPPORT := y\nccflags-y += -DFEATURE_MONITOR_MODE_SUPPORT\n"
        open(kbuild, "w").write(txt)
        print("[OK] Kbuild обновлён")

# 2. Добавляем обработчик TX-инъекции в wlan_hdd_main.c
txt = open(hdd_main).read()
if "hdd_mon_inject_xmit" in txt:
    print("[SKIP] Патч уже применён")
    sys.exit(0)

inject_code = r"""
/* === BEGIN MONITOR TX INJECTION PATCH === */
#include <net/ieee80211_radiotap.h>
#include <linux/workqueue.h>

static struct sk_buff_head mon_tx_q;
static struct work_struct mon_tx_work;
static struct net_device *mon_tx_dev;
static bool mon_tx_inited;

static void hdd_mon_tx_worker(struct work_struct *work)
{
	struct sk_buff *skb;
	struct net_device *dev = mon_tx_dev;
	struct wireless_dev *wdev;
	struct cfg80211_mgmt_tx_params params;
	u64 cookie = 0;

	if (!dev || !dev->ieee80211_ptr)
		return;
	wdev = dev->ieee80211_ptr;

	while ((skb = skb_dequeue(&mon_tx_q)) != NULL) {
		memset(&params, 0, sizeof(params));
		params.buf = skb->data;
		params.len = skb->len;
		params.no_cck = true;
		params.dont_wait_for_ack = true;
		if (wdev->wiphy && wdev->wiphy->ops && wdev->wiphy->ops->mgmt_tx)
			wdev->wiphy->ops->mgmt_tx(wdev->wiphy, wdev, &params, &cookie);
		dev_kfree_skb_any(skb);
	}
}

static netdev_tx_t hdd_mon_inject_xmit(struct sk_buff *skb, struct net_device *dev)
{
	struct ieee80211_radiotap_header *rtap;
	u16 rtap_len;

	if (!mon_tx_inited) {
		skb_queue_head_init(&mon_tx_q);
		INIT_WORK(&mon_tx_work, hdd_mon_tx_worker);
		mon_tx_inited = true;
	}

	if (skb->len < sizeof(*rtap)) {
		dev_kfree_skb_any(skb);
		return NETDEV_TX_OK;
	}

	rtap = (struct ieee80211_radiotap_header *)skb->data;
	rtap_len = le16_to_cpu(rtap->it_len);
	if (rtap_len > skb->len || skb->len - rtap_len < 10) {
		dev_kfree_skb_any(skb);
		return NETDEV_TX_OK;
	}

	skb_pull(skb, rtap_len);
	mon_tx_dev = dev;
	if (skb_queue_len(&mon_tx_q) < 64) {
		skb_queue_tail(&mon_tx_q, skb);
		schedule_work(&mon_tx_work);
	} else {
		dev_kfree_skb_any(skb);
	}
	return NETDEV_TX_OK;
}
/* === END MONITOR TX INJECTION PATCH === */
"""

m = re.search(r'(static\s+const\s+struct\s+net_device_ops\s+mon_drv_ops\s*=\s*\{[^}]+\};)', txt, re.S)
if not m:
    sys.exit("[ERR] Структура mon_drv_ops не найдена в wlan_hdd_main.c")

block = m.group(1)
if ".ndo_start_xmit" in block:
    new_block = re.sub(r'\.ndo_start_xmit\s*=\s*[^,\n]+', '.ndo_start_xmit = hdd_mon_inject_xmit', block)
else:
    new_block = block.replace("{", "{\n\t.ndo_start_xmit = hdd_mon_inject_xmit,", 1)

txt = txt[:m.start()] + inject_code + "\n" + new_block + txt[m.end():]
open(hdd_main, "w").write(txt)
print("[OK] wlan_hdd_main.c пропатчен")
