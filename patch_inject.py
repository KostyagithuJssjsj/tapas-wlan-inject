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

# Автоопределяем точные имена WMI API в текущем qcacld-3.0 (5.15)
wmi_api_txt = ""
for fn in ["cmn/wmi/inc/wmi_unified_api.h", "cmn/wmi/inc/wmi_unified_param.h",
           "cmn/wmi/inc/wmi_unified_vdev_api.h", "cmn/wmi/inc/wmi_unified_vdev_param.h"]:
    fp = os.path.join(root, fn)
    if os.path.exists(fp):
        wmi_api_txt += open(fp, errors="ignore").read() + "\n"

if "wmi_mgmt_unified_cmd_send" in wmi_api_txt:
    mgmt_send_fn = "wmi_mgmt_unified_cmd_send"
else:
    mgmt_send_fn = "wmi_unified_mgmt_tx_cmd_send"

m_vc = re.search(r'struct\s+vdev_create_params\s*\{([^}]+)\}', wmi_api_txt, re.S)
vc_id_field = "vdev_id" if (m_vc and "vdev_id" in m_vc.group(1)) else "if_id"
cf1_field = "cfreq1"
for dp, _, fns in os.walk(os.path.join(root, "cmn")):
    for fn in fns:
        if fn.endswith(".h"):
            t = open(os.path.join(dp, fn), errors="ignore").read()
            m_ch = re.search(r'struct\s+mlme_channel_param\s*\{([^}]+)\}', t, re.S)
            if m_ch:
                cf1_field = "band_center_freq1" if "band_center_freq1" in m_ch.group(1) else "cfreq1"
                break
print(f"[INFO] WMI API: {mgmt_send_fn}, vdev_create_params.{vc_id_field}, mlme_channel_param.{cf1_field}")
cdp_uses_vdev_info = False
for dp, _, fns in os.walk(os.path.join(root, "cmn/dp/inc")):
    for fn in fns:
        if fn.endswith(".h"):
            t = open(os.path.join(dp, fn), errors="ignore").read()
            if "cdp_vdev_attach" in t and "cdp_vdev_info" in t:
                cdp_uses_vdev_info = True
                break
if cdp_uses_vdev_info:
    cdp_attach_code = r"""		{
			void *cdp_soc = cds_get_context(QDF_MODULE_ID_SOC);
			struct cdp_vdev_info vi;
			if (cdp_soc) {
				qdf_mem_zero(&vi, sizeof(vi));
				vi.vdev_mac_addr = mac;
				vi.vdev_id = vdev_id;
				vi.op_mode = wlan_op_mode_sta;
				pr_info("MON_INJ: cdp_vdev_attach(vi) vdev=%u st=%d\n", vdev_id, cdp_vdev_attach(cdp_soc, 0, &vi));
			}
		}"""
else:
    cdp_attach_code = r"""		{
			void *cdp_soc = cds_get_context(QDF_MODULE_ID_SOC);
			if (cdp_soc)
				pr_info("MON_INJ: cdp_vdev_attach vdev=%u st=%d\n", vdev_id, cdp_vdev_attach(cdp_soc, 0, mac, vdev_id, wlan_op_mode_sta));
		}"""
print(f"[INFO] cdp_uses_vdev_info={cdp_uses_vdev_info}")
cdp_attach_code = ""

