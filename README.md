# tapas-wlan-inject (`qca_cld3_wlan.ko`)

Пропатченный модуль Wi-Fi ядра Linux (`qcacld-3.0`) для **Xiaomi Redmi Note 12 4G (`tapas`)** на базе **Snapdragon 685 (SM6225)** и встроенного Wi-Fi-чипа **Qualcomm WCN3988 (Adrastea)**.

Patched Linux kernel Wi-Fi module (`qcacld-3.0`) for **Xiaomi Redmi Note 12 4G (`tapas`)** powered by **Snapdragon 685 (SM6225)** and the built-in **Qualcomm WCN3988 (Adrastea)** wireless chip.

---

## Русский

### Что делает этот `.ko`-файл и зачем он нужен

Стоковый драйвер Wi-Fi в Android (`qca_cld3_wlan.ko`) на Snapdragon 685 рассчитан только на обычный клиентский режим и в лучшем случае отдаёт ограниченный пассивный перехват (RX). Отправлять произвольные 802.11-кадры (packet injection), полноценно управлять монитором через `iw` или переключать каналы/ширину полосы на встроенном Wi-Fi он не позволяет — обычно для этого требуется внешний USB-адаптер через OTG.

**`tapas-wlan-inject`** собирает совместимый с Android GKI 2.0 (ядро `5.15.x`) модуль `qca_cld3_wlan.ko`, который открывает **полноценный Monitor Mode и raw-инъекцию кадров прямо на встроенном Wi-Fi-чипе телефона**, без внешнего адаптера и без постоянной замены системных файлов в `/vendor_dlkm`.

### Возможности патча

| Возможность | Реализация |
| :--- | :--- |
| **Monitor Mode (`nl80211`)** | `NL80211_IFTYPE_MONITOR` добавлен в `wiphy->interface_modes` (`* monitor` виден в `iw phy`). Поддерживается переключение `iw dev wlan0 set type monitor` / `managed` (`RC=0`) и включение через `con_mode=4`. |
| **Инъекция кадров (TX)** | Отправка raw 802.11-кадров с radiotap через скрытый `vdev_id=1` (`WMI_VDEV_TYPE_STA`) и `WMI_MGMT_TX` (`wmi_mgmt_unified_cmd_send`) с очередью `mon_tx_q` (512), пулом на 64 слота и backpressure при `-EBUSY`. |
| **Перехват трафика (RX)** | Штатный `hdd_mon_rx_packet_cbk` с radiotap; при открытии интерфейса останавливаются idle-таймер и фоновое сканирование. |
| **Каналы и ширина полосы** | Поддержка **2.4 ГГц и 5 ГГц**, ширина **20 / 40 / 80 МГц** (`WMI_HOST_MODE_11G/11NG_HT20/11NG_HT40/11A/11NA_HT20/11NA_HT40/11AC_VHT80`). |
| **Смена MAC-адреса** | Реализован `.ndo_set_mac_address` с валидацией и обновлением MAC на скрытом `vdev_id=1`. |
| **Стабильность** | Закрыта утечка SMMU IOVA (строго 1 DMA map ↔ 1 unmap на кадр), убраны утечка `nbuf` (`SUnreclaim` не растёт) и гонка `send ↔ completion`, добавлен мягкий рефреш `vdev_id=1` каждые 20 000 кадров. |

### Требования и подготовка

* **Устройство:** Xiaomi Redmi Note 12 4G (`tapas`, `sku=KHAJE-1-AD`, SM6225, WCN3988).
* **Ядро:** Android GKI 2.0 `5.15.x` (`CONFIG_MODVERSIONS=y`, `CONFIG_CFI_CLANG=y`, `CONFIG_LTO_CLANG_FULL=y`, `CONFIG_DEBUG_INFO_BTF=y`, `CONFIG_SHADOW_CALL_STACK=y`).
* **Окружение:** Root (KernelSU / Magisk), Termux, пакеты `iw`, `iproute2` (`pkg install root-repo && pkg install iw iproute2 tsu`).
* **Бэкап (обязательно перед тестами):** сохраните копию стокового драйвера и `boot.img`:
  ```bash
  su -c "mkdir -p /sdcard/wlan_build && cp /vendor_dlkm/lib/modules/qca_cld3_wlan.ko /sdcard/wlan_build/orig_qca_cld3_wlan.ko"
  ```

