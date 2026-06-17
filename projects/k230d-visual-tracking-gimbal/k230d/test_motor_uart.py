"""
K230D pan-tilt motor UART protocol probe.

Wiring used by the current project:
- X axis: UART4, GPIO36 TX -> driver RX, GPIO37 RX <- driver TX, driver address 1
- Y axis: UART3, GPIO32 TX -> driver RX, GPIO33 RX <- driver TX, driver address 2
- K230D GND, regulator GND, and both driver GND/COM must be common.
"""
import time
from machine import FPIOA, UART


BAUD = 115200
SPEED_RPM = 100
ACC = 10
RUN_MS = 1200
PAUSE_MS = 800


def uart_id(n):
    name = "UART%d" % n
    return getattr(UART, name) if hasattr(UART, name) else n


def make_uart(n):
    return UART(uart_id(n),
                baudrate=BAUD,
                bits=UART.EIGHTBITS,
                parity=UART.PARITY_NONE,
                stop=UART.STOPBITS_ONE)


def build_v2_speed_frame(addr, direction, speed_rpm):
    ramp = 1000
    speed_x10 = max(0, min(int(speed_rpm * 10), 0xFFFF))
    return bytes([
        addr & 0xFF,
        0xF6,
        direction & 0x01,
        (ramp >> 8) & 0xFF,
        ramp & 0xFF,
        (speed_x10 >> 8) & 0xFF,
        speed_x10 & 0xFF,
        0x00,
        0x6B,
    ])


def build_emm_enable_frame(addr, enable):
    return bytes([addr & 0xFF, 0xF3, 0xAB, 0x01 if enable else 0x00, 0x00, 0x6B])


def build_emm_speed_frame(addr, direction, speed_rpm):
    speed = max(0, min(int(speed_rpm), 0xFFFF))
    return bytes([
        addr & 0xFF,
        0xF6,
        direction & 0x01,
        (speed >> 8) & 0xFF,
        speed & 0xFF,
        ACC & 0xFF,
        0x00,
        0x6B,
    ])


def build_emm_stop_frame(addr):
    return bytes([addr & 0xFF, 0xFE, 0x98, 0x00, 0x6B])


def build_old_speed_frame(addr, direction, speed):
    speed = max(0, min(int(speed), 0xFFFF))
    return bytes([
        addr & 0xFF,
        0xF6,
        direction & 0x01,
        0xFF,
        0xFF,
        (speed >> 8) & 0xFF,
        speed & 0xFF,
        0x00,
        0x6B,
    ])


def send_frame(uart, label, frame):
    uart.write(frame)
    print("  TX %-12s %s" % (label, frame))
    time.sleep_ms(100)
    rx = uart.read()
    if rx:
        print("  RX:", rx)


def stop_axis(uart, addr):
    send_frame(uart, "emm-stop", build_emm_stop_frame(addr))
    send_frame(uart, "old-stop", build_old_speed_frame(addr, 0, 0))


def test_axis(name, uart, addr):
    print("")
    print("[%s] address=%d" % (name, addr))
    print("  enable")
    send_frame(uart, "emm-enable", build_emm_enable_frame(addr, True))
    time.sleep_ms(PAUSE_MS)

    print("  Emm V5 CW/run")
    send_frame(uart, "emm-cw", build_emm_speed_frame(addr, 0, SPEED_RPM))
    time.sleep_ms(RUN_MS)

    print("  stop")
    stop_axis(uart, addr)
    time.sleep_ms(PAUSE_MS)

    print("  Emm V5 CCW/run")
    send_frame(uart, "emm-ccw", build_emm_speed_frame(addr, 1, SPEED_RPM))
    time.sleep_ms(RUN_MS)

    print("  stop")
    stop_axis(uart, addr)
    time.sleep_ms(PAUSE_MS)

    print("  V2 CW/run")
    send_frame(uart, "v2-cw", build_v2_speed_frame(addr, 0, SPEED_RPM))
    time.sleep_ms(RUN_MS)

    print("  stop")
    stop_axis(uart, addr)
    time.sleep_ms(PAUSE_MS)


def main():
    print("============================================")
    print("  K230D Motor UART Smoke Test")
    print("============================================")
    print("Check before running:")
    print("  1) Driver power is 12V")
    print("  2) K230D GND and driver GND/COM are common")
    print("  3) Driver baud=115200, checksum=0x6B, response=Receive")
    print("  4) X addr=1, Y addr=2")

    fpioa = FPIOA()
    fpioa.set_function(36, FPIOA.UART4_TXD)
    fpioa.set_function(37, FPIOA.UART4_RXD)
    fpioa.set_function(32, FPIOA.UART3_TXD)
    fpioa.set_function(33, FPIOA.UART3_RXD)

    uart_x = make_uart(4)
    uart_y = make_uart(3)

    try:
        test_axis("X/UART4 GPIO36-37", uart_x, 1)
        test_axis("Y/UART3 GPIO32-33", uart_y, 2)
        print("")
        print("[DONE] If neither axis moved, check TTL/UART mode and TX/RX cross wiring.")
    finally:
        stop_axis(uart_x, 1)
        stop_axis(uart_y, 2)


main()
