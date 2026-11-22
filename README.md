# tapas-wlan-inject (`qca_cld3_wlan.ko`)

Пропатченный модуль Wi-Fi ядра Linux (`qcacld-3.0`) для **Xiaomi Redmi Note 12 4G (`tapas`)** на базе **Snapdragon 685 (SM6225)** и встроенного Wi-Fi-чипа **Qualcomm WCN3988 (Adrastea)**.

Patched Linux kernel Wi-Fi module (`qcacld-3.0`) for **Xiaomi Redmi Note 12 4G (`tapas`)** powered by **Snapdragon 685 (SM6225)** and the built-in **Qualcomm WCN3988 (Adrastea)** wireless chip.

## Русский

### Что делает этот `.ko`-файл и зачем он нужен

Стоковый драйвер Wi-Fi в Android (`qca_cld3_wlan.ko`) на Snapdragon 685 рассчитан только на обычный клиентский режим и в лучшем случае отдаёт ограниченный пассивный перехват (RX). Отправлять произвольные 802.11-кадры (packet injection), полноценно управлять монитором через `iw` или переключать каналы/ширину полосы на встроенном Wi-Fi он не даёт — обычно приходится носить внешний USB-адаптер через OTG.

**`tapas-wlan-inject`** собирает совместимый с GKI 2.0 (ядро 5.15) модуль `qca_cld3_wlan.ko`, который открывает **полноценный Monitor Mode и raw-инъекцию кадров прямо на встроенном Wi-Fi-чипе телефона**, без внешних адаптеров и без постоянной замены системных файлов прошивки.

### Что умеет пропатченный драйвер

| Возможность | Реализация |
| :--- | :--- |
| **Monitor Mode (`nl80211`)** | `NL80211_IFTYPE_MONITOR` добавлен в `wiphy->interface_modes` (`* monitor` виден в `iw phy`); `iw dev wlan0 set type monitor` / `managed` работает асинхронно вне `rtnl_lock` (`RC=0`). |
| **Инъекция кадров (TX)** | Передача raw 802.11-кадров с radiotap через скрытый `vdev_id=1` (`WMI_VDEV_TYPE_STA`) и `WMI_MGMT_TX` (`wmi_mgmt_unified_cmd_send`) с очередью `mon_tx_q` (512), пулом на 64 слота и backpressure при `-EBUSY`. |
| **Перехват (RX)** | Штатный `hdd_mon_rx_packet_cbk` с radiotap; при открытии интерфейса отключаются фоновое сканирование и idle-таймер. |
| **Каналы и ширина** | Поддержка **2.4 и 5 ГГц**, ширина **20 / 40 / 80 МГц** (`WMI_HOST_MODE_11G/11NG_HT20/11NG_HT40/11A/11NA_HT20/11NA_HT40/11AC_VHT80`). |
| **Смена MAC в мониторе** | Реализован `.ndo_set_mac_address` с валидацией и обновлением MAC скрытого `vdev_id=1`. |
| **Стабильность** | Закрыта утечка SMMU IOVA (строго 1 map ↔ 1 unmap на кадр), убраны утечка `nbuf` (`SUnreclaim` не растёт) и гонка `send ↔ completion`, мягкий рефреш `vdev_id=1` каждые 20 000 кадров. |

### Требования и безопасное использование

* **Устройство / ядро:** Redmi Note 12 4G (`tapas`, SM6225, WCN3988), Android GKI 2.0 `5.15.x` (`MODVERSIONS`, `CFI`, `LTO`, `BTF`, `SCS`), root (KernelSU / Magisk) + Termux.
* **Сборка:** AOSP Android Clang 14.0.7 (`clang-r450784e`) + `dwarves` (`pahole`) через GitHub Actions.
* **Загрузка без замены стока:** выключите Wi-Fi (`svc wifi disable`), выгрузите сток (`rmmod wlan`), загрузите собранный `.ko` из `/data/local/tmp/` (`insmod`) и переведите `wlan0` в `monitor`. После работы сделайте `rmmod wlan && svc wifi enable` — Android Wi-Fi HAL сам вернёт стоковый `/vendor_dlkm/lib/modules/qca_cld3_wlan.ko`.
* **Другие прошивки (PixelOS / LineageOS / HyperOS на 5.15):** `patch_inject.py` переписывать не нужно — достаточно обновить `device_symvers.txt` (и при необходимости заголовки ядра под HyperOS) и пересобрать в GitHub Actions.

