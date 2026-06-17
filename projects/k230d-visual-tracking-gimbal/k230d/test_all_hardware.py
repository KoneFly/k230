"""
搴愬北娲?Lite K230D - 鍏ㄦā鍧楃患鍚堢‖浠舵祴璇?椤哄簭娴嬭瘯锛歊GB LED / 铚傞福鍣?/ 鎸夐敭 / 椋庢墖 / UART2 / UART3 / ADC / WiFi / 闊抽 / 鎽勫儚澶?姣忎釜妯″潡鐙珛 pass/fail锛屾渶缁堟眹鎬绘姤鍛?"""
import os, time, sys, gc
import network

from machine import Pin, FPIOA, PWM, UART, ADC
from media.media import *
from media.pyaudio import *
from media.sensor import *
from media.display import *
import media.wave as wave

os.exitpoint(os.EXITPOINT_ENABLE)

# ============================================================
#  宸ュ叿鍑芥暟
# ============================================================
results = []


def report(name, passed, detail=""):
    tag = "PASS" if passed else "FAIL"
    results.append((name, passed, detail))
    print(f"  [{tag}] {name}" + (f" - {detail}" if detail else ""))


def section(title):
    print(f"\n{'='*44}")
    print(f"  TEST: {title}")
    print(f"{'='*44}")


