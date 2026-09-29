# Модификация Xiaomi Gateway DGNWG05LM: Интеграция ESP32-C3 в качестве аппаратного BLE-модуля

Данный проект описывает процесс аппаратной и программной модернизации шлюза Xiaomi DGNWG05LM, работающего под управлением OpenWrt (OpenLumi).

**Описание проблемы:** Использование штатного Bluetooth-контроллера (Realtek) в режиме активного сканирования (BLE Proxy) приводит к утечкам памяти и возникновению Kernel Panic в ядре операционной системы.  
**Реализованное решение:** Интеграция дополнительного микроконтроллера ESP32-C3 через внутренний интерфейс USB (CDC-ACM) шлюза. ESP32-C3 берет на себя обработку Bluetooth-запросов (BLE Proxy) для Home Assistant, в то время как разработанный Python-демон обеспечивает трансляцию данных и управление аппаратной периферией шлюза (LED, MPD, LDR, кнопка).

*Внимание: Данный проект несовместим с демоном `lumimqtt`. Если в вашей системе установлен `lumimqtt`, его необходимо предварительно остановить и отключить.*

## Основные функции
- **Bluetooth Proxy:** Стабильная трансляция BLE-пакетов в Home Assistant без нагрузки на основное ядро роутера.
- **Управление RGB-подсветкой:** Линейное диммирование и 9 встроенных эффектов с частотой обновления 50 кадров в секунду.
- **Управление аудио (MPD):** Поддержка воспроизведения локальных аудиофайлов, изменения громкости и остановки воспроизведения через команды по USB.
- **Обработка кнопки:** Поддержка одинарных, двойных, тройных и четверных нажатий, а также удержания. Реализован системный макрос (4 нажатия + удержание 2 сек) для управления интерфейсом Wi-Fi.
- **Мониторинг сенсоров:** Чтение данных датчика освещенности (LDR) через ADC и трансляция показаний (lx).
- **Системная аналитика OpenWrt:** Передача метрик системы (загрузка CPU, свободная RAM/Flash, температура процессора, Uptime, статус Wi-Fi) в Home Assistant с интервалом в 30 секунд.

---

## 1. Аппаратная часть

**Необходимые компоненты:**
- Модуль ESP32-C3 Super Mini.
- Монтажные провода.
- Гибкие антенны (FPC), рекомендуются решения от Tyco.

**Порядок подключения:**
1. Подключите ESP32-C3 к внутреннему интерфейсу USB на плате шлюза:
   - `5V` (или `3.3V`, в зависимости от выбранной точки на плате) -> `VCC` на ESP32.
   - `GND` -> `GND`.
   - `USB D+` -> пин `D+` (GPIO19) на ESP32-C3.
   - `USB D-` -> пин `D-` (GPIO18) на ESP32-C3.
2. Закрепите FPC-антенны на внутренних пластиковых стенках корпуса. Избегайте их размещения в непосредственной близости от магнита динамика для минимизации электромагнитных помех.

---

## 2. Настройка среды OpenWrt

Все команды выполняются через SSH-сессию от имени пользователя `root`.

### 2.1. Подготовка и установка зависимостей
Обновите список пакетов и установите необходимые зависимости для работы с последовательным портом и устройствами ввода:

```bash
opkg update
opkg install python3-pyserial python3-evdev
```

*Примечание:* Если установка драйвера `kmod-usb-acm` завершается ошибкой несовпадения контрольных сумм ядра (Kernel hash mismatch), необходимо выполнить ручную установку. Скачайте `.ipk` файл драйвера, извлеките архив `data.tar.gz` и скопируйте директорию `lib` в корень файловой системы (`/`) роутера.

### 2.2. Установка Python-демона
Создайте файл скрипта, который будет осуществлять маршрутизацию команд между ESP32 и подсистемами OpenWrt (LED, MPD, GPIO).

```bash
nano /root/usb_brain.py
```
Вставьте следующий код:

<details>
  <summary><b>Развернуть полный код usb_brain.py</b></summary>

