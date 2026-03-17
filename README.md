# Fishborn

Fishborn is an automated fishing assistant that leverages computer vision to simplify fishing mechanics in Fistborn. By tracking on-screen elements in real-time, it provides precise, autonomous control over the fishing process.

## Features

- **Dynamic Region Monitoring**: Easily calibrate the bot to focus on any area of your screen with a simple drag-and-drop selector.
- **Advanced Computer Vision**: Utilizes OpenCV template matching to identify fish and status bars with high accuracy.
- **PD Control Algorithm**: Employs a Proportional-Derivative feedback loop for smooth, human-like mouse simulation, minimizing overshooting.
- **Intelligent Failsafes**: Detects stagnant UI states and automatically handles line recasting upon catch completion.
- **Global Hotkey Control**: Manage all bot functions instantly using dedicated system-wide hotkeys.

## Usage

1. Open your game and position your character in a fishing spot.
2. Run the assistant from the project root:
   ```bash
   python src/main.py
   ```
3. **Calibrate**: Press `F4` and drag a rectangle over the fishing UI area.
4. **Start**: Press `F1` to begin the automated fishing sequence.
5. **Stop**: Press `F2` to halt the bot at any time.

## Controls / Hotkeys

| Key    | Action                     |
| ------ | -------------------------- |
| **F1** | Start / Resume Fishing Bot |
| **F2** | Stop / Pause Fishing Bot   |
| **F4** | Calibrate Detection Region |
| **F3** | Exit Application           |

## Demo

When active, Fishborn monitors the calibrated screen region at 60 FPS. It calculates the delta between the fish and the capture bar, applying pulsed mouse inputs to maintain perfect alignment. Once the detection UI disappears, the bot automatically recasts the line, enabling fully hands-free fishing.

## Requirements

- **Operating System**: Windows (Required for `pydirectinput` and `keyboard` hooks)
- **Python Version**: 3.7 or higher
- **Hardware**: Any modern CPU capable of running OpenCV at 60 FPS

## Community

Join our Discord server to get help, report bugs, or suggest new features:

**Discord**: [https://discord.gg/DgwQ4Hr9Qm](https://discord.gg/DgwQ4Hr9Qm)

---

_Disclaimer: Use this software responsibly. Always respect the Terms of Service of the games you play._
