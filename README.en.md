# NBA 2K Mobile Run The Court Automation

**English** | [Simplified Chinese](README.md)

A local-only macOS and Windows command-line tool. macOS uses Apple's
`iPhone Mirroring` window by default; the experimental Windows backend captures
the iPhone and sends touches directly over USB. Both backends share the same
local templates, color rules, layout rules, and action allowlist.

The project does not use cloud vision models or upload screenshots, logs, or
game data.

> Current status: Alpha. The tool has been validated on an iPhone 15 Pro
> running iOS 18.6.2, with the game in its Chinese landscape UI through macOS
> iPhone Mirroring. Run a new dry run after any game or UI update. The Windows
> backend has automated coverage but has not completed a real
> Windows+iPhone USB acceptance test.

## Safety Model

- All recognition runs locally on the computer.
- The bot does not click during gameplay, automatic substitutions, unknown
  screens, or low-confidence states.
- Every automated action requires the same state to be recognized in two
  consecutive frames.
- The mirror window or USB device identity is checked again before each click.
- Click coordinates must remain inside the normalized game frame.
- After a click, the bot waits for the screen to change before allowing another
  action on that screen.
- The bot continues only after explicitly recognizing `WIN`; a loss pauses the
  bot and sends a notification.
- Purchase, paid replay, back, and settings areas are not allowlisted.

This tool cannot guarantee account safety or compliance with the game's terms
of service. Evaluate the risks of automation, account restrictions, and event
rules before using it.

## Requirements

- Python 3.13
- The currently supported Chinese landscape game UI

macOS mirroring backend:

- A Mac and iPhone that support iPhone Mirroring
- A working iPhone Mirroring connection that can control the phone
- Screen & System Audio Recording and Accessibility permissions for the
  terminal application

Experimental Windows USB backend:

- x86-64 Windows 10 or Windows 11
- An iPhone running iOS 17.4 or later
- Apple Devices from the Microsoft Store for the USB driver
- A trusted computer connection and Developer Mode enabled on the iPhone
- A Developer Disk Image matching the current iOS version

Offline recognition tests can still run on other operating systems.

## macOS Installation

```bash
git clone https://github.com/Jack11111eee/nba2kmobile-runthecourt-automation.git
cd nba2kmobile-runthecourt-automation

python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
```

`requirements.lock` reproduces the validated macOS environment.
`pyproject.toml` contains the runtime dependencies and platform markers.

## Windows Installation

```powershell
git clone https://github.com/Jack11111eee/nba2kmobile-runthecourt-automation.git
cd nba2kmobile-runthecourt-automation

py -3.13 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[ios-usb]"
```

Connect and unlock the iPhone, trust the computer, enable Developer Mode, and
mount the Developer Disk Image:

```powershell
python -m pymobiledevice3 mounter auto-mount
```

`pymobiledevice3` is an optional GPL-3.0-or-later dependency installed only for
the `ios-usb` backend.

## macOS Permissions and Diagnostics

1. Open iPhone Mirroring and connect the phone.
2. Open NBA 2K Mobile. Keep the mirror window visible and not minimized.
3. Run:

```bash
python -m rtc_bot doctor --backend macos-mirroring
```

On first use, macOS will request:

- Screen & System Audio Recording permission
- Accessibility permission

After granting access, reopen the terminal and run `doctor` again. A successful
check should include:

```text
screen capture permission: OK
accessibility/event permission: OK
device capture: OK
detected state: ...
```

The diagnostic screenshot is saved under `runtime/doctor/` for local
troubleshooting only.

## Windows Connection Check

After installation and DDI mounting, run:

```powershell
python -m rtc_bot doctor --backend ios-usb
```

A successful check reports the USB device model, iOS version, UDID, screenshot
dimensions, and detected state. Windows selects `ios-usb` automatically; the
explicit option is useful while troubleshooting.

## Usage

Start from a known Run The Court screen and verify detection without clicking:

```bash
python -m rtc_bot run --dry-run --debug
```