# 2. В core/wma/src/wma_dev_if.c добавляем обход @Loukious (hidden STA vdev + self-peer + WMI_MGMT_TX)
wma_file = os.path.join(root, "core/wma/src/wma_dev_if.c")
if os.path.exists(wma_file):
    wma_txt = open(wma_file, errors="ignore").read()
    if "wma_mon_inject_raw_frame" not in wma_txt:
        wma_code = f"""
/* === BEGIN LOUKIOUS HIDDEN-STA VDEV INJECTION BYPASS === */
#include <linux/spinlock.h>
#include "wmi_unified_api.h"

#define MON_INJ_DESC_MAGIC 0xE000U
#define MON_INJ_DESC_SLOTS 64U
#define MON_INJ_DESC_MASK  (MON_INJ_DESC_SLOTS - 1U)

static uint8_t wma_mon_inject_vdev_id = 1;
static bool wma_mon_inject_vdev_ready;
static uint32_t wma_mon_inject_last_freq;
static int wma_mon_inject_log_cnt;
static int wma_mon_inject_err_cnt;
static uint32_t wma_mon_desc_cursor;
static DEFINE_SPINLOCK(wma_mon_nbuf_lock);
static qdf_nbuf_t wma_mon_nbufs[MON_INJ_DESC_SLOTS];

bool wma_mon_inject_handle_compl(tp_wma_handle wma, uint32_t desc_id)
{{
	unsigned long flags;
	qdf_nbuf_t nbuf = NULL;
	uint32_t slot;

	if ((desc_id & ~MON_INJ_DESC_MASK) != MON_INJ_DESC_MAGIC)
		return false;

	slot = desc_id & MON_INJ_DESC_MASK;
	spin_lock_irqsave(&wma_mon_nbuf_lock, flags);
	nbuf = wma_mon_nbufs[slot];
	wma_mon_nbufs[slot] = NULL;
	spin_unlock_irqrestore(&wma_mon_nbuf_lock, flags);

	if (nbuf) {{
		if (wma && wma->qdf_dev)
			qdf_nbuf_unmap_single(wma->qdf_dev, nbuf, QDF_DMA_TO_DEVICE);
		qdf_nbuf_free(nbuf);
	}}
	return true;
}}

void wma_mon_inject_reset(void)
{{
	tp_wma_handle wma = cds_get_context(QDF_MODULE_ID_WMA);
	unsigned long flags;
	qdf_nbuf_t leftover[MON_INJ_DESC_SLOTS];
	uint32_t i;

	wma_mon_inject_vdev_ready = false;
	qdf_mdelay(20);

	spin_lock_irqsave(&wma_mon_nbuf_lock, flags);
	for (i = 0; i < MON_INJ_DESC_SLOTS; i++) {{
		leftover[i] = wma_mon_nbufs[i];
		wma_mon_nbufs[i] = NULL;
	}}
	spin_unlock_irqrestore(&wma_mon_nbuf_lock, flags);

	for (i = 0; i < MON_INJ_DESC_SLOTS; i++) {{
		if (leftover[i]) {{
			if (wma && wma->qdf_dev)
				qdf_nbuf_unmap_single(wma->qdf_dev, leftover[i], QDF_DMA_TO_DEVICE);
			qdf_nbuf_free(leftover[i]);
		}}
	}}
}}

static QDF_STATUS wma_create_mon_inject_vdev(tp_wma_handle wma, uint32_t freq)
{{
\tstruct vdev_create_params create_params;
\tstruct vdev_start_params start_params;
\tstruct peer_create_params peer_params;
\tstruct vdev_up_params up_params;
\tuint8_t mac[6] = {{0x02, 0x00, 0x00, 0x11, 0x22, 0x33}};
\tuint8_t vdev_id = wma_mon_inject_vdev_id;
\tQDF_STATUS status;

\tif (!wma || !wma->wmi_handle)
\t\treturn QDF_STATUS_E_INVAL;

\tif (freq == 0)
\t\tfreq = 2412;

\tif (wma_mon_inject_vdev_ready && wma_mon_inject_last_freq == freq)
\t\treturn QDF_STATUS_SUCCESS;

\tif (!wma_mon_inject_vdev_ready) {{
\t\tqdf_mem_zero(&create_params, sizeof(create_params));
\t\tcreate_params.vdev_id = vdev_id;
\t\tcreate_params.type = WMI_VDEV_TYPE_STA;
\t\tcreate_params.subtype = 0;
\t\tcreate_params.nss_2g = 1;
\t\tcreate_params.nss_5g = 1;
\t\tcreate_params.pdev_id = 0;

\t\tpr_info("MON_INJ: creating hidden STA vdev_id=%u\\n", vdev_id);
\t\tstatus = wmi_unified_vdev_create_send(wma->wmi_handle, mac, &create_params);
\t\tif (QDF_IS_STATUS_ERROR(status)) {{
\t\t\tpr_err("MON_INJ: vdev_create failed: %d\\n", status);
\t\t\treturn status;
\t\t}}

\t\tqdf_mem_zero(&peer_params, sizeof(peer_params));
\t\tpeer_params.peer_addr = mac;
\t\tpeer_params.peer_type = WMI_PEER_TYPE_DEFAULT;
\t\tpeer_params.vdev_id = vdev_id;
\t\tstatus = wmi_unified_peer_create_send(wma->wmi_handle, &peer_params);
\t\tif (QDF_IS_STATUS_ERROR(status))
\t\t\tpr_warn("MON_INJ: self-peer create failed: %d\\n", status);

{cdp_attach_code}
		qdf_mdelay(15);
\t}} else {{
\t\tpr_info("MON_INJ: channel change %u -> %u on vdev_id=%u\\n",
\t\t\twma_mon_inject_last_freq, freq, vdev_id);
\t\twmi_unified_vdev_stop_send(wma->wmi_handle, vdev_id);
\t\tqdf_mdelay(10);
\t}}

\tqdf_mem_zero(&start_params, sizeof(start_params));
\tstart_params.vdev_id = vdev_id;
\tstart_params.channel.mhz = freq;
\tstart_params.channel.{cf1_field} = freq;
\t\tstart_params.channel.phy_mode = (freq < 5000) ? WMI_HOST_MODE_11G : WMI_HOST_MODE_11A;
\tstart_params.channel.maxregpower = 20;
\tstart_params.channel.maxpower = 20;
\tstart_params.channel.minpower = 0;
\tstart_params.beacon_interval = 100;
\tstart_params.dtim_period = 1;

\tpr_info("MON_INJ: starting hidden STA vdev_id=%u freq=%u\\n", vdev_id, freq);
\tstatus = wmi_unified_vdev_start_send(wma->wmi_handle, &start_params);
\tif (QDF_IS_STATUS_ERROR(status)) {{
\t\tpr_err("MON_INJ: vdev_start failed: %d\\n", status);
\t\treturn status;
\t}}
\tqdf_mdelay(20);

\tif (!wma_mon_inject_vdev_ready) {{
\t\tqdf_mem_zero(&up_params, sizeof(up_params));
\t\tup_params.vdev_id = vdev_id;
\t\tup_params.assoc_id = 1;
	/* SKIP VDEV_UP: FW asserts in wlan_vdev_up without BSS peer */
	(void)up_params;
\t\tif (QDF_IS_STATUS_ERROR(status))
\t\t\tpr_warn("MON_INJ: vdev_up failed: %d\\n", status);
\t\tqdf_mdelay(10);
\t}}

\twma_mon_inject_vdev_ready = true;
\twma_mon_inject_last_freq = freq;
\tpr_info("MON_INJ: hidden STA vdev_id=%u READY on freq=%u!\\n", vdev_id, freq);
\treturn QDF_STATUS_SUCCESS;
}}

int wma_mon_inject_raw_frame(const uint8_t *frame_data, size_t frame_len, uint32_t freq)
{{
	tp_wma_handle wma;
	struct wmi_mgmt_params tx_params;
	qdf_nbuf_t nbuf;
	QDF_STATUS status;
	unsigned long flags;
	uint32_t i, slot = MON_INJ_DESC_SLOTS;

	wma = cds_get_context(QDF_MODULE_ID_WMA);
	if (!wma || !wma->wmi_handle || !frame_data || frame_len < 10)
		return -EINVAL;

	status = wma_create_mon_inject_vdev(wma, freq);
	if (QDF_IS_STATUS_ERROR(status))
		return -EIO;

	nbuf = qdf_nbuf_alloc(NULL, frame_len + 64, 32, 4, false);
	if (!nbuf)
		return -ENOMEM;

	qdf_nbuf_put_tail(nbuf, frame_len);
	qdf_mem_copy(qdf_nbuf_data(nbuf), frame_data, frame_len);

	status = qdf_nbuf_map_single(wma->qdf_dev, nbuf, QDF_DMA_TO_DEVICE);
	if (QDF_IS_STATUS_ERROR(status)) {{
		qdf_nbuf_free(nbuf);
		return -EIO;
	}}

	spin_lock_irqsave(&wma_mon_nbuf_lock, flags);
	for (i = 0; i < MON_INJ_DESC_SLOTS; i++) {{
		uint32_t cand = (wma_mon_desc_cursor + i) & MON_INJ_DESC_MASK;
		if (!wma_mon_nbufs[cand]) {{
			wma_mon_nbufs[cand] = nbuf;
			wma_mon_desc_cursor = (cand + 1U) & MON_INJ_DESC_MASK;
			slot = cand;
			break;
		}}
	}}
	spin_unlock_irqrestore(&wma_mon_nbuf_lock, flags);

	if (slot >= MON_INJ_DESC_SLOTS) {{
		qdf_nbuf_unmap_single(wma->qdf_dev, nbuf, QDF_DMA_TO_DEVICE);
		qdf_nbuf_free(nbuf);
		return -EBUSY;
	}}

	qdf_mem_zero(&tx_params, sizeof(tx_params));
	tx_params.vdev_id = wma_mon_inject_vdev_id;
	tx_params.tx_frame = nbuf;
	tx_params.frm_len = frame_len;
	tx_params.qdf_ctx = wma->qdf_dev;
	tx_params.chanfreq = freq ? freq : 2412;
	tx_params.desc_id = MON_INJ_DESC_MAGIC | slot;
	tx_params.pdata = qdf_nbuf_data(nbuf);
	tx_params.tx_flags = 0;

	status = {mgmt_send_fn}(wma->wmi_handle, &tx_params);
	if (wma_mon_inject_log_cnt < 10) {{
		wma_mon_inject_log_cnt++;
		pr_info("MON_INJ: WMI_MGMT_TX vdev=%u len=%zu freq=%u desc=0x%x status=%d\n",
			tx_params.vdev_id, frame_len, tx_params.chanfreq, tx_params.desc_id, status);
	}}
	if (QDF_IS_STATUS_ERROR(status)) {{
		qdf_nbuf_t to_free = NULL;
		spin_lock_irqsave(&wma_mon_nbuf_lock, flags);
		if (wma_mon_nbufs[slot] == nbuf) {{
			to_free = nbuf;
			wma_mon_nbufs[slot] = NULL;
		}}
		spin_unlock_irqrestore(&wma_mon_nbuf_lock, flags);
		if (to_free) {{
			qdf_nbuf_unmap_single(wma->qdf_dev, to_free, QDF_DMA_TO_DEVICE);
			qdf_nbuf_free(to_free);
		}}
		if (wma_mon_inject_err_cnt < 10) {{
			wma_mon_inject_err_cnt++;
			pr_warn("MON_INJ: WMI_MGMT_TX err=%d\n", status);
		}}
		return -EIO;
	}}
	return 0;
}}
/* === END LOUKIOUS HIDDEN-STA VDEV INJECTION BYPASS === */
"""
        open(wma_file, "w").write(wma_txt + wma_code)
        print("[OK] Добавлен обход @Loukious (hidden STA vdev) в wma_dev_if.c")

