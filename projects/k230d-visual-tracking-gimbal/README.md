# K230D 视觉追踪云台靶场

基于庐山派 Lite K230D CanMV 的两轴视觉追踪云台原型。K230D 负责摄像头采集、LAB 色块识别、ST7701 本地显示和 UART 电机控制；PC 网页上位机只负责无线调参、遥测曲线和数据导出。

## 功能

- GC2093 摄像头采集，ST7701 本地显示。
- `image.find_blobs()` LAB 色块追踪。
- UART4 控制 X 轴，UART3 控制 Y 轴。
- 张大头 X42_V1.3 闭环步进驱动，Emm V5 协议。
- 分段 P/D、最小速度补偿、限速、换向刹车和目标速度前馈预测。
- UDP 无线遥测和参数下发。
- PC 端网页调参台，支持曲线显示、CSV/PNG/JSON 导出。

## 目录

```text
k230d/
  tracking_main.py          # K230D 主程序
  wireless_tuning.py        # K230D UDP 调参通信
  test_all_hardware.py      # 基础外设综合测试
  test_motor_uart.py        # 电机串口测试
pc_tools/
  wireless_tuning_bridge.py # PC 网页上位机桥接服务
web/
  target_field.html         # 浏览器靶场页面示例
docs/
  K230D_庐山派Lite_阶段性评测报告.md
  images/
```

## 接线摘要

| 功能 | K230D 引脚 | 驱动板 |
| --- | --- | --- |
| X 轴 TX | GPIO36，UART4_TXD | X 驱动 RX |
| X 轴 RX | GPIO37，UART4_RXD | X 驱动 TX |
| Y 轴 TX | GPIO32，UART3_TXD | Y 驱动 RX |
| Y 轴 RX | GPIO33，UART3_RXD | Y 驱动 TX |
| 共地 | K230D GND | 驱动 GND/COM 与 12V 电源 GND |

驱动设置：X 轴地址 1，Y 轴地址 2，Emm V5，115200，Checksum 0x6B，Response=Receive，P_Serial=UART_FUN，En=Hold。

## 运行

1. 在 CanMV IDE 中先运行 `k230d/test_all_hardware.py` 验证基础外设。
2. 接好电机并确认安全限位后运行 `k230d/test_motor_uart.py` 验证 X/Y 轴。
3. 修改 `k230d/tracking_main.py` 中的 WiFi 占位符：

```python
WIFI_SSID = "YOUR_2G_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
```

4. 将 `tracking_main.py` 与 `wireless_tuning.py` 放到 CanMV 设备同一目录，运行 `tracking_main.py`。
5. PC 端运行：

```bash
python pc_tools/wireless_tuning_bridge.py
```

6. 浏览器打开：

```text
http://127.0.0.1:8088
```

## 评测报告

详见：`docs/K230D_庐山派Lite_阶段性评测报告.md`

## 注意

- 不做 Web 视频推流，视频只在 ST7701 本地显示。
- PC 网页只传输小包遥测和调参命令，避免占用 K230D 图像处理资源。
- 公开仓库中的 WiFi 配置已脱敏，运行前需要自行填写。