After confirming that the reported states and planned click positions are
correct, enable real clicks:

```bash
python -m rtc_bot run --debug
```

The Windows-style direct USB path can also be tested from a Mac:

```bash
python -m pip install -e ".[ios-usb]"
python -m pymobiledevice3 mounter auto-mount
python -m rtc_bot run --backend ios-usb --dry-run --debug
```

The installed entry point provides the same commands:

```bash
rtc-bot doctor
rtc-bot run --dry-run --debug
rtc-bot run --debug
```

Press `Ctrl+C` to stop manually. The tool uses macOS `caffeinate` or the
Windows power API to prevent the computer from sleeping.

## State Policy

| Screen | Behavior |
| --- | --- |
| Event home, stage list, matchup screen | Click the recognized green Start button |
| Lineup or bonus screen | Click only the Skip button in the lower-right corner |
| Normal gameplay | Wait; do not click |
| Automatic substitution | Wait for the game to resume by itself |
| Between-quarter reward card | Wait for automatic advance; click the card center once if unchanged for 5 seconds |
| Win result | Click Continue only after recognizing `WIN` |
| Loss result | Pause indefinitely and send a platform alert |
| Unopened reward pack | Click the center pack only after validating the pack layout |
| Face-down reward cards | Click Show All in the lower-left corner |
| Card-flip animation | Wait |
| Reward summary | Click Continue in the lower-right corner |
| Main menu, network error, insufficient energy, unknown screen | Wait indefinitely for manual intervention |

## Logs and Privacy

Runtime data is stored under `runtime/`:

- `runtime/logs/`: per-frame JSONL state and action logs
- `runtime/captures/`: debug, pause, and pre-click screenshots
- `runtime/doctor/`: diagnostic screenshots

These files may contain player names, lineups, resource counts, notification
text, and complete phone mirror frames. The repository ignores `runtime/`.
Do not upload it, attach it to an issue, or send it to third parties without
redacting private information first.

The test assets included in the repository have had image metadata removed and
player names covered on matchup and result screens.

## Testing

Run the complete offline test suite:

```bash
python -m unittest discover -s tests -v
python -m compileall -q rtc_bot tests tools
python -m pip check
```

Replay a recording offline:

```bash
python tools/replay_check.py /path/to/recording.mov
```

The replay tool requires `ffmpeg` to be installed. It only reads the input
video and extracts frames into a temporary directory.

## Project Structure

```text
rtc_bot/
  bridge.py       Cross-platform backend interface and selection
  cli.py          Command-line interface and runtime loop
  engine.py       Stable-frame, cooldown, state-change, and action decisions
  ios_device.py   Direct iPhone USB capture and touch events
  macos.py        iPhone Mirroring capture and mouse events
  vision.py       Local template, color, and layout recognition
  runtime.py      JSONL logs, screenshots, notifications, and sleep prevention
  assets/         Runtime recognition templates
tests/            Unit tests, flow tests, and redacted fixtures
tools/            Offline replay and asset-sanitization tools
```

## Known Limitations

- The detector targets the currently captured Chinese UI. Other languages and
  resolutions have not been validated.
- Game updates, event reskins, window aspect-ratio changes, or system updates
  may reduce recognition accuracy.
- Dedicated samples are not yet available for every network error,
  insufficient-energy, inventory-limit, maintenance, and event-ended screen.
  The default behavior is to wait for manual intervention.
- A click is canceled if the iPhone Mirroring window disappears, is minimized,
  produces a black frame, or moves after recognition.
- The Windows USB backend has not completed a real Windows+iPhone acceptance
  test. CI covers installation, imports, and simulated device flow only.
- The USB backend requires iOS Developer Mode and a mounted Developer Disk
  Image. A reboot or iOS update may require mounting it again.
- The tool does not navigate from the NBA 2K main menu back into the event.

## Disclaimer

This project is not affiliated with NBA, 2K Games, Visual Concepts, or Apple.
All trademarks and interface screenshots in this repository belong to their
respective owners and are included only for local interoperability, state
recognition, and regression testing.