### Почему монитор включается не как на ПК

1. **Нельзя грузить `.ko` напрямую с `/sdcard`:** раздел `/sdcard` смонтирован через FUSE с ограничениями SELinux, поэтому `insmod` оттуда не сработает — файл сначала копируется в `/data/local/tmp/wlan_test.ko`.
2. **Нельзя просто сделать `airmon-ng start wlan0` на стоковом драйвере:** сначала нужно остановить Android Wi-Fi (`svc wifi disable`), выгрузить стоковый модуль (`rmmod wlan`), загрузить патченный `.ko` и перевести драйвер `qcacld-3.0` в режим монитора записью `4` в `/sys/module/wlan/parameters/con_mode`.
3. **Не нужно зашивать модуль в KernelSU навсегда:** ручная загрузка оставляет `/vendor_dlkm` нетронутым — если что-то пойдёт не так, достаточно выполнить `stop_mon` или просто перезагрузить телефон, и стоковый Wi-Fi вернётся сам.

### Быстрая настройка команд `driver` и `stop_mon` в Termux

Положите собранный `qca_cld3_wlan.ko` в `/sdcard/tools/wlan_build/qca_cld3_wlan.ko` и добавьте эти две функции в конец `~/.bashrc`:

```bash
DRIVER_SRC="/sdcard/tools/wlan_build/qca_cld3_wlan.ko"
DRIVER_TMP="/data/local/tmp/wlan_test.ko"

driver() {
    su -c '
        echo "[*] Выгрузка стока и загрузка патча..."
        svc wifi disable; sleep 2
        rmmod wlan 2>/dev/null; sleep 1
        cmp -s "'"$DRIVER_SRC"'" "'"$DRIVER_TMP"'" || cp "'"$DRIVER_SRC"'" "'"$DRIVER_TMP"'"
        insmod "'"$DRIVER_TMP"'" || { echo "[ERR] Ошибка insmod!"; exit 1; }
        echo 4 > /sys/module/wlan/parameters/con_mode

        echo "[*] Ждём появления wlan0..."
        i=0
        while [ ! -d /sys/class/net/wlan0 ] && [ $i -lt 10 ]; do
            sleep 1
            i=$((i+1))
        done

        ip link set wlan0 up
        iw dev wlan0 set power_save off 2>/dev/null
        echo "[+] Драйвер загружен, wlan0 готов в режиме monitor."
    '
}

stop_mon() {
    su -c '
        echo "[*] Остановка монитора и возврат стокового Wi-Fi..."
        echo 0 > /sys/module/wlan/parameters/con_mode 2>/dev/null
        sleep 2
        ip link set wlan0 down 2>/dev/null
        sleep 1
        rmmod wlan 2>/dev/null
        sleep 1
        insmod /vendor_dlkm/lib/modules/qca_cld3_wlan.ko 2>/dev/null
        sleep 2
        svc wifi enable
        echo "[+] Стоковый Wi-Fi восстановлен!"
    '
}
```

Примените конфиг:
```bash
source ~/.bashrc
```

### Пошаговый запуск и проверка

1. **Запустить патченный драйвер в режиме монитора:**
   ```bash
   driver
   ```
2. **Проверить, что интерфейс поднялся в `monitor` и патч активен:**
   ```bash
   su -c "iw dev wlan0 info"
   su -c "dmesg | grep MON_INJ | tail -n 20"
   ```
   В выводе `iw dev wlan0 info` должно быть `type monitor`, а в `dmesg` — `MON_INJ: hdd_mon_open_hook rc=0`.
3. **Управление каналом и MAC (примеры):**
   ```bash
   su -c "iw dev wlan0 set channel 6 HT40+"
   su -c "iw dev wlan0 set channel 36"
   su -c "ip link set wlan0 down && ip link set wlan0 address 02:11:22:33:44:55 && ip link set wlan0 up"
   ```
4. **Вернуть обычный Wi-Fi после работы:**
   ```bash
   stop_mon
   ```
   После `stop_mon` в `dmesg | grep "MON_INJ: tx stats"` можно посмотреть итоговую статистику отправленных и отброшенных кадров (`sent / wma_drop / q_drop`).

### Частые проблемы