```python
import serial
import time
import os
import threading
import socket
import math
import random
import colorsys
from evdev import InputDevice, ecodes

PORT = '/dev/ttyACM0'
BTN_DEV = '/dev/input/event0'
LDR_FILE = '/sys/devices/platform/soc/2100000.bus/2198000.adc/iio:device0/in_voltage5_raw'
LED_R = '/sys/class/leds/red'
LED_G = '/sys/class/leds/green'
LED_B = '/sys/class/leds/blue'

wifi_is_on = False
ser = None

def get_max_brightness(led_path):
    try:
        with open(f"{led_path}/max_brightness", 'r') as f: return int(f.read().strip())
    except: return 255

MAX_R = get_max_brightness(LED_R)
MAX_G = get_max_brightness(LED_G)
MAX_B = get_max_brightness(LED_B)

def set_led(led_path, val):
    try:
        with open(f"{led_path}/brightness", 'w') as f: f.write(str(int(val)))
    except: pass

def set_rgb_raw(r, g, b):
    set_led(LED_R, (r / 255.0) * MAX_R)
    set_led(LED_G, (g / 255.0) * MAX_G)
    set_led(LED_B, (b / 255.0) * MAX_B)

# ==========================================
# ЛОГИКА КНОПОК И WI-FI
# ==========================================
btn_clicks = 0
btn_pressed = False
btn_last_time = time.time()

def button_reader():
    global btn_clicks, btn_pressed, btn_last_time
    while True:
        try:
            dev = InputDevice(BTN_DEV)
            for event in dev.read_loop():
                if event.type == ecodes.EV_KEY:
                    if event.value == 1:
                        btn_pressed = True
                        btn_last_time = time.time()
                    elif event.value == 0:
                        btn_pressed = False
                        btn_clicks += 1
                        btn_last_time = time.time()
        except Exception as e:
            time.sleep(1)

def toggle_wifi_bg(state=None):
    global wifi_is_on, ser
    if state == "ON" or (state is None and not wifi_is_on):
        os.system("wifi up")
        wifi_is_on = True
    elif state == "OFF" or (state is None and wifi_is_on):
        os.system("wifi down")
        wifi_is_on = False
        
    if ser and ser.is_open:
        status_str = "ON" if wifi_is_on else "OFF"
        try: ser.write(f"SYS:WIFI:{status_str}\n".encode('utf-8'))
        except: pass

def button_processor():
    global btn_clicks, btn_pressed, btn_last_time, ser
    while True:
        time.sleep(0.05)
        if btn_clicks > 0 or btn_pressed:
            elapsed = time.time() - btn_last_time
            if btn_pressed and btn_clicks == 4 and elapsed >= 2.0:
                
                prev_r, prev_g, prev_b = light.r, light.g, light.b
                prev_effect = light.current_effect
                
                light.run_effect("Police Triple Strobe")
                threading.Thread(target=toggle_wifi_bg, daemon=True).start()
                
                while btn_pressed: time.sleep(0.05)
                btn_clicks = 0
                if ser and ser.is_open:
                    try: ser.write(b"ACTION:Hold Released\n")
                    except: pass
                
                time.sleep(2)
                light.set_state(prev_r, prev_g, prev_b, 0.0, prev_effect)
                continue

            if elapsed > 0.5:
                if btn_pressed and btn_clicks == 4:
                    continue
                action = ""
                if btn_pressed:
                    if btn_clicks == 0: action = "Hold"
                    elif btn_clicks == 1: action = "Double Hold"
                    elif btn_clicks == 2: action = "Triple Hold"
                else:
                    if btn_clicks == 1: action = "Single Click"
                    elif btn_clicks == 2: action = "Double Click"
                    elif btn_clicks == 3: action = "Triple Click"
                    elif btn_clicks == 4: action = "Quadruple Click"

                if action and ser and ser.is_open:
                    try: ser.write(f"ACTION:{action}\n".encode('utf-8'))
                    except: pass
                
                if not btn_pressed:
                    btn_clicks = 0
                else:
                    while btn_pressed: time.sleep(0.05)
                    btn_clicks = 0
                    if ser and ser.is_open:
                        try: ser.write(b"ACTION:Hold Released\n")
                        except: pass

# ==========================================
# СИСТЕМНАЯ АНАЛИТИКА OPENWRT
# ==========================================
def stats_publisher():
    global ser, wifi_is_on
    last_idle = 0.0
    last_total = 0.0
    
    while True:
        try:
            temp = 0.0
            try:
                with open('/sys/devices/platform/soc/2100000.bus/2198000.adc/iio:device0/in_temp_input', 'r') as f:
                    temp = int(f.read().strip()) / 1000.0
            except: pass

            ram_free, ram_used = 0.0, 0.0
            try:
                with open('/proc/meminfo', 'r') as f:
                    lines = f.readlines()
                    mem_total = int(lines[0].split()[1]) / 1024.0
                    mem_free = int(lines[1].split()[1]) / 1024.0
                    mem_avail = mem_free
                    for line in lines:
                        if line.startswith("MemAvailable:"):
                            mem_avail = int(line.split()[1]) / 1024.0
                            break
                    ram_free = mem_avail
                    ram_used = mem_total - ram_free
            except: pass

            rom_free, rom_used = 0.0, 0.0
            try:
                st = os.statvfs('/')
                rom_total = (st.f_blocks * st.f_frsize) / 1048576.0
                rom_free = (st.f_bfree * st.f_frsize) / 1048576.0 
                rom_used = rom_total - rom_free
            except: pass

            cpu_load = 0.0
            try:
                with open('/proc/stat', 'r') as f:
                    fields = [float(column) for column in f.readline().strip().split()[1:]]
                idle, total = fields[3], sum(fields)
                if last_total > 0:
                    idle_delta = idle - last_idle
                    total_delta = total - last_total
                    if total_delta > 0:
                        cpu_load = 100.0 * (1.0 - idle_delta / total_delta)
                last_idle, last_total = idle, total
            except: pass

            uptime_h = 0.0
            try:
                with open('/proc/uptime', 'r') as f:
                    uptime_h = float(f.read().split()[0]) / 3600.0
            except: pass

            wifi_str = "ON" if wifi_is_on else "OFF"

            if ser and ser.is_open:
                ser.write(f"SYS:TEMP:{temp:.1f}\n".encode('utf-8'))
                ser.write(f"SYS:RAM:{ram_used:.1f}:{ram_free:.1f}\n".encode('utf-8'))
                ser.write(f"SYS:ROM:{rom_used:.1f}:{rom_free:.1f}\n".encode('utf-8'))
                ser.write(f"SYS:CPU:{cpu_load:.1f}\n".encode('utf-8'))
                ser.write(f"SYS:UPTIME:{uptime_h:.1f}\n".encode('utf-8'))
                ser.write(f"SYS:WIFI:{wifi_str}\n".encode('utf-8'))
        except Exception as e:
            pass
        
        time.sleep(30)

# ==========================================
# СВЕТ: ПЛАВНЫЕ ПЕРЕХОДЫ (50 FPS)
# ==========================================
class LightController:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None
        self.r = 0.0; self.g = 0.0; self.b = 0.0
        self.current_effect = "None"

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None
        self.current_effect = "None"

    def _fade(self, tr, tg, tb, trans):
        sr, sg, sb = self.r, self.g, self.b
        steps = max(1, int(50 * trans))
        delay = trans / steps
        for step in range(1, steps + 1):
            if self.stop_event.is_set(): break
            self.r = sr + (tr - sr) * (step / steps)
            self.g = sg + (tg - sg) * (step / steps)
            self.b = sb + (tb - sb) * (step / steps)
            set_rgb_raw(int(self.r), int(self.g), int(self.b))
            self._sleep(delay)
        if not self.stop_event.is_set():
            self.r, self.g, self.b = float(tr), float(tg), float(tb)
            set_rgb_raw(int(tr), int(tg), int(tb))

    def set_color(self, r, g, b, trans):
        self.stop()
        self.stop_event.clear()
        if trans <= 0:
            self.r, self.g, self.b = float(r), float(g), float(b)
            set_rgb_raw(int(r), int(g), int(b))
        else:
            self.thread = threading.Thread(target=self._fade, args=(r, g, b, trans), daemon=True)
            self.thread.start()

    def set_state(self, r, g, b, trans, effect):
        if effect == "None":
            self.set_color(r, g, b, trans)
        else:
            self.r, self.g, self.b = float(r), float(g), float(b)
            if self.current_effect != effect:
                self.stop()
                self.stop_event.clear()
                self.current_effect = effect
                effects_map = {
                    "Police": self._police, "Rainbow": self._rainbow, "Strobe": self._strobe,
                    "Blink": self._blink, "Police Strobe": self._police_strobe,
                    "Double Strobe": self._double_strobe, "Breathing": self._breathing,
                    "Fire": self._fire, "Police Triple Strobe": self._police_triple_strobe
                }
                target = effects_map.get(effect)
                if target:
                    self.thread = threading.Thread(target=target, daemon=True)
                    self.thread.start()

    def run_effect(self, effect_name):
        self.set_state(self.r, self.g, self.b, 0, effect_name)

    def _sleep(self, delay):
        self.stop_event.wait(delay)

    def _police(self):
        while not self.stop_event.is_set():
            set_rgb_raw(255, 0, 0); self._sleep(0.3)
            if self.stop_event.is_set(): break
            set_rgb_raw(0, 0, 255); self._sleep(0.3)
    def _rainbow(self):
        hue = 0.0
        while not self.stop_event.is_set():
            r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            set_rgb_raw(int(r*255), int(g*255), int(b*255))
            hue = (hue + 0.01) % 1.0
            self._sleep(0.05)
    def _police_triple_strobe(self):
        while not self.stop_event.is_set():
            for _ in range(3):
                set_rgb_raw(255, 0, 0); self._sleep(0.05)
                set_rgb_raw(0, 0, 0); self._sleep(0.05)
            self._sleep(0.2)
            if self.stop_event.is_set(): break
            for _ in range(3):
                set_rgb_raw(0, 0, 255); self._sleep(0.05)
                set_rgb_raw(0, 0, 0); self._sleep(0.05)
            self._sleep(0.2)
    def _police_strobe(self):
        while not self.stop_event.is_set():
            for _ in range(2):
                set_rgb_raw(255, 0, 0); self._sleep(0.05)
                set_rgb_raw(0, 0, 0); self._sleep(0.05)
            self._sleep(0.2)
            if self.stop_event.is_set(): break
            for _ in range(2):
                set_rgb_raw(0, 0, 255); self._sleep(0.05)
                set_rgb_raw(0, 0, 0); self._sleep(0.05)
            self._sleep(0.2)
    def _double_strobe(self):
        while not self.stop_event.is_set():
            for _ in range(2):
                set_rgb_raw(int(self.r), int(self.g), int(self.b)); self._sleep(0.05)
                set_rgb_raw(0, 0, 0); self._sleep(0.05)
            self._sleep(0.1)
            if self.stop_event.is_set(): break
            for _ in range(2):
                set_rgb_raw(int(self.r), int(self.g), int(self.b)); self._sleep(0.05)
                set_rgb_raw(0, 0, 0); self._sleep(0.05)
            self._sleep(0.5)
    def _breathing(self):
        step = 0
        while not self.stop_event.is_set():
            factor = (math.sin(step) + 1) / 2 * 0.9 + 0.1
            set_rgb_raw(int(self.r * factor), int(self.g * factor), int(self.b * factor))
            step += 0.05
            self._sleep(0.05)
    def _fire(self):
        while not self.stop_event.is_set():
            factor = random.uniform(0.5, 1.0)
            hue = random.uniform(0.0, 0.12)
            r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            set_rgb_raw(int(r*255*factor), int(g*255*factor), int(b*255*factor))
            self._sleep(random.uniform(0.05, 0.15))
    def _strobe(self):
        while not self.stop_event.is_set():
            set_rgb_raw(int(self.r), int(self.g), int(self.b)); self._sleep(0.1)
            set_rgb_raw(0, 0, 0); self._sleep(0.1)
    def _blink(self):
        while not self.stop_event.is_set():
            set_rgb_raw(int(self.r), int(self.g), int(self.b)); self._sleep(1.0)
            set_rgb_raw(0, 0, 0); self._sleep(1.0)

light = LightController()

def send_mpd_command(cmd_list):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(('127.0.0.1', 6600))
            s.recv(1024)
            s.sendall(("\n".join(cmd_list) + "\n").encode('utf-8'))
            s.recv(1024)
    except: pass

def ldr_listener():
    global ser
    while True:
        try:
            with open(LDR_FILE, 'r') as f: raw_val = int(f.read().strip())
            lux = int(raw_val * 0.25)
            if ser and ser.is_open: ser.write(f"LDR:{lux}\n".encode('utf-8'))
        except: pass
        time.sleep(10)

def main():
    global ser
    threading.Thread(target=button_reader, daemon=True).start()
    threading.Thread(target=button_processor, daemon=True).start()
    threading.Thread(target=ldr_listener, daemon=True).start()
    threading.Thread(target=stats_publisher, daemon=True).start()
    
    while True:
        try:
            ser = serial.Serial(PORT, 115200, timeout=1)
            print(f"[*] Демон запущен.")
            
            while True:
                line = ser.readline()
                if not line: continue
                try:
                    line = line.decode('utf-8', errors='ignore').strip()
                    if line.startswith("CMD:STATE:"):
                        parts = line.split(":")
                        r, g, b = map(int, parts[2].split(','))
                        trans = float(parts[3])
                        effect = parts[4]
                        light.set_state(r, g, b, trans, effect)
                    elif line.startswith("CMD:MPD:PLAY:"):
                        track = line[13:]
                        send_mpd_command(["clear", f'add "{track}"', "play"])
                    elif line.startswith("CMD:MPD:VOL:"):
                        vol = line[12:]
                        send_mpd_command([f"setvol {vol}"])
                    elif line == "CMD:MPD:STOP":
                        send_mpd_command(["stop"])
                    elif line == "CMD:SYS:REBOOT":
                        os.system("reboot")
                    elif line == "CMD:SYS:WIFI:ON":
                        threading.Thread(target=toggle_wifi_bg, args=("ON",), daemon=True).start()
                    elif line == "CMD:SYS:WIFI:OFF":
                        threading.Thread(target=toggle_wifi_bg, args=("OFF",), daemon=True).start()
                except Exception as e:
                    pass
        except Exception as e:
            time.sleep(1)

if __name__ == '__main__':
    main()
```

