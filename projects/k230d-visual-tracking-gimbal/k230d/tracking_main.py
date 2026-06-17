"""
K230D AI Tracking Demo - ST7701鏈湴鏄剧ず鐗?鑹插潡杩借釜(LAB) + 浜戝彴姝ヨ繘鐢垫満鎺у埗 + 澹板厜鍙嶉
鍗忚鍙傝€? 25E_tripod_head follow_rectangle.py
"""
import time, os, sys, gc

from media.sensor import *
from media.display import *
from media.media import *
from machine import Pin, PWM, FPIOA, UART
from wireless_tuning import WirelessTuner, clamp

os.exitpoint(os.EXITPOINT_ENABLE)
gc.enable()

# ============================================================
#  閰嶇疆
# ============================================================
CAM_W = 640
CAM_H = 480
ST7701_W = 800
ST7701_H = 480

# Camera image is centered on ST7701.
DISP_X = (ST7701_W - CAM_W) // 2
DISP_Y = (ST7701_H - CAM_H) // 2

# 鑹插潡妫€娴?LAB 闃堝€?(杩借釜绾㈣壊, L瀹芥澗鎶楀厜鐓? A/B涓ユ牸閿佽壊)
TARGET_LAB = (15, 70, 30, 80, 15, 70)
MIN_PIXELS = 120
MIN_AREA = 120
MERGE_MARGIN = 20

# 浜戝彴鎺у埗
DEAD_ZONE = 8
GAIN_X = 20        # 姘村钩澧炵泭
GAIN_Y = 7         # 淇话澧炵泭
KD_X = 2
KD_Y = 1
ALPHA_NUM = 5
ALPHA_DEN = 10
MIN_SPEED_X_RPM = 55
MIN_SPEED_Y_RPM = 40
MAX_SPEED_X_RPM = 260
MAX_SPEED_Y_RPM = 210
BOOST_ERR = 55
X_BRAKE_FRAMES = 2
X_REVERSE_ERR = 22
X_REVERSE_BRAKE_SPEED = 110
X_REVERSE_LIMIT_RPM = 180
X_NEAR_ZONE = 42
X_SLOW_ZONE = 95
X_NEAR_MAX_RPM = 70
X_SLOW_MAX_RPM = 135
Y_BRAKE_FRAMES = 4
Y_REVERSE_ERR = 18
Y_REVERSE_BRAKE_SPEED = 95
Y_REVERSE_LIMIT_RPM = 150
Y_NEAR_ZONE = 35
Y_SLOW_ZONE = 85
Y_NEAR_MAX_RPM = 58
Y_SLOW_MAX_RPM = 105

# Target motion feed-forward. It predicts a near-future aim point from recent
# target motion instead of only chasing the current frame center.
PREDICT_ENABLE = True
PREDICT_GAIN_X_NUM = 7
PREDICT_GAIN_Y_NUM = 12
PREDICT_GAIN_DEN = 10
TARGET_VEL_ALPHA_NUM = 4
TARGET_VEL_ALPHA_DEN = 10
MAX_PREDICT_X = 45
MAX_PREDICT_Y = 55
PREDICT_MIN_VEL = 2

# 鍛戒腑鍒ゅ畾
HIT_THRESHOLD = 15

# Wireless tuning. Set ENABLE_WIRELESS_TUNING to False for maximum standalone stability.
ENABLE_WIRELESS_TUNING = True
WIFI_SSID = "YOUR_2G_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
PC_IP = "255.255.255.255"
STAT_PORT = 9001
CMD_PORT = 9002
STAT_INTERVAL_MS = 100

TUNABLE_LIMITS = {
    "gain_x": (4, 45),
    "gain_y": (2, 30),
    "kd_x": (0, 10),
    "kd_y": (0, 10),
    "dead": (3, 30),
    "min_x": (10, 160),
    "min_y": (10, 140),
    "max_x": (60, 300),
    "max_y": (60, 260),
}