* **`insmod: Exec format error` / `Invalid module format`:** не совпали версии символов (`CONFIG_MODVERSIONS`) или версия ядра. Снимите свежий `device_symvers.txt` со своей прошивки и пересоберите модуль в GitHub Actions.
* **Wi-Fi не включается после экспериментов:** выполните `stop_mon` ещё раз; если модуль завис — обычная перезагрузка телефона гарантированно вернёт стоковый драйвер из `/vendor_dlkm`.
* **Пересборка под другую прошивку (PixelOS / LineageOS / HyperOS на ядре 5.15):** переписывать `patch_inject.py` не нужно — достаточно обновить `device_symvers.txt` (и при необходимости дерево заголовков ядра под HyperOS) и запустить сборку в GitHub Actions.

### Отказ от ответственности

Проект предназначен исключительно для исследования драйверов Linux, изучения работы `qcacld-3.0` / `nl80211` и авторизованного тестирования безопасности **собственных устройств и сетей**.

---

## English

### What This `.ko` File Does and Why It Exists

The stock Android Wi-Fi kernel driver (`qca_cld3_wlan.ko`) on Snapdragon 685 only supports standard client operation and at most limited passive capture. It does not support raw 802.11 packet injection or full `nl80211` monitor control on the internal chip, which normally forces you to carry an external USB Wi-Fi adapter over OTG.

**`tapas-wlan-inject`** builds an Android GKI 2.0 (`5.15.x`) compatible `qca_cld3_wlan.ko` module that unlocks **full Monitor Mode and raw frame injection directly on the built-in WCN3988 radio**, without external adapters and without permanently modifying `/vendor_dlkm`.

### Features

| Feature | Implementation |
| :--- | :--- |
| **Monitor Mode (`nl80211`)** | Exposes `NL80211_IFTYPE_MONITOR` in `wiphy->interface_modes` (`* monitor` visible in `iw phy`). Supports `iw dev wlan0 set type monitor` / `managed` (`RC=0`) as well as `con_mode=4`. |
| **Raw Frame Injection (TX)** | Injects radiotap-stripped 802.11 frames via a hidden `vdev_id=1` (`WMI_VDEV_TYPE_STA`) and `WMI_MGMT_TX` (`wmi_mgmt_unified_cmd_send`) with a 512-frame `mon_tx_q`, 64-slot descriptor pool, and `-EBUSY` backpressure. |
| **Packet Capture (RX)** | Native `hdd_mon_rx_packet_cbk` with radiotap headers; stops idle timers and aborts background scans on interface open. |
| **Channel & Bandwidth** | Supports **2.4 GHz & 5 GHz**, **20 / 40 / 80 MHz** (`WMI_HOST_MODE_11G/11NG_HT20/11NG_HT40/11A/11NA_HT20/11NA_HT40/11AC_VHT80`). |
| **MAC Spoofing** | Implements `.ndo_set_mac_address` with address validation and hidden `vdev_id=1` MAC sync. |
| **Stability** | Fixes SMMU IOVA exhaustion (strict 1:1 DMA map/unmap per frame), eliminates `nbuf` leaks (`SUnreclaim` stays flat) and `send <-> completion` races, plus a soft `vdev_id=1` refresh every 20,000 frames. |

### Requirements & Backup

* **Device:** Xiaomi Redmi Note 12 4G (`tapas`, `sku=KHAJE-1-AD`, SM6225, WCN3988).
* **Kernel:** Android GKI 2.0 `5.15.x` (`CONFIG_MODVERSIONS=y`, `CONFIG_CFI_CLANG=y`, `CONFIG_LTO_CLANG_FULL=y`, `CONFIG_DEBUG_INFO_BTF=y`, `CONFIG_SHADOW_CALL_STACK=y`).
* **Environment:** Root (KernelSU / Magisk), Termux, `iw`, `iproute2` (`pkg install root-repo && pkg install iw iproute2 tsu`).
* **Backup stock driver first:**
  ```bash
  su -c "mkdir -p /sdcard/wlan_build && cp /vendor_dlkm/lib/modules/qca_cld3_wlan.ko /sdcard/wlan_build/orig_qca_cld3_wlan.ko"
  ```

### Why Starting Monitor Mode Differs from Desktop Linux