> Только для исследований драйверов Linux, изучения `qcacld-3.0` / `nl80211` и тестирования безопасности **собственных сетей и устройств**.

## English

### What This `.ko` File Does and Why It Exists

The stock Android Wi-Fi kernel driver (`qca_cld3_wlan.ko`) on Snapdragon 685 only supports normal client mode and at most limited passive capture. It does not allow raw 802.11 frame injection or full `nl80211` monitor control on the built-in radio, usually requiring an external USB Wi-Fi adapter via OTG.

**`tapas-wlan-inject`** builds a GKI 2.0 (Linux 5.15) compatible `qca_cld3_wlan.ko` module that unlocks **full Monitor Mode and raw packet injection directly on the internal WCN3988 chip**, with no external adapter and no permanent changes to `/vendor_dlkm`.

### Key Features

| Feature | Implementation |
| :--- | :--- |
| **Monitor Mode (`nl80211`)** | Exposes `NL80211_IFTYPE_MONITOR` in `wiphy->interface_modes` (`* monitor` in `iw phy`); `iw dev wlan0 set type monitor` / `managed` runs asynchronously outside `rtnl_lock` (`RC=0`). |
| **Frame Injection (TX)** | Injects radiotap-stripped raw 802.11 frames via hidden `vdev_id=1` (`WMI_VDEV_TYPE_STA`) and `WMI_MGMT_TX` (`wmi_mgmt_unified_cmd_send`) with a 512-frame `mon_tx_q`, 64-slot descriptor pool, and `-EBUSY` backpressure. |
| **Packet Capture (RX)** | Native `hdd_mon_rx_packet_cbk` with radiotap headers; stops idle timer and aborts background scans on open. |
| **Channel & Bandwidth** | Supports **2.4 GHz & 5 GHz**, **20 / 40 / 80 MHz** (`WMI_HOST_MODE_11G/11NG_HT20/11NG_HT40/11A/11NA_HT20/11NA_HT40/11AC_VHT80`). |
| **MAC Spoofing** | Implements `.ndo_set_mac_address` with validation and hidden `vdev_id=1` MAC sync. |
| **Stability** | Fixes SMMU IOVA leak (strict 1:1 DMA map/unmap), eliminates `nbuf` leaks (`SUnreclaim` stays flat) and `send <-> completion` races, plus soft `vdev_id=1` refresh every 20,000 frames. |

### Requirements & Safe Usage

* **Device / Kernel:** Redmi Note 12 4G (`tapas`, SM6225, WCN3988), Android GKI 2.0 `5.15.x` (`MODVERSIONS`, `CFI`, `LTO`, `BTF`, `SCS`), root (KernelSU / Magisk) + Termux.
* **Build:** AOSP Android Clang 14.0.7 (`clang-r450784e`) + `dwarves` (`pahole`) via GitHub Actions.
* **Safe manual loading:** disable Wi-Fi (`svc wifi disable`), unload stock (`rmmod wlan`), `insmod` the built `.ko` from `/data/local/tmp/`, and switch `wlan0` to `monitor`. When done, run `rmmod wlan && svc wifi enable` — Android Wi-Fi HAL automatically restores stock `/vendor_dlkm/lib/modules/qca_cld3_wlan.ko`.
* **Other 5.15 ROMs (PixelOS / LineageOS / HyperOS):** no changes to `patch_inject.py` needed — just update `device_symvers.txt` (and kernel headers for HyperOS if required) and rebuild in GitHub Actions.

> For Linux driver research, `qcacld-3.0` / `nl80211` study, and authorized security testing on **your own devices and networks** only.
