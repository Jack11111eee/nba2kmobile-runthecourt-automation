# NBA 2K Mobile Run The Court Automation

[English](README.en.md) | **简体中文**

一个仅在本机运行的 macOS/Windows 命令行工具。macOS 默认通过 Apple 的
`iPhone Mirroring` 窗口读取和控制 NBA 2K Mobile；Windows 实验性后端通过 USB
直接获取 iPhone 截图并发送触摸。两种后端共用本地模板、颜色和布局规则，并且只
在白名单页面执行动作。

项目不会调用云端视觉模型，也不会上传截图、日志或游戏数据。

> 当前状态：Alpha。已在 iPhone 15 Pro、iOS 18.6.2、中文横屏界面和
> macOS iPhone Mirroring 环境下完成实机验证。2026-07-23 的单场真实点击测试
> 未观察到点击异常。游戏更新或 UI 变化后必须重新执行 dry-run 验证。
> Windows 后端已通过自动化测试，但尚未完成真实
> Windows+iPhone USB 实机验收。

## 安全设计

- 所有识别都在电脑本地完成。
- 比赛画面、自动换人、未知页面和低置信度状态不会点击。
- 所有自动动作必须连续两帧识别一致。
- 点击前重新检查镜像窗口或 USB 设备身份。
- 点击坐标必须位于归一化画面范围内。
- 点击后等待画面变化，避免在同一页面重复操作。
- 只有明确识别到 `WIN` 才会继续；失败结果会暂停并发送通知。
- 购买、付费重播、返回和设置区域不在动作白名单中。

本工具不能保证账号安全或符合游戏服务条款。使用前请自行评估封号、活动规则和
自动化使用风险。

## 系统要求

- Python 3.13
- 游戏使用当前支持的中文横屏 UI

macOS 镜像后端：

- 支持 iPhone Mirroring 的 Mac 和 iPhone
- macOS 中已可正常打开并控制 iPhone Mirroring
- 终端拥有“屏幕与系统音频录制”和“辅助功能”权限

Windows USB 后端（实验性）：

- x86-64 Windows 10 或 Windows 11
- iOS 17.4 或更高版本的 iPhone
- 已安装 Microsoft Store 中的 Apple Devices，以提供 USB 驱动
- iPhone 已信任电脑并开启 Developer Mode
- 已挂载与当前 iOS 匹配的 Developer Disk Image

离线识别测试仍可在其他系统运行。

## macOS 安装

```bash
git clone https://github.com/Jack11111eee/nba2kmobile-runthecourt-automation.git
cd nba2kmobile-runthecourt-automation

python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
```

`requirements.lock` 用于复现已验证的 macOS 环境；`pyproject.toml` 保存项目的
运行依赖和平台标记。

## Windows 安装

```powershell
git clone https://github.com/Jack11111eee/nba2kmobile-runthecourt-automation.git
cd nba2kmobile-runthecourt-automation

py -3.13 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[ios-usb]"
```

连接并解锁 iPhone，在手机上选择信任电脑并开启 Developer Mode，然后挂载
Developer Disk Image：

```powershell
python -m pymobiledevice3 mounter auto-mount
```

`pymobiledevice3` 是 GPL-3.0-or-later 的可选依赖，只在使用 `ios-usb` 后端时
安装。

## macOS 权限与检查

1. 打开 iPhone Mirroring 并连接手机。
2. 打开 NBA 2K Mobile，保持镜像窗口可见且不要最小化。
3. 执行：

```bash
python -m rtc_bot doctor --backend macos-mirroring
```

首次运行时，macOS 会请求：

- 屏幕与系统音频录制权限
- 辅助功能权限

授权后重新打开终端并再次运行 `doctor`。成功输出应包含：

```text
screen capture permission: OK
accessibility/event permission: OK
device capture: OK
detected state: ...
```

检查截图保存在 `runtime/doctor/`，仅供本机诊断。

## Windows 连接检查

完成 Windows 安装和 DDI 挂载后执行：

```powershell
python -m rtc_bot doctor --backend ios-usb
```

成功输出应包含 USB 设备型号、iOS 版本、UDID、截图尺寸和识别状态。Windows
默认会自动选择 `ios-usb`，显式参数便于排查配置。

## 使用

先从 Run The Court 的已知页面进入检测模式：

```bash
python -m rtc_bot run --dry-run --debug
```

确认终端显示的状态和计划点击位置正确后，再启动真实点击：

```bash
python -m rtc_bot run --debug
```

建议给无人值守运行设置明确边界。例如最多完成 5 场、最多运行 30 分钟，并在失败
后直接退出：

```bash
python -m rtc_bot run --max-games 5 --max-duration 30 --on-loss exit
```

可用的运行限制包括：

- `--max-games N`：确认完成 N 场后停止，不继续点击结果页。
- `--max-duration MINUTES`：到达时限后停止，截图或设备连接中断时间也计入。
- `--stop-after-win`：确认胜利后停止，不进入奖励流程。
- `--on-loss pause|exit`：失败后永久暂停，或保存报告并退出。
- `--capture-limit-mb MB`：限制 `runtime/captures/` 总大小，默认 256 MB。