1. **You cannot `insmod` directly from `/sdcard`:** `/sdcard` is FUSE-mounted with SELinux restrictions, so the `.ko` must be copied to `/data/local/tmp/wlan_test.ko` first.
2. **Android Wi-Fi HAL owns the stock module:** disable Android Wi-Fi (`svc wifi disable`), unload the stock `wlan` module (`rmmod wlan`), `insmod` the patched module, and switch `qcacld-3.0` to monitor mode via `echo 4 > /sys/module/wlan/parameters/con_mode`.
3. **No permanent KernelSU replacement needed:** manual loading leaves `/vendor_dlkm` untouched. Running `stop_mon` (or simply rebooting) cleanly restores stock Wi-Fi.

### Quick Setup: `driver` and `stop_mon` Helpers in Termux

Place your built `qca_cld3_wlan.ko` at `/sdcard/tools/wlan_build/qca_cld3_wlan.ko` and append these helpers to `~/.bashrc`:

```bash
DRIVER_SRC="/sdcard/tools/wlan_build/qca_cld3_wlan.ko"
DRIVER_TMP="/data/local/tmp/wlan_test.ko"

driver() {
    su -c '
        echo "[*] Unloading stock driver and loading patched module..."
        svc wifi disable; sleep 2
        rmmod wlan 2>/dev/null; sleep 1
        cmp -s "'"$DRIVER_SRC"'" "'"$DRIVER_TMP"'" || cp "'"$DRIVER_SRC"'" "'"$DRIVER_TMP"'"
        insmod "'"$DRIVER_TMP"'" || { echo "[ERR] insmod failed!"; exit 1; }
        echo 4 > /sys/module/wlan/parameters/con_mode

        echo "[*] Waiting for wlan0..."
        i=0
        while [ ! -d /sys/class/net/wlan0 ] && [ $i -lt 10 ]; do
            sleep 1
            i=$((i+1))
        done

        ip link set wlan0 up
        iw dev wlan0 set power_save off 2>/dev/null
        echo "[+] Patched driver loaded, wlan0 ready in monitor mode."
    '
}

stop_mon() {
    su -c '
        echo "[*] Stopping monitor mode and restoring stock Wi-Fi..."
        echo 0 > /sys/module/wlan/parameters/con_mode 2>/dev/null
        sleep 2
        ip link set wlan0 down 2>/dev/null
        sleep 1
        rmmod wlan 2>/dev/null
        sleep 1
        insmod /vendor_dlkm/lib/modules/qca_cld3_wlan.ko 2>/dev/null
        sleep 2
        svc wifi enable
        echo "[+] Stock Wi-Fi restored!"
    '
}
```

Reload `~/.bashrc`:
```bash
source ~/.bashrc
```

### Step-by-Step Usage & Verification

1. **Load the patched driver in monitor mode:**
   ```bash
   driver
   ```
2. **Verify monitor mode and patch hooks:**
   ```bash
   su -c "iw dev wlan0 info"
   su -c "dmesg | grep MON_INJ | tail -n 20"
   ```
   Confirm `type monitor` in `iw dev wlan0 info` and `MON_INJ: hdd_mon_open_hook rc=0` in `dmesg`.
3. **Channel and MAC control examples:**
   ```bash
   su -c "iw dev wlan0 set channel 6 HT40+"
   su -c "iw dev wlan0 set channel 36"
   su -c "ip link set wlan0 down && ip link set wlan0 address 02:11:22:33:44:55 && ip link set wlan0 up"
   ```
4. **Restore normal Android Wi-Fi when done:**
   ```bash
   stop_mon
   ```
   After `stop_mon`, check `dmesg | grep "MON_INJ: tx stats"` to inspect `sent / wma_drop / q_drop` counters.

### Troubleshooting & Porting

* **`insmod: Exec format error` / `Invalid module format`:** kernel symbol CRCs (`CONFIG_MODVERSIONS`) do not match your running kernel. Extract a fresh 5-column `device_symvers.txt` from your ROM and rebuild via GitHub Actions.
* **Wi-Fi won't turn back on:** run `stop_mon` again, or reboot — since `/vendor_dlkm` is untouched, stock Wi-Fi always recovers cleanly on boot.
* **Other 5.15 ROMs (PixelOS / LineageOS / HyperOS):** `patch_inject.py` stays unchanged — update `device_symvers.txt` (and kernel headers for HyperOS if needed) and trigger a GitHub Actions build.

### Disclaimer

Intended solely for Linux kernel driver research, `qcacld-3.0` / `nl80211` study, and authorized security testing on **your own devices and networks**.