# 2b. Перехватываем completion наших desc_id (0xE000..0xE03F) в wma_mgmt.c
wma_src_dir = os.path.join(root, "core/wma/src")
if os.path.isdir(wma_src_dir):
    for fn in sorted(os.listdir(wma_src_dir)):
        if not fn.endswith(".c") or fn == "wma_dev_if.c":
            continue
        fp = os.path.join(wma_src_dir, fn)
        t = open(fp, errors="ignore").read()
        m = re.search(r'((?:static\s+)?int\s+wma_process_mgmt_tx_completion\s*\(([^)]+)\)\s*\{)', t, re.S)
        if not m or "wma_mon_inject_handle_compl" in t:
            continue
        ps = [x.strip() for x in m.group(2).split(",")]
        wma_v = re.findall(r'\b(\w+)\b', ps[0])[-1]
        desc_v = re.findall(r'\b(\w+)\b', ps[1])[-1]
        m_st = re.search(r'\n([ \t]+)(if\s*\(|pdev\s*=|status\s*=|wma_debug)', t[m.end():m.end()+1500])
        if m_st:
            ind = m_st.group(1)
            pos = m.end() + m_st.start()
            ext = "\nextern bool wma_mon_inject_handle_compl(tp_wma_handle wma, uint32_t desc_id);\n"
            chk = f"\n{ind}if (wma_mon_inject_handle_compl({wma_v}, {desc_v}))\n{ind}\treturn 0;\n"
            open(fp, "w").write(t[:m.start()] + ext + t[m.start():pos] + chk + t[pos:])
            print(f"[OK] Перехвачен wma_process_mgmt_tx_completion в {fn} ({wma_v}, {desc_v})")
            break