# ============================================================
#  UART 浜戝彴鍗忚 (9瀛楄妭甯?
# ============================================================
# Emm V5 UART protocol used by X42_V1.3.
MOTOR_ACC = 15
MAX_SPEED_RPM = 250


def motor_enable(uart, addr, enable=True):
    uart.write(bytes([addr & 0xFF, 0xF3, 0xAB, 0x01 if enable else 0x00, 0x00, 0x6B]))


def motor_stop(uart, addr):
    uart.write(bytes([addr & 0xFF, 0xFE, 0x98, 0x00, 0x6B]))


def send_order(uart, addr, direction, velocity):
    speed = max(0, min(int(velocity), MAX_SPEED_RPM))
    if speed == 0:
        motor_stop(uart, addr)
        return
    uart.write(bytes([
        addr & 0xFF,
        0xF6,
        direction & 0x01,
        (speed >> 8) & 0xFF,
        speed & 0xFF,
        MOTOR_ACC & 0xFF,
        0x00,
        0x6B,
    ]))


def calc_speed(delta, gain, derivative, kd, min_speed, max_speed):
    speed = delta * gain
    if delta > BOOST_ERR:
        speed += (delta - BOOST_ERR) * gain
    speed += derivative * kd
    if speed > 0 and speed < min_speed:
        speed = min_speed
    return min(speed, max_speed)


def ramp_down(speed):
    if speed <= 0:
        return 0
    if speed > 120:
        return speed - 40
    if speed > 70:
        return speed - 25
    if speed > 30:
        return speed - 15
    return 0


def calc_reverse_speed(delta, gain, derivative, kd, min_speed, max_speed, reverse_limit):
    speed = calc_speed(delta, gain, derivative, kd, min_speed, max_speed)
    return min(speed, reverse_limit)


def limit_x_speed(delta, speed):
    if speed <= 0:
        return 0
    if delta <= X_NEAR_ZONE:
        return min(speed, X_NEAR_MAX_RPM)
    if delta <= X_SLOW_ZONE:
        return min(speed, X_SLOW_MAX_RPM)
    return speed


def limit_y_speed(delta, speed):
    if speed <= 0:
        return 0
    if delta <= Y_NEAR_ZONE:
        return min(speed, Y_NEAR_MAX_RPM)
    if delta <= Y_SLOW_ZONE:
        return min(speed, Y_SLOW_MAX_RPM)
    return speed