</details>

### 2.3. Создание службы init.d (procd)
Для обеспечения автоматического запуска скрипта при загрузке системы и его перезапуска в случае завершения работы с ошибкой (respawn), необходимо создать системную службу.

Выполните команду для создания файла инициализации:

```bash
cat << 'EOF' > /etc/init.d/usbbrain
#!/bin/sh /etc/rc.common
START=99
USE_PROCD=1
start_service() {
    wifi down
    hciconfig hci0 down &> /dev/null
    procd_open_instance
    procd_set_param command /usr/bin/python3 /root/usb_brain.py
    procd_set_param respawn
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}
EOF
```

Установите права на исполнение и добавьте службу в автозагрузку:

```bash
chmod +x /etc/init.d/usbbrain
/etc/init.d/usbbrain enable
/etc/init.d/usbbrain start
```

---

## 3. Конфигурация ESPHome

Модуль ESP32-C3 настраивается через платформу ESPHome.
**Важное замечание:** Для корректной инициализации аппаратного USB (CDC-ACM) необходимо использовать фреймворк `arduino` со следующими флагами сборки: `-DARDUINO_USB_MODE=1` и `-DARDUINO_USB_CDC_ON_BOOT=1`. Без них связь по USB-интерфейсу функционировать не будет.

Используйте предоставленную конфигурацию YAML (предварительно измените учетные данные Wi-Fi и параметры OTA):

