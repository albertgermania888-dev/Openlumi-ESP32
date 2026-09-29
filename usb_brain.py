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
            print(f"[*] Боевой Демон V11 (Media Player Edition) запущен.")
            
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
                    elif line == "CMD:MPD:PAUSE":
                        send_mpd_command(["pause 1"])
                    elif line == "CMD:MPD:RESUME":
                        send_mpd_command(["pause 0"])
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