def clamp_int(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def apply_tuning_command(message):
    global GAIN_X, GAIN_Y, KD_X, KD_Y, DEAD_ZONE
    global MIN_SPEED_X_RPM, MIN_SPEED_Y_RPM, MAX_SPEED_X_RPM, MAX_SPEED_Y_RPM

    if not message:
        return False
    cmd = message.get("cmd", "")
    params = message.get("params", {})
    if cmd == "STOP":
        return "stop"
    if cmd == "START":
        return "start"
    if cmd not in ("SET", "PARAM"):
        return False

    mapping = {
        "gx": ("gain_x", "GAIN_X"),
        "gy": ("gain_y", "GAIN_Y"),
        "kdx": ("kd_x", "KD_X"),
        "kdy": ("kd_y", "KD_Y"),
        "dead": ("dead", "DEAD_ZONE"),
        "minx": ("min_x", "MIN_SPEED_X_RPM"),
        "miny": ("min_y", "MIN_SPEED_Y_RPM"),
        "maxx": ("max_x", "MAX_SPEED_X_RPM"),
        "maxy": ("max_y", "MAX_SPEED_Y_RPM"),
    }
    changed = False
    for key, value in params.items():
        if key not in mapping:
            continue
        limit_key, global_name = mapping[key]
        low, high = TUNABLE_LIMITS[limit_key]
        globals()[global_name] = clamp(value, low, high)
        changed = True
    return changed


# ============================================================
#  铚傞福鍣?+ RGB
# ============================================================
def feedback_init():
    fpioa = FPIOA()
    fpioa.set_function(65, FPIOA.GPIO65)
    fpioa.set_function(66, FPIOA.GPIO66)
    fpioa.set_function(71, FPIOA.GPIO71)
    fpioa.set_function(61, FPIOA.PWM1)

    r = Pin(65, Pin.OUT, pull=Pin.PULL_NONE, drive=7)
    g = Pin(66, Pin.OUT, pull=Pin.PULL_NONE, drive=7)
    b = Pin(71, Pin.OUT, pull=Pin.PULL_NONE, drive=7)
    r.high(); g.high(); b.high()

    bz = PWM(1)
    bz.freq(2000)
    bz.duty_u16(0)
    return r, g, b, bz


def led_set(r, g, b, cr, cg, cb):
    r.value(0 if cr else 1)
    g.value(0 if cg else 1)
    b.value(0 if cb else 1)


# ============================================================
#  涓诲嚱鏁?# ============================================================
def main():
    print("=" * 40)
    print("  K230D Tracking Demo v2.0")
    print("=" * 40)

    sensor = None
    uart_x = None
    uart_y = None
    tuner = None
    try:
        # X杞? UART4(GPIO36/37), Y杞? UART3(GPIO32/33)
        fpioa = FPIOA()
        fpioa.set_function(36, FPIOA.UART4_TXD)
        fpioa.set_function(37, FPIOA.UART4_RXD)
        fpioa.set_function(32, FPIOA.UART3_TXD)
        fpioa.set_function(33, FPIOA.UART3_RXD)
        uart_x = UART(4, baudrate=115200)
        uart_y = UART(3, baudrate=115200)
        print("[UART] X=UART4(GPIO36/37), Y=UART3(GPIO32/33) OK")
        motor_enable(uart_x, 1, True)
        motor_enable(uart_y, 2, True)
        time.sleep_ms(100)
        print("[MOTOR] Emm V5 enable sent")

        # Camera 640x480 RGB565
        sensor = Sensor(id=2)
        sensor.reset()
        sensor.set_framesize(width=CAM_W, height=CAM_H, chn=CAM_CHN_ID_0)
        sensor.set_pixformat(Sensor.RGB565, chn=CAM_CHN_ID_0)

        Display.init(Display.ST7701, width=ST7701_W, height=ST7701_H)
        MediaManager.init()
        sensor.run()
        time.sleep(0.5)
        print(f"[CAM] {CAM_W}x{CAM_H} RGB565 + ST7701 OK")

        # Feedback
        led_r, led_g, led_b, buzzer = feedback_init()
        print("[FB] LED+Buzzer OK")

        if ENABLE_WIRELESS_TUNING:
            tuner = WirelessTuner(
                WIFI_SSID,
                WIFI_PASSWORD,
                pc_ip=PC_IP,
                stat_port=STAT_PORT,
                cmd_port=CMD_PORT,
            )
            tuner.start()

        cx_half = CAM_W // 2
        cy_half = CAM_H // 2

        # EMA 婊ゆ尝鐘舵€?(鏁存暟)
        filtered_err_x = 0
        filtered_err_y = 0
        last_filtered_err_x = 0
        last_filtered_err_y = 0
        last_dir_x = -1
        last_speed_x = 0
        x_brake_frames = 0
        last_dir_y = -1
        last_speed_y = 0
        y_brake_frames = 0
        last_target_x = cx_half
        last_target_y = cy_half
        target_vel_x = 0
        target_vel_y = 0
        had_target = False

        hits = 0
        buzz_until = 0
        motor_output_enabled = True
        clock = time.clock()

        for _ in range(5):
            sensor.snapshot()
        gc.collect()
        print("[RUN] Tracking started!")

        while True:
            clock.tick()
            os.exitpoint()

            img = sensor.snapshot(chn=CAM_CHN_ID_0)

            # color blob detection
            blobs = img.find_blobs(
                [TARGET_LAB],
                pixels_threshold=MIN_PIXELS,
                area_threshold=MIN_AREA,
                merge=True,
                margin=MERGE_MARGIN
            )
            target_x = cx_half
            target_y = cy_half
            aim_x = cx_half
            aim_y = cy_half
            tracking = False

            if blobs:
                largest = max(blobs, key=lambda b: b.pixels())
                if largest.pixels() >= MIN_PIXELS:
                    target_x = largest.cx()
                    target_y = largest.cy()
                    tracking = True

                    # 缁樺埗鐩爣
                    hit = abs(target_x - cx_half) < HIT_THRESHOLD and abs(target_y - cy_half) < HIT_THRESHOLD
                    color = (0, 255, 0) if hit else (255, 255, 0)
                    img.draw_rectangle(largest.rect(), color=color, thickness=2)
                    img.draw_cross(target_x, target_y, color=(0, 255, 0), size=6)
                    img.draw_line(cx_half, cy_half, target_x, target_y, color=(0, 255, 255))

                    if hit:
                        hits += 1
                        led_set(led_r, led_g, led_b, 0, 1, 0)
                        buzzer.duty_u16(32768)
                        buzz_until = time.ticks_add(time.ticks_ms(), 30)
                    else:
                        led_set(led_r, led_g, led_b, 0, 0, 1)

            if tracking:
                if had_target:
                    raw_vx = target_x - last_target_x
                    raw_vy = target_y - last_target_y
                    target_vel_x = (TARGET_VEL_ALPHA_NUM * raw_vx + (TARGET_VEL_ALPHA_DEN - TARGET_VEL_ALPHA_NUM) * target_vel_x) // TARGET_VEL_ALPHA_DEN
                    target_vel_y = (TARGET_VEL_ALPHA_NUM * raw_vy + (TARGET_VEL_ALPHA_DEN - TARGET_VEL_ALPHA_NUM) * target_vel_y) // TARGET_VEL_ALPHA_DEN
                else:
                    target_vel_x = 0
                    target_vel_y = 0
                    had_target = True

                last_target_x = target_x
                last_target_y = target_y
                if PREDICT_ENABLE and (abs(target_vel_x) >= PREDICT_MIN_VEL or abs(target_vel_y) >= PREDICT_MIN_VEL):
                    predict_x = clamp_int((target_vel_x * PREDICT_GAIN_X_NUM) // PREDICT_GAIN_DEN, -MAX_PREDICT_X, MAX_PREDICT_X)
                    predict_y = clamp_int((target_vel_y * PREDICT_GAIN_Y_NUM) // PREDICT_GAIN_DEN, -MAX_PREDICT_Y, MAX_PREDICT_Y)
                    aim_x = clamp_int(target_x + predict_x, 0, CAM_W - 1)
                    aim_y = clamp_int(target_y + predict_y, 0, CAM_H - 1)
                    img.draw_cross(aim_x, aim_y, color=(0, 128, 255), size=8, thickness=2)
                else:
                    aim_x = target_x
                    aim_y = target_y
            else:
                had_target = False
                target_vel_x = 0
                target_vel_y = 0

            if not tracking:
                led_set(led_r, led_g, led_b, 1, 0, 0)

            if tuner:
                tune_msg = tuner.recv_params()
                tune_result = apply_tuning_command(tune_msg)
                if tune_result == "stop":
                    motor_output_enabled = False
                    motor_stop(uart_x, 1)
                    motor_stop(uart_y, 2)
                    print("[TUNE] motor output stopped")
                elif tune_result == "start":
                    motor_output_enabled = True
                    print("[TUNE] motor output started")
                elif tune_result:
                    print("[TUNE] params gx=%d gy=%d kdx=%d kdy=%d dead=%d" %
                          (GAIN_X, GAIN_Y, KD_X, KD_Y, DEAD_ZONE))

            # --- X杞翠簯鍙版帶鍒?---
            raw_err_x = aim_x - cx_half
            speed_x = 0
            dir_x = last_dir_x if last_dir_x >= 0 else 0
            if x_brake_frames > 0:
                x_brake_frames -= 1
                last_filtered_err_x = 0
            elif abs(raw_err_x) < DEAD_ZONE:
                last_filtered_err_x = 0
                send_order(uart_x, 1, 0, 0)
            else:
                filtered_err_x = (ALPHA_NUM * raw_err_x + (ALPHA_DEN - ALPHA_NUM) * filtered_err_x) // ALPHA_DEN
                deriv_x = abs(filtered_err_x) - abs(last_filtered_err_x)
                last_filtered_err_x = filtered_err_x
                if filtered_err_x >= 0:
                    next_dir_x = 0
                    dx = filtered_err_x
                else:
                    next_dir_x = 1
                    dx = -filtered_err_x
                if last_dir_x >= 0 and next_dir_x != last_dir_x and dx > X_REVERSE_ERR:
                    last_filtered_err_x = 0
                    old_dir_x = last_dir_x
                    last_dir_x = next_dir_x
                    if last_speed_x > X_REVERSE_BRAKE_SPEED:
                        speed_x = ramp_down(last_speed_x)
                        dir_x = old_dir_x
                    else:
                        dir_x = next_dir_x
                        speed_x = calc_reverse_speed(
                            dx, GAIN_X, deriv_x, KD_X,
                            MIN_SPEED_X_RPM, MAX_SPEED_X_RPM, X_REVERSE_LIMIT_RPM)
                        speed_x = limit_x_speed(dx, speed_x)
                else:
                    dir_x = next_dir_x
                    last_dir_x = next_dir_x
                    speed_x = calc_speed(dx, GAIN_X, deriv_x, KD_X, MIN_SPEED_X_RPM, MAX_SPEED_X_RPM)
                    speed_x = limit_x_speed(dx, speed_x)
                if motor_output_enabled:
                    send_order(uart_x, 1, dir_x, speed_x)
                else:
                    send_order(uart_x, 1, 0, 0)
            last_speed_x = speed_x

            # Buzzer timeout
            if buzz_until and time.ticks_diff(time.ticks_ms(), buzz_until) >= 0:
                buzzer.duty_u16(0)
                buzz_until = 0

            # 鍑嗘槦 + HUD
            raw_err_y = aim_y - cy_half
            speed_y = 0
            dir_y = last_dir_y if last_dir_y >= 0 else 0
            if y_brake_frames > 0:
                y_brake_frames -= 1
                last_filtered_err_y = 0
            elif abs(raw_err_y) >= DEAD_ZONE:
                filtered_err_y = (ALPHA_NUM * raw_err_y + (ALPHA_DEN - ALPHA_NUM) * filtered_err_y) // ALPHA_DEN
                deriv_y = abs(filtered_err_y) - abs(last_filtered_err_y)
                if filtered_err_y >= 0:
                    next_dir_y = 1  # Y axis is inverted mechanically.
                    dy = filtered_err_y
                else:
                    next_dir_y = 0
                    dy = -filtered_err_y

                if last_dir_y >= 0 and next_dir_y != last_dir_y and dy > Y_REVERSE_ERR:
                    last_filtered_err_y = 0
                    old_dir_y = last_dir_y
                    last_dir_y = next_dir_y
                    if last_speed_y > Y_REVERSE_BRAKE_SPEED:
                        speed_y = ramp_down(last_speed_y)
                        dir_y = old_dir_y
                    else:
                        dir_y = next_dir_y
                        speed_y = calc_reverse_speed(
                            dy, GAIN_Y, deriv_y, KD_Y,
                            MIN_SPEED_Y_RPM, MAX_SPEED_Y_RPM, Y_REVERSE_LIMIT_RPM)
                        speed_y = limit_y_speed(dy, speed_y)
                else:
                    last_filtered_err_y = filtered_err_y
                    dir_y = next_dir_y
                    last_dir_y = next_dir_y
                    speed_y = calc_speed(dy, GAIN_Y, deriv_y, KD_Y, MIN_SPEED_Y_RPM, MAX_SPEED_Y_RPM)
                    speed_y = limit_y_speed(dy, speed_y)
            else:
                last_filtered_err_y = 0

            img.draw_cross(cx_half, cy_half, color=(255, 0, 0), size=10, thickness=2)
            img.draw_circle(cx_half, cy_half, 4, color=(255, 0, 0), thickness=2, fill=False)
            img.draw_string_advanced(5, 5, 24,
                f"FPS:{clock.fps():.0f} HIT:{hits}", color=(255, 255, 255))
            img.draw_string_advanced(5, 34, 18,
                f"EX:{raw_err_x} EY:{raw_err_y} VX:{speed_x} VY:{speed_y}", color=(255, 255, 255))
            img.draw_string_advanced(5, 58, 16,
                f"TVX:{target_vel_x} TVY:{target_vel_y} {'RUN' if motor_output_enabled else 'STOP'}",
                color=(255, 255, 255))

            # 鏄剧ず
            Display.show_image(img, x=DISP_X, y=DISP_Y)

            # --- Y杞翠簯鍙版帶鍒?(鏄剧ず鍚庡彂閫?浜ら敊I/O) ---
            if not motor_output_enabled:
                send_order(uart_y, 2, 0, 0)
            elif speed_y == 0:
                send_order(uart_y, 2, 0, 0)
            else:
                send_order(uart_y, 2, dir_y, speed_y)
            last_speed_y = speed_y

            if tuner:
                tuner.send_stat({
                    "t": time.ticks_ms(),
                    "ex": raw_err_x,
                    "ey": raw_err_y,
                    "tx": target_x - cx_half,
                    "ty": target_y - cy_half,
                    "ax": aim_x - cx_half,
                    "ay": aim_y - cy_half,
                    "vx": speed_x if motor_output_enabled else 0,
                    "vy": speed_y if motor_output_enabled else 0,
                    "dirx": dir_x,
                    "diry": dir_y,
                    "fps": int(clock.fps()),
                    "found": 1 if tracking else 0,
                    "run": 1 if motor_output_enabled else 0,
                    "tvx": target_vel_x,
                    "tvy": target_vel_y,
                    "gx": GAIN_X,
                    "gy": GAIN_Y,
                    "kdx": KD_X,
                    "kdy": KD_Y,
                    "dead": DEAD_ZONE,
                    "minx": MIN_SPEED_X_RPM,
                    "miny": MIN_SPEED_Y_RPM,
                    "maxx": MAX_SPEED_X_RPM,
                    "maxy": MAX_SPEED_Y_RPM,
                }, interval_ms=STAT_INTERVAL_MS)
            if False:
                filtered_err_y = (ALPHA_NUM * raw_err_y + (ALPHA_DEN - ALPHA_NUM) * filtered_err_y) // ALPHA_DEN
                if filtered_err_y >= 0:
                    dir_y = 1  # Y杞存柟鍚戝弽杞?                    dy = filtered_err_y
                else:
                    dir_y = 0
                    dy = -filtered_err_y
                send_order(uart_y, 2, dir_y, dy * GAIN_Y)

            gc.collect()

    except KeyboardInterrupt:
        print("\n[EXIT] Stopped")
    except BaseException as e:
        print(f"[ERROR] {e}")
        sys.print_exception(e)
    finally:
        try:
            buzzer.duty_u16(0)
            buzzer.deinit()
        except:
            pass
        try:
            led_r.high(); led_g.high(); led_b.high()
        except:
            pass
        try:
            if uart_x:
                send_order(uart_x, 1, 0, 0)
            if uart_y:
                send_order(uart_y, 2, 0, 0)
        except:
            pass
        try:
            if tuner:
                tuner.close()
        except:
            pass
        if isinstance(sensor, Sensor):
            sensor.stop()
        Display.deinit()
        os.exitpoint(os.EXITPOINT_ENABLE_SLEEP)
        time.sleep_ms(100)
        MediaManager.deinit()


if __name__ == "__main__":
    main()