<details>
  <summary><b>Развернуть полный код ESPHome (YAML)</b></summary>

```yaml
esphome:
  name: ble-gw-kuhnia
  friendly_name: ble-gw-kuhnia
  build_flags:
    - "-DARDUINO_USB_MODE=1"
    - "-DARDUINO_USB_CDC_ON_BOOT=1"
  on_boot:
    priority: 600
    then:
      - lambda: |-
          Serial.begin(115200);

esp32:
  variant: esp32c3
  flash_size: 4MB
  framework:
    type: arduino

logger:
  level: DEBUG
  baud_rate: 0 

globals:
  - id: was_held
    type: bool
    initial_value: 'false'
  - id: was_light_on
    type: bool
    initial_value: 'false'

api:
  encryption:
    key: "aHx8jw2Iq5aMUsi3+90aVINJ5bD6DwDfNM5FaG6Jy9s="
  services:
    - service: mpd_play_track
      variables:
        track: string
      then:
        - lambda: |-
            Serial.printf("CMD:MPD:PLAY:%s\n", track.c_str());
    - service: mpd_stop
      then:
        - lambda: |-
            Serial.printf("CMD:MPD:STOP\n");
    - service: mpd_set_volume
      variables:
        volume: int
      then:
        - lambda: |-
            Serial.printf("CMD:MPD:VOL:%d\n", (int)volume);

ota:
  - platform: esphome

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
  fast_connect: true
  power_save_mode: none

# ==========================================
# ПОЛЗУНКИ И ВЫКЛЮЧАТЕЛИ (Раздел: Настройки)
# ==========================================
number:
  - platform: template
    name: "Transition (Вкл-Выкл)"
    id: gw_transition_power
    min_value: 0
    max_value: 60
    step: 0.1
    initial_value: 1.0
    optimistic: true
    unit_of_measurement: "s"
    mode: slider
    entity_category: config

  - platform: template
    name: "Transition (Цвет)"
    id: gw_transition_color
    min_value: 0
    max_value: 60
    step: 0.1
    initial_value: 0.5
    optimistic: true
    unit_of_measurement: "s"
    mode: slider
    entity_category: config

switch:
  - platform: template
    name: "Gateway Wi-Fi"
    id: gw_sys_wifi_switch
    icon: "mdi:wifi"
    entity_category: config
    optimistic: true
    turn_on_action:
      - lambda: |-
          Serial.printf("CMD:SYS:WIFI:ON\n");
    turn_off_action:
      - lambda: |-
          Serial.printf("CMD:SYS:WIFI:OFF\n");

# ==========================================
# BLUETOOTH PROXY 
# ==========================================
esp32_ble_tracker:
  scan_parameters:
    interval: 320ms
    window: 240ms
    active: true

bluetooth_proxy:
  active: true

# ==========================================
# ПАРСИНГ USB 
# ==========================================
interval:
  - interval: 50ms
    then:
      - lambda: |-
          while (Serial.available()) {
            String line = Serial.readStringUntil('\n');
            line.trim();
            if (line.startsWith("ACTION:")) {
              id(gw_btn_action).publish_state(line.substring(7).c_str());
            } else if (line.startsWith("LDR:")) {
              id(gw_ldr).publish_state(line.substring(4).toFloat());
            } else if (line.startsWith("SYS:TEMP:")) {
              id(gw_sys_temp).publish_state(line.substring(9).toFloat());
            } else if (line.startsWith("SYS:CPU:")) {
              id(gw_sys_cpu).publish_state(line.substring(8).toFloat());
            } else if (line.startsWith("SYS:UPTIME:")) {
              id(gw_sys_uptime).publish_state(line.substring(11).toFloat());
            } else if (line.startsWith("SYS:WIFI:")) {
              if (line.substring(9) == "ON") {
                id(gw_sys_wifi_switch).publish_state(true);
              } else {
                id(gw_sys_wifi_switch).publish_state(false);
              }
            } else if (line.startsWith("SYS:RAM:")) {
              int colon = line.indexOf(':', 8);
              if (colon != -1) {
                id(gw_sys_ram_used).publish_state(line.substring(8, colon).toFloat());
                id(gw_sys_ram_free).publish_state(line.substring(colon + 1).toFloat());
              }
            } else if (line.startsWith("SYS:ROM:")) {
              int colon = line.indexOf(':', 8);
              if (colon != -1) {
                id(gw_sys_rom_used).publish_state(line.substring(8, colon).toFloat());
                id(gw_sys_rom_free).publish_state(line.substring(colon + 1).toFloat());
              }
            }
          }

# ==========================================
# ЧИСЛОВЫЕ СЕНСОРЫ И АНАЛИТИКА ШЛЮЗА
# ==========================================
sensor:
  - platform: template
    id: gw_ldr
    name: "Gateway Illuminance"
    device_class: illuminance
    unit_of_measurement: "lx"

  - platform: template
    id: gw_sys_temp
    name: "Gateway CPU Temperature"
    unit_of_measurement: "°C"
    device_class: temperature
    entity_category: diagnostic

  - platform: template
    id: gw_sys_cpu
    name: "Gateway CPU Load (1m)"
    unit_of_measurement: "%"
    icon: "mdi:cpu-64-bit"
    entity_category: diagnostic

  - platform: template
    id: gw_sys_ram_used
    name: "Gateway RAM Used"
    unit_of_measurement: "MB"
    icon: "mdi:memory"
    entity_category: diagnostic

  - platform: template
    id: gw_sys_ram_free
    name: "Gateway RAM Free"
    unit_of_measurement: "MB"
    icon: "mdi:memory"
    entity_category: diagnostic

  - platform: template
    id: gw_sys_rom_used
    name: "Gateway Flash Used"
    unit_of_measurement: "MB"
    icon: "mdi:harddisk"
    entity_category: diagnostic

  - platform: template
    id: gw_sys_rom_free
    name: "Gateway Flash Free"
    unit_of_measurement: "MB"
    icon: "mdi:harddisk"
    entity_category: diagnostic

  - platform: template
    id: gw_sys_uptime
    name: "Gateway Uptime"
    unit_of_measurement: "h"
    icon: "mdi:clock-outline"
    entity_category: diagnostic

# ==========================================
# ТЕКСТОВЫЕ СЕНСОРЫ
# ==========================================
text_sensor:
  - platform: template
    id: gw_btn_action
    name: "Gateway Button Action"
    icon: "mdi:gesture-double-tap"

# ==========================================
# ЛАМПА (Единый пакет)
# ==========================================
output:
  - platform: template
    id: gw_red
    type: float
    write_action: { lambda: "return;" }
  - platform: template
    id: gw_green
    type: float
    write_action: { lambda: "return;" }
  - platform: template
    id: gw_blue
    type: float
    write_action: { lambda: "return;" }

light:
  - platform: rgb
    name: "Gateway Light"
    id: gw_light
    red: gw_red
    green: gw_green
    blue: gw_blue
    gamma_correct: 1.0 
    default_transition_length: 0s 
    
    effects:
      - lambda: { name: "Police", update_interval: 1s, lambda: "return;" }
      - lambda: { name: "Rainbow", update_interval: 1s, lambda: "return;" }
      - lambda: { name: "Strobe", update_interval: 1s, lambda: "return;" }
      - lambda: { name: "Blink", update_interval: 1s, lambda: "return;" }
      - lambda: { name: "Police Strobe", update_interval: 1s, lambda: "return;" }
      - lambda: { name: "Double Strobe", update_interval: 1s, lambda: "return;" }
      - lambda: { name: "Breathing", update_interval: 1s, lambda: "return;" }
      - lambda: { name: "Fire", update_interval: 1s, lambda: "return;" }
      - lambda: { name: "Police Triple Strobe", update_interval: 1s, lambda: "return;" }
    
    on_state:
      - lambda: |-
          std::string effect = id(gw_light).get_effect_name();
          if (effect == "") { effect = "None"; }
          
          bool is_on = id(gw_light).current_values.is_on();
          float trans;
          if (is_on != id(was_light_on)) {
            trans = id(gw_transition_power).state;
          } else {
            trans = id(gw_transition_color).state;
          }
          id(was_light_on) = is_on;
          
          if (!is_on) {
            Serial.printf("CMD:STATE:0,0,0:%.1f:None\n", trans);
          } else {
            float r, g, b;
            id(gw_light).current_values_as_rgb(&r, &g, &b);
            Serial.printf("CMD:STATE:%d,%d,%d:%.1f:%s\n", (int)(r*255), (int)(g*255), (int)(b*255), trans, effect.c_str());
          }

# ==========================================
# ПЕРЕЗАГРУЗКИ (Раздел: Диагностика)
# ==========================================
button:
  - platform: restart
    name: "Restart ESP32 Gateway"
    entity_category: diagnostic

  - platform: template
    name: "Reboot Xiaomi Gateway"
    icon: "mdi:restart"
    entity_category: diagnostic
    on_press:
      - lambda: |-
          Serial.printf("CMD:SYS:REBOOT\n");
```

</details>

После успешной компиляции и прошивки устройство будет доступно в интеграции ESPHome в Home Assistant. Элементы управления параметрами перехода (transition) будут сгруппированы в разделе «Настройки», а системные метрики шлюза — в разделе «Диагностика».

---

## 4. Примеры использования в Home Assistant

Логика работы демона позволяет использовать шлюз как локальную систему оповещения без существенных задержек.

Пример автоматизации для срабатывания сигнализации при протечке (включение эффекта стробоскопа и сирены через MPD):

```yaml
automation:
  - alias: "Тревога: Протечка воды"
    mode: restart
    trigger:
      - platform: state
        entity_id: binary_sensor.water_leak
        to: "on"
    action:
      - action: light.turn_on
        target:
          entity_id: light.gateway_light
        data:
          effect: "Police Triple Strobe"
          brightness_pct: 100
      - action: esphome.ble_gw_kuhnia_mpd_set_volume
        data:
          volume: 100
      - action: esphome.ble_gw_kuhnia_mpd_play_track
        data:
          track: "siren_water.mp3" # Файл должен находиться в директории плеера MPD на роутере
```