# 3. В wlan_hdd_cfg80211.c перехватываем set_monitor_channel и экспортируем частоту
cfg_file = os.path.join(root, "core/hdd/src/wlan_hdd_cfg80211.c")
if os.path.exists(cfg_file):
    cfg_txt = open(cfg_file, errors="ignore").read()
    if "hdd_mon_get_saved_freq" not in cfg_txt:
        m_ops = re.search(r'(?:static\s+)?(?:const\s+)?struct\s+cfg80211_ops\s+(\w+)\s*=', cfg_txt)
        if not m_ops:
            print("[ERR] struct cfg80211_ops не найдена")
            sys.exit(1)
        m_smc = re.search(r'(\.set_monitor_channel\s*=\s*)(\w+)', cfg_txt)
        if m_smc:
            orig_smc = m_smc.group(2)
            smc_hook_decl = f"""
static uint32_t mon_saved_freq = 2412;
uint32_t hdd_mon_get_saved_freq(void) {{ return mon_saved_freq; }}
static int hdd_mon_set_chan_hook(struct wiphy *wiphy, struct cfg80211_chan_def *chandef)
{{
\tif (chandef && chandef->chan) {{
\t\tmon_saved_freq = chandef->chan->center_freq;
\t\tpr_info("MON_INJ: set_monitor_channel freq=%u\\n", mon_saved_freq);
\t}}
\treturn {orig_smc}(wiphy, chandef);
}}
"""
            cfg_txt = cfg_txt[:m_ops.start()] + smc_hook_decl + "\n" + cfg_txt[m_ops.start():]
            cfg_txt = re.sub(r'(\.set_monitor_channel\s*=\s*)' + re.escape(orig_smc),
                             r'\1hdd_mon_set_chan_hook', cfg_txt, count=1)
        else:
            cfg_txt = cfg_txt[:m_ops.start()] + "\nuint32_t hdd_mon_get_saved_freq(void) { return 2412; }\n" + cfg_txt[m_ops.start():]
        open(cfg_file, "w").write(cfg_txt)
        print("[OK] Перехвачен set_monitor_channel в wlan_hdd_cfg80211.c")

