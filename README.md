# K230 / K230D Vision Projects

本仓库用于整理 K230/K230D 视觉识别、显示交互、串口控制和上位机调参相关项目。

## 项目列表

### 1. K230 矩形检测与激光定位系统

原始项目位于仓库根目录的 `src/`、`config/`、`docs/`、`examples/`。该项目用于 A4 纸张矩形检测、激光点偏差计算和串口数据输出。

主要入口：

- `src/rectangle_detection.py`
- `config/detection_config.py`
- `docs/hardware_setup.md`

### 2. K230D 视觉追踪云台靶场

新增项目位于：

```text
projects/k230d-visual-tracking-gimbal/
```

该项目基于庐山派 Lite K230D CanMV：

- 摄像头 + ST7701 本地显示。
- LAB 色块视觉追踪。
- UART3/UART4 控制 X/Y 两轴张大头 X42_V1.3 闭环步进驱动。
- PC 网页无线调参上位机。
- 阶段性评测报告和测试照片。

快速入口：

- `projects/k230d-visual-tracking-gimbal/README.md`
- `projects/k230d-visual-tracking-gimbal/k230d/tracking_main.py`
- `projects/k230d-visual-tracking-gimbal/pc_tools/wireless_tuning_bridge.py`
- `projects/k230d-visual-tracking-gimbal/docs/K230D_庐山派Lite_阶段性评测报告.md`

## 依赖说明

K230/K230D 板端代码运行在 CanMV MicroPython 环境中。PC 上位机部分优先使用 Python 标准库，避免额外依赖。

## 隐私说明

公开代码中的 WiFi SSID、密码和个人本地路径均已脱敏。运行前请在本地配置实际网络参数。

## License

见 `LICENSE`。