在 Mac 上也可以测试与 Windows 相同的直接 USB 通道：

```bash
python -m pip install -e ".[ios-usb]"
python -m pymobiledevice3 mounter auto-mount
python -m rtc_bot run --backend ios-usb --dry-run --debug
```

也可以使用安装后的入口：

```bash
rtc-bot doctor
rtc-bot run --dry-run --debug
rtc-bot run --debug
```

按 `Ctrl+C` 手动停止。运行时会使用 macOS `caffeinate` 或 Windows 电源 API
阻止电脑自动睡眠。

## 状态策略

| 页面 | 行为 |
| --- | --- |
| 活动主页、关卡列表、对阵页 | 点击识别到的绿色开始按钮 |
| 阵容/加成页 | 只点击右下角跳过按钮 |
| 正常比赛 | 等待，不点击 |
| 自动换人 | 等待游戏自行恢复 |
| 节间奖励卡 | 等待自动翻页；5 秒不变后补点卡片中心一次 |
| 胜利结果 | 识别到 `WIN` 后点击继续 |
| 失败结果 | 永久暂停并发送平台提示 |
| 未开启卡包 | 验证卡包页面结构后点击中央卡包 |
| 背面奖励卡 | 点击左下角显示全部 |
| 翻卡动画 | 等待 |
| 奖励汇总 | 点击右下角继续 |
| 网络异常、能量不足、背包已满、维护、活动结束 | 专用模板或 macOS 本地 OCR 确认后停止并通知 |
| 主菜单、其他未知页面 | 无限等待人工处理 |

## 日志与隐私

运行数据保存在 `runtime/`：

- `runtime/logs/`：逐帧 JSONL 状态和动作日志
- `runtime/captures/`：调试截图、暂停截图和点击前截图
- `runtime/doctor/`：权限检查截图
- `runtime/reports/`：每次结束时生成的 JSON 会话汇总

截图目录默认限制为 256 MB。写入新截图后，工具会优先删除最旧的 PNG，并始终
保留刚写入的最新截图。`--debug` 只在稳定状态变化时保存截图。

这些文件可能包含游戏昵称、阵容、资源数量、通知内容和完整手机镜像画面。
`runtime/` 已被 Git 忽略，不应上传、提交到 Issue，或直接发送给第三方。公开分享
前请先脱敏。

仓库中的测试素材已移除图片元数据，并遮盖对阵页和结果页中的游戏昵称。

## 测试

运行全部离线测试：

```bash
python -m unittest discover -s tests -v
python -m compileall -q rtc_bot tests tools
python -m pip check
```

最近一次实机验证于 2026-07-23 使用 `live` 模式和 15 分钟上限完成。会话报告
记录了 1,797 帧和 8 次白名单点击，并在 902.4 秒后因 900 秒时限正常停止。
运行生成了 JSON 会话汇总和 109 张截图；`runtime/captures/` 最终保持在配置的
256 MB 上限内。该次报告的胜负计数均为 0，因此这条记录验证了真实点击、时限
停止、会话报告和截图保留，但不视为结果页或异常 OCR 流程验证。

使用录屏进行离线回放：

```bash
python tools/replay_check.py /path/to/recording.mov
```

回放工具需要系统安装 `ffmpeg`。它只读取输入视频并在临时目录中提取帧。

## 项目结构

```text
rtc_bot/
  bridge.py       跨平台后端接口和选择
  cli.py          命令行入口和运行循环
  engine.py       稳定帧、冷却、状态变化与动作决策
  exceptions.py   本地 OCR 和已知异常消息分类
  ios_device.py   iPhone USB 截图和触摸事件
  macos.py        iPhone Mirroring 窗口抓取和鼠标事件
  session.py      场次、时限、胜负和停止策略
  vision.py       本地模板、颜色和布局识别
  runtime.py      JSONL 日志、受限截图、报告、通知和防休眠
  assets/         运行时识别模板
tests/            单元测试、流程测试和脱敏夹具
tools/            离线回放与素材清理工具
```

## 已知限制

- 识别器针对当前已采集的中文 UI，其他语言和分辨率未验证。
- 游戏更新、活动换皮、窗口比例变化或系统升级可能降低识别准确率。
- 网络错误、能量不足、背包上限、维护和活动结束页面尚未全部获得专用素材；
  macOS 当前通过本地文字识别和中英文关键词补充检测；Windows USB 后端在没有
  专用模板匹配时仍等待人工处理。
- iPhone Mirroring 窗口消失、最小化、黑帧或位置在识别后变化时会取消点击；
  USB 后端在设备身份或截图尺寸发生变化时也会取消触摸。
- Windows USB 后端尚未在真实 Windows+iPhone 环境完成验收；CI 只能验证安装、
  导入和模拟设备流程。
- USB 后端需要 iOS Developer Mode 和已挂载的 Developer Disk Image；手机重启
  或 iOS 更新后可能需要重新挂载。
- 工具不会从 NBA 2K 主菜单自动寻找并重新进入活动。

## 免责声明

本项目与 NBA、2K Games、Visual Concepts 或 Apple 没有关联。仓库中的商标和
界面截图仅用于本地互操作、状态识别和回归测试，其权利归各自权利人所有。