# 4. В wlan_hdd_main.c будим TX-очередь монитора и шлём кадры в wma_mon_inject_raw_frame
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

txt = open(target_file).read()
headers = "\n#include <net/cfg80211.h>\n#include <net/ieee80211_radiotap.h>\n#include <linux/workqueue.h>\n"
inject_code = r"""
/* === BEGIN MONITOR TX INJECTION PATCH (LOUKIOUS WMI BYPASS) === */
extern int wma_mon_inject_raw_frame(const uint8_t *frame_data, size_t frame_len, uint32_t freq);
extern uint32_t hdd_mon_get_saved_freq(void);
extern void wma_mon_inject_reset(void);

static struct sk_buff_head mon_tx_q;
static struct work_struct mon_tx_work;
static bool mon_tx_inited;
static int mon_xmit_log_cnt;

static int hdd_mon_open_hook(struct net_device *dev)
{
	int rc = hdd_mon_open(dev);
	pr_info("MON_INJ: hdd_mon_open_hook rc=%d\n", rc);
	if (rc == 0) {
		netif_carrier_on(dev);
		netif_tx_start_all_queues(dev);
	}
	return rc;
}

static void hdd_mon_tx_worker(struct work_struct *work)
{
	struct sk_buff *skb;
	uint32_t freq = hdd_mon_get_saved_freq();

	while ((skb = skb_dequeue(&mon_tx_q)) != NULL) {
		wma_mon_inject_raw_frame(skb->data, skb->len, freq);
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
	if (rtap_len < sizeof(*rtap) || rtap_len > skb->len || skb->len - rtap_len < 10) {
		dev_kfree_skb_any(skb);
		return NETDEV_TX_OK;
	}

	if (mon_xmit_log_cnt < 5) {
		mon_xmit_log_cnt++;
		pr_info("MON_INJ: xmit skb_len=%u rtap=%u\n", skb->len, rtap_len);
	}

	skb_pull(skb, rtap_len);
	if (skb_queue_len(&mon_tx_q) < 256) {
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
new_block = re.sub(r'\.ndo_open\s*=\s*hdd_mon_open\b', '.ndo_open = hdd_mon_open_hook', new_block)
m_stop = re.search(r'\.ndo_stop\s*=\s*(\w+)', new_block)
if m_stop and "hdd_mon_stop_hook" not in inject_code:
    orig_stop = m_stop.group(1)
    inject_code += f'''
static int hdd_mon_stop_hook(struct net_device *dev)
{{
	if (mon_tx_inited) {{
		cancel_work_sync(&mon_tx_work);
		skb_queue_purge(&mon_tx_q);
	}}
	wma_mon_inject_reset();
	return {orig_stop}(dev);
}}
'''
    new_block = re.sub(r'\.ndo_stop\s*=\s*' + orig_stop + r'\b', '.ndo_stop = hdd_mon_stop_hook', new_block)


txt = txt[:match.start()] + inject_code + "\n" + new_block + txt[match.end():]

inc_m = re.search(r'^\s*#include\s+.*$', txt, re.M)
if inc_m:
    txt = txt[:inc_m.end()] + headers + txt[inc_m.end():]
else:
    txt = headers + txt

open(target_file, "w").write(txt)
print("[OK] Патч TX-инъекции (@Loukious WMI hidden STA vdev) применён")
