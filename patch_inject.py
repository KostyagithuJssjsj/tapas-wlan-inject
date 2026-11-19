import os, re, sys

root = sys.argv[1] if len(sys.argv) > 1 else "qcacld-3.0"
kbuild = os.path.join(root, "Kbuild")

# 1. Включаем поддержку режима мониторинга в Kbuild
if os.path.exists(kbuild):
    txt = open(kbuild).read()
    if "CONFIG_FEATURE_MONITOR_MODE_SUPPORT := y" not in txt:
        txt += "\nCONFIG_FEATURE_MONITOR_MODE_SUPPORT := y\nccflags-y += -DFEATURE_MONITOR_MODE_SUPPORT\n"
        open(kbuild, "w").write(txt)
        print("[OK] Kbuild обновлён")

# 2. Экспортируем обёртку hdd_mon_call_mgmt_tx из wlan_hdd_cfg80211.c
cfg_file = os.path.join(root, "core/hdd/src/wlan_hdd_cfg80211.c")
if os.path.exists(cfg_file):
    cfg_txt = open(cfg_file, errors="ignore").read()
    if "hdd_mon_call_mgmt_tx" not in cfg_txt:
        m_ops = re.search(r'struct\s+cfg80211_ops\s+(\w+)\s*=', cfg_txt)
        if not m_ops:
            print("[ERR] struct cfg80211_ops не найдена в wlan_hdd_cfg80211.c")
            sys.exit(1)
        ops_name = m_ops.group(1)
        wrapper = f"""
/* === BEGIN MONITOR MGMT_TX WRAPPER === */
int hdd_mon_call_mgmt_tx(struct wiphy *wiphy, struct wireless_dev *wdev,
\t\t\t struct cfg80211_mgmt_tx_params *params, u64 *cookie)
{{
\tif ({ops_name}.mgmt_tx)
\t\treturn {ops_name}.mgmt_tx(wiphy, wdev, params, cookie);
\treturn -EOPNOTSUPP;
}}
/* === END MONITOR MGMT_TX WRAPPER === */
"""
        open(cfg_file, "w").write(cfg_txt + wrapper)
        print(f"[OK] Добавлена обёртка hdd_mon_call_mgmt_tx через {ops_name}")

# 3. Ищем структуру net_device_ops для монитора по всей папке core/hdd
hdd_dir = os.path.join(root, "core/hdd")
patterns = [
    re.compile(r'((?:static\s+)?(?:const\s+)?struct\s+net_device_ops\s+\w+\s*=\s*\{[^}]*hdd_mon_open[^}]*\};)', re.S),
    re.compile(r'((?:static\s+)?(?:const\s+)?struct\s+net_device_ops\s+\w*mon\w*\s*=\s*\{[^}]+\};)', re.S),
]

target_file = None
match = None

for pat in patterns:
    for dirpath, _, filenames in os.walk(hdd_dir):
        for fn in sorted(filenames):
            if not fn.endswith(".c"):
                continue
            fp = os.path.join(dirpath, fn)
            txt = open(fp, errors="ignore").read()
            if "hdd_mon_inject_xmit" in txt:
                print(f"[SKIP] Уже пропатчено: {fp}")
                sys.exit(0)
            m = pat.search(txt)
            if m:
                target_file = fp
                match = m
                break
        if match:
            break
    if match:
        break

if not match:
    print("[ERR] Структура net_device_ops для мониторинга не найдена.")
    sys.exit(1)

print(f"[OK] Найдена структура мониторинга в: {target_file}")
txt = open(target_file).read()

headers = "\n#include <net/cfg80211.h>\n#include <net/ieee80211_radiotap.h>\n#include <linux/workqueue.h>\n"
inject_code = r"""
/* === BEGIN MONITOR TX INJECTION PATCH === */
extern int hdd_mon_call_mgmt_tx(struct wiphy *wiphy, struct wireless_dev *wdev,
				struct cfg80211_mgmt_tx_params *params, u64 *cookie);

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
		if (wdev->preset_chandef.chan)
			params.chan = wdev->preset_chandef.chan;
		else if (wdev->wiphy && wdev->wiphy->bands[NL80211_BAND_2GHZ])
			params.chan = &wdev->wiphy->bands[NL80211_BAND_2GHZ]->channels[0];
		if (wdev->wiphy)
			hdd_mon_call_mgmt_tx(wdev->wiphy, wdev, &params, &cookie);
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

block = match.group(1)
if ".ndo_start_xmit" in block:
    new_block = re.sub(r'\.ndo_start_xmit\s*=\s*[^,\n]+', '.ndo_start_xmit = hdd_mon_inject_xmit', block)
else:
    new_block = block.replace("{", "{\n\t.ndo_start_xmit = hdd_mon_inject_xmit,", 1)

txt = txt[:match.start()] + inject_code + "\n" + new_block + txt[match.end():]

inc_m = re.search(r'^\s*#include\s+.*$', txt, re.M)
if inc_m:
    txt = txt[:inc_m.end()] + headers + txt[inc_m.end():]
else:
    txt = headers + txt

open(target_file, "w").write(txt)
print("[OK] Патч TX-инъекции применён")