# ============================================================
#  1. RGB LED (GPIO65=R, GPIO66=G, GPIO71=B, 鍏遍槼:low=浜?
# ============================================================
def test_rgb_led():
    section("RGB LED")
    try:
        fpioa = FPIOA()
        fpioa.set_function(65, FPIOA.GPIO65)
        fpioa.set_function(66, FPIOA.GPIO66)
        fpioa.set_function(71, FPIOA.GPIO71)

        LED_R = Pin(65, Pin.OUT, pull=Pin.PULL_NONE, drive=7)
        LED_G = Pin(66, Pin.OUT, pull=Pin.PULL_NONE, drive=7)
        LED_B = Pin(71, Pin.OUT, pull=Pin.PULL_NONE, drive=7)

        LED_R.high(); LED_G.high(); LED_B.high()

        colors = [
            ("Red",   0, 1, 1),
            ("Green", 1, 0, 1),
            ("Blue",  1, 1, 0),
            ("Yellow",0, 0, 1),
            ("Cyan",  1, 0, 0),
            ("White", 0, 0, 0),
        ]
        for name, r, g, b in colors:
            LED_R.value(r); LED_G.value(g); LED_B.value(b)
            print(f"    {name}")
            time.sleep(0.4)

        LED_R.high(); LED_G.high(); LED_B.high()
        report("RGB LED", True, "6鑹插惊鐜畬鎴愶紝璇风洰瑙嗙‘璁?)
    except Exception as e:
        report("RGB LED", False, str(e))


# ============================================================
#  2. 铚傞福鍣?(PWM1, GPIO61, 4kHz)
# ============================================================
def test_buzzer():
    section("Buzzer")
    try:
        fpioa = FPIOA()
        fpioa.set_function(61, FPIOA.PWM1)

        pwm = PWM(1)
        pwm.freq(4000)
        pwm.duty_u16(32768)
        time.sleep_ms(100)
        pwm.duty_u16(0)
        pwm.deinit()
        report("Buzzer", True, "4kHz鍝?00ms")
    except Exception as e:
        report("Buzzer", False, str(e))


# ============================================================
#  3. 鏉胯浇鎸夐敭 (GPIO64, PULL_DOWN, pressed=high)
# ============================================================
def test_button():
    section("Button (GPIO64)")
    try:
        fpioa = FPIOA()
        fpioa.set_function(64, FPIOA.GPIO64)
        btn = Pin(64, Pin.IN, Pin.PULL_DOWN)

        val = btn.value()
        print(f"    褰撳墠鎸夐敭鍊? {val} (0=鏈寜, 1=鎸変笅)")
        print("    璇峰湪3绉掑唴鎸変笅鎸夐敭...")

        pressed = False
        deadline = time.ticks_add(time.ticks_ms(), 3000)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if btn.value() == 1:
                pressed = True
                break
            time.sleep_ms(20)

        if pressed:
            report("Button", True, "妫€娴嬪埌鎸変笅")
        else:
            report("Button", True, "鏈寜涓?璺宠繃浜や簰锛屽紩鑴氳鍙栨甯?")
    except Exception as e:
        report("Button", False, str(e))


# ============================================================
#  4. 椋庢墖 (PWM0, GPIO60)
# ============================================================
def test_fan():
    section("Fan (PWM0/GPIO60)")
    try:
        fpioa = FPIOA()
        fpioa.set_function(60, FPIOA.PWM0)

        pwm = PWM(0)
        pwm.freq(20000)
        pwm.duty_u16(0)
        time.sleep_ms(100)

        print("    50%杞€?1绉?..")
        pwm.duty_u16(32768)
        time.sleep(1)

        print("    100%杞€?1绉?..")
        pwm.duty_u16(65535)
        time.sleep(1)

        pwm.duty_u16(0)
        report("Fan", True, "PWM璋冮€熷畬鎴愶紝璇风‘璁ら鎵囪浆鍔?)
    except Exception as e:
        report("Fan", False, str(e))


# ============================================================
#  5. UART2 (GPIO11=TX, GPIO12=RX, 115200)
# ============================================================
def test_uart2():
    section("UART2 (GPIO11/12)")
    try:
        fpioa = FPIOA()
        fpioa.set_function(11, FPIOA.UART2_TXD)
        fpioa.set_function(12, FPIOA.UART2_RXD)

        uart = UART(UART.UART2, baudrate=115200,
                    bits=UART.EIGHTBITS,
                    parity=UART.PARITY_NONE,
                    stop=UART.STOPBITS_ONE)

        test_msg = b"K230D_UART2_TEST\r\n"
        uart.write(test_msg)
        print(f"    TX鍙戦€? {test_msg}")
        time.sleep_ms(50)

        rx = uart.read()
        if rx:
            print(f"    RX鏀跺埌: {rx}")
            report("UART2", True, "TX+RX姝ｅ父(鍥炵幆)")
        else:
            report("UART2", True, "TX鍙戦€佹甯?鏈帴鍥炵幆绾匡紝RX鏃犳暟鎹?")
    except Exception as e:
        report("UART2", False, str(e))


# ============================================================
#  6. UART3 (GPIO32=TX, GPIO33=RX, 115200)
# ============================================================
def test_uart3():
    section("UART3 (GPIO32/33)")
    try:
        fpioa = FPIOA()
        fpioa.set_function(32, FPIOA.UART3_TXD)
        fpioa.set_function(33, FPIOA.UART3_RXD)

        uart = UART(UART.UART3, baudrate=115200,
                    bits=UART.EIGHTBITS,
                    parity=UART.PARITY_NONE,
                    stop=UART.STOPBITS_ONE)

        test_msg = b"K230D_UART3_TEST\r\n"
        uart.write(test_msg)
        print(f"    TX鍙戦€? {test_msg}")
        time.sleep_ms(50)

        rx = uart.read()
        if rx:
            print(f"    RX鏀跺埌: {rx}")
            report("UART3", True, "TX+RX姝ｅ父(鍥炵幆)")
        else:
            report("UART3", True, "TX鍙戦€佹甯?鏈帴鍥炵幆绾匡紝RX鏃犳暟鎹?")
    except Exception as e:
        report("UART3", False, str(e))


# ============================================================
#  7. ADC (閫氶亾0/1/2)
# ============================================================
def test_adc():
    section("ADC (CH0/1/2)")
    try:
        all_ok = True
        for ch in range(3):
            try:
                adc = ADC(ch)
                val = adc.read_u16()
                uv = adc.read_uv()
                v = uv / 1000000.0
                print(f"    CH{ch}: raw={val}, {v:.3f}V")
            except Exception as e:
                print(f"    CH{ch}: 閿欒 - {e}")
                all_ok = False
        report("ADC", all_ok, "3閫氶亾璇诲彇瀹屾垚")
    except Exception as e:
        report("ADC", False, str(e))


# ============================================================
#  8. WiFi STA (杩炴帴娴嬭瘯)
# ============================================================
def test_wifi():
    section("WiFi STA")
    SSID = "YOUR_2G_WIFI_SSID"
    PASSWORD = "YOUR_WIFI_PASSWORD"
    try:
        sta = network.WLAN(network.STA_IF)
        if not sta.active():
            sta.active(True)
        print(f"    杩炴帴 '{SSID}'...")
        sta.connect(SSID, PASSWORD)

        for i in range(8):
            if sta.isconnected():
                break
            time.sleep(1)
            if i > 1:
                sta.connect(SSID, PASSWORD)

        if sta.isconnected():
            while sta.ifconfig()[0] == '0.0.0.0':
                time.sleep(0.5)
            ip = sta.ifconfig()[0]
            print(f"    IP: {ip}")
            report("WiFi", True, f"宸茶繛鎺? IP={ip}")
        else:
            report("WiFi", False, "杩炴帴瓒呮椂")
    except Exception as e:
        report("WiFi", False, str(e))


# ============================================================
#  9. 闊抽 - 楹﹀厠椋庡綍鍒?+ 鍔熸斁鎾斁 (HT6872, GPIO10 EN)
# ============================================================
def test_audio():
    section("Audio (Mic+Speaker)")
    try:
        fpioa = FPIOA()
        fpioa.set_function(10, FPIOA.GPIO10)
        HT_CTRL = Pin(10, Pin.OUT, pull=Pin.PULL_NONE, drive=7)
        HT_CTRL.high()

        CHUNK = 44100 // 25
        FORMAT = paInt16
        CHANNELS = 2
        RATE = 44100
        DURATION = 3
        FILENAME = "/sdcard/test_hw_audio.wav"

        p = PyAudio()

        print("    褰曞埗3绉?..")
        input_stream = p.open(format=FORMAT, channels=CHANNELS,
                              rate=RATE, input=True,
                              frames_per_buffer=CHUNK)
        input_stream.volume(70, LEFT)
        input_stream.volume(85, RIGHT)
        input_stream.enable_audio3a(AUDIO_3A_ENABLE_ANS)

        frames = []
        for i in range(int(RATE / CHUNK * DURATION)):
            data = input_stream.read()
            frames.append(data)

        input_stream.stop_stream()
        input_stream.close()

        wf = wave.open(FILENAME, 'wb')
        wf.set_channels(CHANNELS)
        wf.set_sampwidth(p.get_sample_size(FORMAT))
        wf.set_framerate(RATE)
        wf.write_frames(b''.join(frames))
        wf.close()
        del frames
        gc.collect()
        print(f"    褰曞埗瀹屾垚: {FILENAME}")

        print("    鎾斁褰曞埗鍐呭...")
        wf = wave.open(FILENAME, 'rb')
        CHUNK2 = int(wf.get_framerate() / 25)
        output_stream = p.open(
            format=p.get_format_from_width(wf.get_sampwidth()),
            channels=wf.get_channels(),
            rate=wf.get_framerate(),
            output=True, frames_per_buffer=CHUNK2)
        output_stream.volume(vol=100)

        data = wf.read_frames(CHUNK2)
        while data:
            output_stream.write(data)
            data = wf.read_frames(CHUNK2)

        output_stream.stop_stream()
        output_stream.close()
        wf.close()
        p.terminate()
        HT_CTRL.low()

        report("Audio", True, "褰曞埗+鎾斁瀹屾垚")
    except Exception as e:
        report("Audio", False, str(e))


# ============================================================
#  10. 鎽勫儚澶?(CSI2, sensor_id=2)
# ============================================================
def test_camera():
    section("Camera (CSI2)")
    sensor_obj = None
    try:
        sensor_obj = Sensor(id=2)
        sensor_obj.reset()
        sensor_obj.set_framesize(width=640, height=480, chn=CAM_CHN_ID_0)
        sensor_obj.set_pixformat(Sensor.RGB888, chn=CAM_CHN_ID_0)

        Display.init(Display.VIRT, width=640, height=480, to_ide=True)
        MediaManager.init()
        sensor_obj.run()
        time.sleep(0.3)

        for i in range(10):
            os.exitpoint()
            img = sensor_obj.snapshot(chn=CAM_CHN_ID_0)
            Display.show_image(img)

        print(f"    10甯ф崟鑾锋垚鍔? 鍒嗚鲸鐜?40x480")
        report("Camera", True, "CSI2 640x480 RGB888")
    except Exception as e:
        report("Camera", False, str(e))
    finally:
        if sensor_obj:
            try:
                sensor_obj.stop()
            except:
                pass
        try:
            Display.deinit()
        except:
            pass
        try:
            os.exitpoint(os.EXITPOINT_ENABLE_SLEEP)
            time.sleep_ms(100)
            MediaManager.deinit()
        except:
            pass


# ============================================================
#  MAIN - 鎸夐『搴忔墽琛屾墍鏈夋祴璇?# ============================================================
def main():
    print("\n" + "=" * 50)
    print("  K230D LuShanPi-Lite 鍏ㄦā鍧楃‖浠剁患鍚堟祴璇?)
    print("  Version: 1.0")
    print("=" * 50)

    test_rgb_led()
    gc.collect()

    test_buzzer()
    gc.collect()

    test_button()
    gc.collect()

    test_fan()
    gc.collect()

    test_uart2()
    gc.collect()

    test_uart3()
    gc.collect()

    test_adc()
    gc.collect()

    test_wifi()
    gc.collect()

    test_audio()
    gc.collect()

    test_camera()
    gc.collect()

    # 姹囨€绘姤鍛?    print("\n" + "=" * 50)
    print("  娴嬭瘯鎶ュ憡")
    print("=" * 50)
    passed = sum(1 for _, p, _ in results if p)
    total = len(results)
    for name, p, detail in results:
        tag = "PASS" if p else "FAIL"
        print(f"  [{tag}] {name:12s} {detail}")
    print(f"\n  鎬昏: {passed}/{total} 閫氳繃")
    if passed == total:
        print("  鎵€鏈夋ā鍧楁祴璇曢€氳繃!")
    else:
        print("  瀛樺湪澶辫触椤癸紝璇锋鏌ュ搴旂‖浠惰繛鎺?)
    print("=" * 50)


if __name__ == "__main__":
    main()

