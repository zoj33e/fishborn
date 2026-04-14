"""
FishbornV2 — Fishing Bot
Auto-fishing thing for Roblox with template matching magic
"""

import sys
import os
import ctypes
import json
import time
import threading
import queue
import atexit
import traceback

import tkinter as tk
from tkinter import messagebox

import pydirectinput
import cv2
import numpy as np
import pyautogui
import keyboard
import mss
import ahk

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

VERSION = "2.0.0"
DEV_MODE = False  # flip this when building exe

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and PyInstaller"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        # in dev mode, go up from src/ to where essentials folder is
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

def get_config_path():
    """Get config file path next to the exe (not CWD)"""
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), "config.json")
    else:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def is_admin():
    """Check if we're admin or not"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def cleanup():
    """Emergency cleanup — let go of mouse when we crash"""
    try:
        pyautogui.mouseUp()
    except Exception:
        pass

# file paths and stuff
CONFIG_FILE = get_config_path()
FISH_TEMPLATE = resource_path("essentials/fish.png")
BAR_RED_TEMPLATE = resource_path("essentials/bar_red.png")
BAR_GREEN_TEMPLATE = resource_path("essentials/bar_green.png")

# magic numbers that make the bot work somehow
BAR_HEIGHT = 86
BAR_CENTER_OFFSET = 43
FISH_HEIGHT = 30
FISH_CENTER_OFFSET = 15
TARGET_FPS = 60
FRAME_TIME = 1.0 / TARGET_FPS

VELOCITY_FACTOR = 0.5
GRAVITY_COMPENSATION = 5
DEADZONE = 12
HOLD_THRESHOLD_LOW = -20
HOLD_THRESHOLD_HIGH = -8
MIN_HOLD_DURATION = 0.015
MAX_HOLD_DURATION = 0.050

# ─────────────────────────────────────────────
# colors and theme stuff
# ─────────────────────────────────────────────

COLORS = {
    "bg":           "#121212",   # Dark background
    "bg_card":      "#1e1e1e",   # Dark card surface
    "bg_inset":     "#181818",   # Pressed-in / inset surface
    "shadow_dark":  "#0a0a0a",   # Bottom-right shadow
    "shadow_light": "#2a2a2a",   # Top-left highlight
    "border":       "#2a2a2a",   # Subtle border
    "text":         "#e0e0e0",   # Light text
    "text_dim":     "#888888",   # Muted text
    "accent":       "#e06c8c",   # Rose color
    "accent_soft":  "#3d2a35",   # Dark rose
    "accent_dark":  "#c05070",   # Deep rose
    "green":        "#5cb87a",   # Green
    "yellow":       "#cda044",   # Yellow
    "red":          "#e06c6c",   # Red
    "badge_bg":     "#3d2a35",   # Badge bg
    "titlebar":     "#1a1a1a",   # Title bar
}
FONT = "Bahnschrift"

# ─────────────────────────────────────────────
# Region selector thing (for calibration)
# ─────────────────────────────────────────────

class RegionSelector:
    def __init__(self, parent=None, instruction="DRAG A BOX OVER THE TARGET AREA  |  ESC TO CANCEL"):
        self.is_toplevel = parent is not None
        if self.is_toplevel:
            self.root = tk.Toplevel(parent)
        else:
            self.root = tk.Tk()

        self.root.attributes('-alpha', 0.35)
        self.root.attributes('-fullscreen', True)
        self.root.attributes("-topmost", True)
        self.root.config(cursor="cross")

        self.canvas = tk.Canvas(self.root, cursor="cross", bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.start_x = None
        self.start_y = None
        self.rect = None
        self.selection = None

        self.label = tk.Label(
            self.root, text=instruction,
            fg="white", bg="black", font=("Arial", 20, "bold")
        )
        self.label.place(relx=0.5, rely=0.1, anchor="center")

        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_move_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.root.bind("<Escape>", lambda e: self.root.destroy())

    def on_button_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, 1, 1, outline='red', width=3
        )

    def on_move_press(self, event):
        cur_x, cur_y = event.x, event.y
        self.canvas.coords(self.rect, self.start_x, self.start_y, cur_x, cur_y)

    def on_button_release(self, event):
        end_x, end_y = event.x, event.y
        self.selection = {
            "top":    min(self.start_y, end_y),
            "left":   min(self.start_x, end_x),
            "width":  max(10, abs(self.start_x - end_x)),
            "height": max(10, abs(self.start_y - end_y)),
        }
        self.root.destroy()

    def get_selection(self):
        if self.is_toplevel:
            self.root.wait_window()
        else:
            self.root.mainloop()
        return self.selection

# ─────────────────────────────────────────────
# The actual bot logic
# ─────────────────────────────────────────────

class FishingBot:
    def __init__(self):
        self.running = False
        self.mouse_pressed = False
        self.previous_fish_center = None
        self.debug_info = {}
        self.catching_active = False

        self.sct = None

        # fish hunting flags
        self.shark_clicked = False
        self.swordfish_clicked = False
        self.last_fish_click_time = 0
        self.need_recast = False

        # load the template images
        shark_path = resource_path("essentials/shark.png")
        swordfish_path = resource_path("essentials/swordfish.png")

        self.shark_template = cv2.imread(shark_path, cv2.IMREAD_COLOR)
        self.swordfish_template = cv2.imread(swordfish_path, cv2.IMREAD_COLOR)
        self.fish_template = cv2.imread(FISH_TEMPLATE, cv2.IMREAD_GRAYSCALE)
        self.bar_red_template = cv2.imread(BAR_RED_TEMPLATE, cv2.IMREAD_GRAYSCALE)
        self.bar_green_template = cv2.imread(BAR_GREEN_TEMPLATE, cv2.IMREAD_GRAYSCALE)

        # check if templates loaded properly
        templates = {
            "fish.png":      self.fish_template,
            "bar_red.png":   self.bar_red_template,
            "bar_green.png": self.bar_green_template,
            "shark.png":     self.shark_template,
            "swordfish.png": self.swordfish_template,
        }
        missing = [name for name, tmpl in templates.items() if tmpl is None]
        if missing:
            paths = "\n".join(resource_path(f"essentials/{n}") for n in missing)
            raise FileNotFoundError(
                f"Could not load template files: {', '.join(missing)}\n"
                f"Expected at:\n{paths}"
            )

        print(f"Shark template loaded: {self.shark_template.shape}")
        print(f"Swordfish template loaded: {self.swordfish_template.shape}")

        # load config if it exists
        config = self.load_config()
        if config and "bar_region" in config and "fish_region" in config:
            self.monitor = config["bar_region"]
            self.fish_search_region = config["fish_region"]
            self.calibrated = True
        else:
            self.monitor = None
            self.fish_search_region = None
            self.calibrated = False

    # config saving/loading stuff

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                if "bar_region" in data and "fish_region" in data:
                    return data
                # Old format — treat as no config
                print("Old config format detected, re-calibration required.")
            except Exception as e:
                print(f"Error loading config: {e}")
        return None

    def save_config(self):
        try:
            data = {
                "bar_region": self.monitor,
                "fish_region": self.fish_search_region,
            }
            with open(CONFIG_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"Configuration saved to {CONFIG_FILE}")
        except Exception as e:
            print(f"Error saving config: {e}")

    # input helpers

    def release_bait(self):
        """Click and press E to throw the bait"""
        print("Releasing bait...")
        pyautogui.click()
        time.sleep(0.1)
        try:
            pydirectinput.press('e')
        except Exception:
            try:
                pyautogui.press('e')
            except Exception:
                keyboard.press('e')
                time.sleep(0.05)
                keyboard.release('e')
        time.sleep(0.5)

    def recast_line(self):
        """Click and press E to recast"""
        print("Recasting line...")
        pyautogui.click()
        time.sleep(0.1)
        try:
            pydirectinput.press('e')
        except Exception:
            try:
                pyautogui.press('e')
            except Exception:
                keyboard.press('e')
                time.sleep(0.05)
                keyboard.release('e')
        time.sleep(1.0)

    # screen capture stuff

    def capture_fish_region(self):
        """Grab the fish search area from screen"""
        if self.sct is None or self.fish_search_region is None:
            return None
        screenshot = self.sct.grab(self.fish_search_region)
        img = np.array(screenshot)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    def capture_screen(self):
        if self.sct is None:
            return np.zeros((410, 70), dtype=np.uint8)
        screenshot = self.sct.grab(self.monitor)
        img = np.array(screenshot)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)

    # template matching magic

    def find_fish_template(self, frame, template, threshold=0.8):
        """Find fish using template matching with multiple methods"""
        if template is None or frame is None:
            return None, None

        methods = [cv2.TM_CCOEFF_NORMED, cv2.TM_CCORR_NORMED]

        best_match = None
        best_val = 0

        for method in methods:
            result = cv2.matchTemplate(frame, template, method)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

            if method in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED):
                match_val = 1 - min_val
                match_loc = min_loc
            else:
                match_val = max_val
                match_loc = max_loc

            if match_val > best_val:
                best_val = match_val
                best_match = match_loc

        if best_val >= threshold:
            return best_match, best_val
        return None, None

    def find_template(self, frame, template, threshold=0.8):
        if template is None:
            return None, None
        result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        if max_val >= threshold:
            return max_loc, max_val
        return None, None

    def detect_objects(self, frame):
        fish_pos, fish_conf = self.find_template(frame, self.fish_template, 0.7)
        bar_red_pos, bar_red_conf = self.find_template(frame, self.bar_red_template, 0.8)

        bar_pos = bar_red_pos
        bar_conf = bar_red_conf

        if bar_pos is None:
            bar_green_pos, bar_green_conf = self.find_template(frame, self.bar_green_template, 0.8)
            if bar_green_pos is not None:
                bar_pos = bar_green_pos
                bar_conf = bar_green_conf

        return fish_pos, bar_pos, fish_conf, bar_conf

    # fish clicking (shark/swordfish)

    def click_fish(self, x, y):
        """Click at specific position using AHK"""
        ahk_instance = ahk.AHK()
        ahk_instance.click(x, y)
        time.sleep(0.02)
        ahk_instance.mouse_move(x, y - 80)
        # click 10 times to make sure it actually eats
        for _ in range(10):
            ahk_instance.click()
            time.sleep(0.01)

    def check_and_click_fish(self):
        """Check for shark/swordfish and click if found"""
        frame = self.capture_fish_region()
        if frame is None:
            return False

        shark_pos, shark_conf = self.find_fish_template(frame, self.shark_template, threshold=0.85)
        swordfish_pos, swordfish_conf = self.find_fish_template(frame, self.swordfish_template, threshold=0.85)

        if shark_pos is not None and not self.shark_clicked:
            abs_x = self.fish_search_region["left"] + shark_pos[0]
            abs_y = self.fish_search_region["top"] + shark_pos[1]
            h, w = self.shark_template.shape[:2]
            center_x = abs_x + w // 2
            center_y = abs_y + h // 2
            print(f"[PRE-CHECK] SHARK FOUND at ({center_x}, {center_y}) | CLICKING!")
            self.click_fish(center_x, center_y)
            self.shark_clicked = True
            self.swordfish_clicked = False
            return True

        elif swordfish_pos is not None and not self.swordfish_clicked:
            abs_x = self.fish_search_region["left"] + swordfish_pos[0]
            abs_y = self.fish_search_region["top"] + swordfish_pos[1]
            h, w = self.swordfish_template.shape[:2]
            center_x = abs_x + w // 2
            center_y = abs_y + h // 2
            print(f"[PRE-CHECK] SWORDFISH FOUND at ({center_x}, {center_y}) | CLICKING!")
            self.click_fish(center_x, center_y)
            self.swordfish_clicked = True
            self.shark_clicked = False
            return True

        else:
            self.shark_clicked = False
            self.swordfish_clicked = False
            return False

    # control logic

    def compute_control(self, fish_pos, bar_pos):
        if fish_pos is None or bar_pos is None:
            return "none", 0, 0, 0

        fish_center = fish_pos[1] + FISH_CENTER_OFFSET
        bar_center = bar_pos[1] + BAR_CENTER_OFFSET

        error = bar_center - fish_center

        if not hasattr(self, 'prev_bar_center'):
            self.prev_bar_center = bar_center
            self.prev_fish_center = fish_center

        bar_vel = bar_center - self.prev_bar_center
        fish_vel = fish_center - self.prev_fish_center

        self.prev_bar_center = bar_center
        self.prev_fish_center = fish_center

        error_vel = bar_vel - fish_vel

        if not hasattr(self, 'smoothed_error_vel'):
            self.smoothed_error_vel = error_vel
        self.smoothed_error_vel = self.smoothed_error_vel * 0.6 + error_vel * 0.4

        Kp = 0.85
        Kd = 12.0
        control_signal = (Kp * error) + (Kd * self.smoothed_error_vel)

        if abs(error) < DEADZONE:
            if abs(self.smoothed_error_vel) < 1.0:
                control_signal = -2
            else:
                control_signal *= 0.5

        if self.mouse_pressed:
            threshold = -8
        else:
            threshold = 1

        if control_signal > threshold:
            return "hold_continuous", 0, control_signal, fish_center
        else:
            return "release", 0, control_signal, fish_center

    def execute_control(self, action, duration):
        if action == "hold_continuous":
            if not self.mouse_pressed:
                pyautogui.mouseDown()
                self.mouse_pressed = True
        elif action == "release":
            if self.mouse_pressed:
                pyautogui.mouseUp()
                self.mouse_pressed = False

    # debug stuff

    def print_debug_info(self):
        if self.debug_info:
            status = "Catching" if self.catching_active else "Waiting"
            print(
                f"\r{status} | "
                f"Fish: {'Found' if self.debug_info.get('fish_pos') else 'Not Found'} | "
                f"Bar: {'Found' if self.debug_info.get('bar_pos') else 'Not Found'} | "
                f"Action: {self.debug_info.get('action', 'unknown')} | "
                f"Difference: {self.debug_info.get('difference', 0):.1f} | "
                f"Mouse: {'Pressed' if self.mouse_pressed else 'Released'}",
                end="", flush=True
            )

    # main bot loop

    def run_bot(self):
        print("Fishing bot started. Press F2 to stop, F3 to exit.")

        self.sct = mss.mss()

        no_detection_count = 0
        max_no_detection = 60
        self.need_recast = True  # Start with need to cast

        while self.running:
            start_time = time.time()

            # Step 1: Check for shark/swordfish (2 sec cooldown)
            if time.time() - self.last_fish_click_time > 2.0:
                if self.check_and_click_fish():
                    if self.mouse_pressed:
                        pyautogui.mouseUp()
                        self.mouse_pressed = False
                    self.catching_active = False
                    self.need_recast = True
                    no_detection_count = 0
                    self.last_fish_click_time = time.time()
                    # wait for all clicks to finish
                    time.sleep(0.5)
                    print("Fish clicked! Pressing '1'...")
                    try:
                        pydirectinput.press('1')
                    except Exception:
                        try:
                            pyautogui.press('1')
                        except Exception:
                            keyboard.press('1')
                            time.sleep(0.05)
                            keyboard.release('1')
                    time.sleep(0.5)
                    continue

            # Step 2: Recast if needed (after fish check)
            if self.need_recast:
                print("Releasing bait...")
                self.release_bait()
                self.need_recast = False

            # Step 3: Do the actual fishing
            frame = self.capture_screen()
            fish_pos, bar_pos, fish_conf, bar_conf = self.detect_objects(frame)

            if fish_pos is not None and bar_pos is not None:
                no_detection_count = 0
                self.catching_active = True

                current_time = time.time()
                if not hasattr(self, 'last_bar_y') or self.last_bar_y != bar_pos[1]:
                    self.last_bar_y = bar_pos[1]
                    self.bar_stagnant_since = current_time
                elif current_time - self.bar_stagnant_since > 5.0:
                    print("\n[Failsafe] Bar seems stuck! Clicking to un-stuck...")
                    pyautogui.click()
                    self.bar_stagnant_since = current_time

                action, duration, difference, target = self.compute_control(fish_pos, bar_pos)
                self.execute_control(action, duration)

                self.debug_info = {
                    "fish_pos": fish_pos,
                    "bar_pos": bar_pos,
                    "action": action,
                    "difference": difference,
                    "target": target,
                    "mouse_pressed": self.mouse_pressed,
                }
            else:
                no_detection_count += 1

                if self.catching_active and no_detection_count >= max_no_detection:
                    print("\nCatching complete! Will recast after fish check...")
                    self.catching_active = False

                    if self.mouse_pressed:
                        pyautogui.mouseUp()
                        self.mouse_pressed = False

                    self.need_recast = True
                    no_detection_count = 0

                if self.mouse_pressed:
                    pyautogui.mouseUp()
                    self.mouse_pressed = False

                self.debug_info = {
                    "fish_pos": fish_pos,
                    "bar_pos": bar_pos,
                    "action": "no_detection",
                    "mouse_pressed": self.mouse_pressed,
                }

            self.print_debug_info()

            elapsed = time.time() - start_time
            if elapsed < FRAME_TIME:
                time.sleep(FRAME_TIME - elapsed)

    def start_bot(self):
        if not self.running and self.calibrated:
            self.running = True
            self.bot_thread = threading.Thread(target=self.run_bot, daemon=True)
            self.bot_thread.start()
            print("Bot started!")

    def stop_bot(self):
        self.running = False
        if self.mouse_pressed:
            pyautogui.mouseUp()
            self.mouse_pressed = False
        if self.sct:
            self.sct = None
        print("Bot stopped!")

    def exit_bot(self):
        self.stop_bot()
        print("\nExiting...")

# ─────────────────────────────────────────────
# GUI stuff
# ─────────────────────────────────────────────

class BotGUI:
    def __init__(self, bot):
        self.bot = bot
        self.action_queue = queue.Queue()

        # drag state
        self._drag_x = 0
        self._drag_y = 0

        # frameless window
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.configure(bg=COLORS["bg"])
        self.root.attributes("-topmost", True)

        # position on left side of screen
        win_w, win_h = 340, 530
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = 40
        y = (screen_h - win_h) // 2
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")

        self._build_ui()
        self._register_hotkeys()
        self._start_loops()

    # drag logic

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag(self, event):
        new_x = self.root.winfo_x() + event.x - self._drag_x
        new_y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{new_x}+{new_y}")

    # build the UI

    def _clay_card(self, parent, **kwargs):
        """Create a simple card frame"""
        # simple card with border
        card = tk.Frame(parent, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1)
        return card, card

    def _build_ui(self):
        # main body
        body = tk.Frame(self.root, bg=COLORS["bg"], highlightbackground=COLORS["border"], highlightthickness=1)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        # rose stripe at top
        tk.Frame(body, bg=COLORS["accent"], height=4).pack(fill="x")

        # title bar (draggable)
        titlebar = tk.Frame(body, bg=COLORS["titlebar"])
        titlebar.pack(fill="x")

        titlebar.bind("<ButtonPress-1>", self._start_drag)
        titlebar.bind("<B1-Motion>", self._on_drag)

        title_lbl = tk.Label(
            titlebar, text="  Fishing Bot",
            font=(FONT, 10, "bold"), fg=COLORS["text"], bg=COLORS["titlebar"]
        )
        title_lbl.pack(side="left", padx=(6, 0), pady=7)
        title_lbl.bind("<ButtonPress-1>", self._start_drag)
        title_lbl.bind("<B1-Motion>", self._on_drag)

        ver_lbl = tk.Label(
            titlebar, text=f"v{VERSION}",
            font=(FONT, 8), fg=COLORS["text_dim"], bg=COLORS["titlebar"]
        )
        ver_lbl.pack(side="left", padx=(5, 0), pady=7)
        ver_lbl.bind("<ButtonPress-1>", self._start_drag)
        ver_lbl.bind("<B1-Motion>", self._on_drag)

        close_btn = tk.Label(
            titlebar, text="  ✕  ",
            font=(FONT, 10, "bold"), fg=COLORS["text_dim"], bg=COLORS["titlebar"],
            cursor="hand2"
        )
        close_btn.pack(side="right", pady=5, padx=(0, 6))
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg=COLORS["red"]))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg=COLORS["text_dim"]))
        close_btn.bind("<ButtonRelease-1>", lambda e: self._on_exit())

        # separator line
        tk.Frame(body, bg=COLORS["border"], height=1).pack(fill="x")

        # content area
        content = tk.Frame(body, bg=COLORS["bg"])
        content.pack(fill="both", expand=True, padx=14, pady=10)

        # status card
        status_card, _ = self._clay_card(content)
        status_card.pack(fill="x", pady=(0, 8))

        self.status_dot = tk.Label(
            status_card, text="●", font=(FONT, 20),
            fg=COLORS["yellow"], bg=COLORS["bg_card"]
        )
        self.status_dot.pack(pady=(10, 0))

        self.status_label = tk.Label(
            status_card, text="IDLE",
            font=(FONT, 13, "bold"), fg=COLORS["text"], bg=COLORS["bg_card"]
        )
        self.status_label.pack()

        self.status_sub = tk.Label(
            status_card, text="Press F1 to start fishing",
            font=(FONT, 8), fg=COLORS["text_dim"], bg=COLORS["bg_card"]
        )
        self.status_sub.pack(pady=(0, 10))

        # controls card
        ctrl_card, _ = self._clay_card(content)
        ctrl_card.pack(fill="x", pady=(0, 8))

        tk.Label(
            ctrl_card, text="CONTROLS",
            font=(FONT, 7, "bold"), fg=COLORS["text_dim"], bg=COLORS["bg_card"]
        ).pack(anchor="w", padx=12, pady=(10, 4))

        hotkeys = [
            ("F1", "Start Bot"),
            ("F2", "Stop Bot"),
            ("F3", "Exit"),
            ("F4", "Calibrate Fishing Bar"),
            ("F5", "Calibrate Fish Area"),
        ]

        for key, desc in hotkeys:
            row = tk.Frame(ctrl_card, bg=COLORS["bg_card"])
            row.pack(fill="x", padx=12, pady=1)

            tk.Label(
                row, text=f" {key} ",
                font=(FONT, 7, "bold"),
                fg=COLORS["accent_dark"], bg=COLORS["badge_bg"],
                padx=3
            ).pack(side="left")

            tk.Label(
                row, text=f"  {desc}",
                font=(FONT, 9), fg=COLORS["text"], bg=COLORS["bg_card"]
            ).pack(side="left")

        # padding
        tk.Frame(ctrl_card, bg=COLORS["bg_card"], height=8).pack()

        # info card
        info_card, _ = self._clay_card(content)
        info_card.pack(fill="x", pady=(0, 8))

        tk.Label(
            info_card, text="INFO",
            font=(FONT, 7, "bold"), fg=COLORS["text_dim"], bg=COLORS["bg_card"]
        ).pack(anchor="w", padx=12, pady=(10, 4))

        self.bar_status = tk.Label(
            info_card, text="Bar Region:  …",
            font=(FONT, 9), fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
        )
        self.bar_status.pack(fill="x", padx=12, pady=1)

        self.fish_status = tk.Label(
            info_card, text="Fish Region:  …",
            font=(FONT, 9), fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
        )
        self.fish_status.pack(fill="x", padx=12, pady=1)

        self.detection_label = tk.Label(
            info_card, text="Detection:  —",
            font=(FONT, 9), fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
        )
        self.detection_label.pack(fill="x", padx=12, pady=1)

        self.action_label = tk.Label(
            info_card, text="Action:  —",
            font=(FONT, 9), fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
        )
        self.action_label.pack(fill="x", padx=12, pady=(1, 10))

        # tip at bottom
        tk.Label(
            content,
            text="Open Roblox first, then press F1",
            font=(FONT, 8), fg=COLORS["text_dim"], bg=COLORS["bg"]
        ).pack(pady=(2, 0))

        # set initial status
        self._refresh_config_status()

    # config status

    def _refresh_config_status(self):
        if self.bot.monitor:
            self.bar_status.config(text="Bar Region:  Configured", fg=COLORS["green"])
        else:
            self.bar_status.config(text="Bar Region:  Not Set", fg=COLORS["red"])

        if self.bot.fish_search_region:
            self.fish_status.config(text="Fish Region:  Configured", fg=COLORS["green"])
        else:
            self.fish_status.config(text="Fish Region:  Not Set", fg=COLORS["red"])

    # hotkey stuff

    def _register_hotkeys(self):
        keyboard.on_press_key("F1", lambda _: self.action_queue.put("start"))
        keyboard.on_press_key("F2", lambda _: self.action_queue.put("stop"))
        keyboard.on_press_key("F3", lambda _: self.action_queue.put("exit"))
        keyboard.on_press_key("F4", lambda _: self.action_queue.put("calibrate_bar"))
        keyboard.on_press_key("F5", lambda _: self.action_queue.put("calibrate_fish"))

    # event loops

    def _start_loops(self):
        self._process_queue()
        self._update_display()

    def _process_queue(self):
        try:
            while True:
                action = self.action_queue.get_nowait()
                if action == "start":
                    self._on_start()
                elif action == "stop":
                    self._on_stop()
                elif action == "exit":
                    self._on_exit()
                elif action == "calibrate_bar":
                    self._on_calibrate_bar()
                elif action == "calibrate_fish":
                    self._on_calibrate_fish()
        except queue.Empty:
            pass
        self.root.after(50, self._process_queue)

    def _update_display(self):
        card_bg = COLORS["bg_card"]

        # status section
        if not self.bot.calibrated:
            self.status_dot.config(fg=COLORS["red"])
            self.status_label.config(text="NOT CALIBRATED")
            self.status_sub.config(text="Press F4 and F5 to set up regions")
        elif self.bot.running:
            if self.bot.catching_active:
                self.status_dot.config(fg=COLORS["green"])
                self.status_label.config(text="FISHING")
                self.status_sub.config(text="Actively catching fish...")
            else:
                self.status_dot.config(fg=COLORS["accent"])
                self.status_label.config(text="RUNNING")
                self.status_sub.config(text="Waiting for fish to bite...")
        else:
            self.status_dot.config(fg=COLORS["yellow"])
            self.status_label.config(text="IDLE")
            self.status_sub.config(text="Press F1 to start fishing")

        # detection info
        if self.bot.running and self.bot.debug_info:
            fish_ok = "✓" if self.bot.debug_info.get("fish_pos") else "✗"
            bar_ok = "✓" if self.bot.debug_info.get("bar_pos") else "✗"
            self.detection_label.config(
                text=f"Detection:  Fish {fish_ok}  |  Bar {bar_ok}",
                fg=COLORS["text"]
            )
            act = self.bot.debug_info.get("action", "—")
            mouse = "Pressed" if self.bot.mouse_pressed else "Released"
            self.action_label.config(
                text=f"Action:  {act}  |  Mouse: {mouse}",
                fg=COLORS["text"]
            )
        else:
            self.detection_label.config(text="Detection:  —", fg=COLORS["text_dim"])
            self.action_label.config(text="Action:  —", fg=COLORS["text_dim"])

        self.root.after(100, self._update_display)

    # actions

    def _on_start(self):
        if not self.bot.calibrated:
            messagebox.showwarning(
                "Not Calibrated",
                "Please calibrate both regions first!\n\n"
                "F4 — Calibrate Fishing Bar\n"
                "F5 — Calibrate Fish Search Area",
                parent=self.root
            )
            return
        if self.bot.running:
            return
        self.bot.start_bot()

    def _on_stop(self):
        self.bot.stop_bot()

    def _on_exit(self):
        self.bot.exit_bot()
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass
        sys.exit(0)

    def _on_calibrate_bar(self):
        if self.bot.running:
            self.bot.stop_bot()

        messagebox.showinfo(
            "Calibrate Fishing Bar",
            "A transparent overlay will appear.\n\n"
            "DRAG A BOX over the fishing bar in your game.\n"
            "Press ESC to cancel.",
            parent=self.root
        )

        self.root.withdraw()
        selector = RegionSelector(
            parent=self.root,
            instruction="DRAG A BOX OVER THE FISHING BAR  |  ESC TO CANCEL"
        )
        result = selector.get_selection()
        self.root.deiconify()

        if result:
            self.bot.monitor = result
            self.bot.calibrated = (
                self.bot.monitor is not None and self.bot.fish_search_region is not None
            )
            self.bot.save_config()
            self._refresh_config_status()
            messagebox.showinfo("Success", "Fishing bar region saved!", parent=self.root)
        else:
            messagebox.showwarning("Cancelled", "Calibration was cancelled.", parent=self.root)

    def _on_calibrate_fish(self):
        if self.bot.running:
            self.bot.stop_bot()

        messagebox.showinfo(
            "Calibrate Fish Area",
            "A transparent overlay will appear.\n\n"
            "DRAG A BOX over the area where fish\n"
            "(shark / swordfish) appear on screen.\n"
            "Press ESC to cancel.",
            parent=self.root
        )

        self.root.withdraw()
        selector = RegionSelector(
            parent=self.root,
            instruction="DRAG A BOX OVER THE FISH SELECTION AREA  |  ESC TO CANCEL"
        )
        result = selector.get_selection()
        self.root.deiconify()

        if result:
            self.bot.fish_search_region = result
            self.bot.calibrated = (
                self.bot.monitor is not None and self.bot.fish_search_region is not None
            )
            self.bot.save_config()
            self._refresh_config_status()
            messagebox.showinfo("Success", "Fish search region saved!", parent=self.root)
        else:
            messagebox.showwarning("Cancelled", "Calibration was cancelled.", parent=self.root)

    # first-run setup

    def _first_run_setup(self):
        """Force calibration on first run"""
        messagebox.showinfo(
            "Welcome to Fishing Bot",
            "Before we start, you need to set up two screen regions.\n\n"
            "  1.  First — select the FISHING BAR area\n"
            "  2.  Then — select the FISH SELECTION area\n\n"
            "Make sure Roblox is open and visible!",
            parent=self.root
        )

        # Step 1: Bar region
        messagebox.showinfo(
            "Step 1 of 2  —  Fishing Bar",
            "A transparent overlay will appear.\n\n"
            "DRAG A BOX over the FISHING BAR in your game.\n"
            "Press ESC to cancel (will exit the program).",
            parent=self.root
        )

        self.root.withdraw()
        selector = RegionSelector(
            parent=self.root,
            instruction="STEP 1 / 2  ·  DRAG A BOX OVER THE FISHING BAR  |  ESC TO CANCEL"
        )
        bar_result = selector.get_selection()
        self.root.deiconify()

        if not bar_result:
            messagebox.showerror(
                "Setup Cancelled",
                "Both regions must be configured to use the bot.\n"
                "The program will now exit.",
                parent=self.root
            )
            self.root.destroy()
            sys.exit(1)

        self.bot.monitor = bar_result

        messagebox.showinfo(
            "Step 1 Complete",
            "Fishing bar region saved!\n\n"
            "Now let's set up the fish selection area.",
            parent=self.root
        )

        # Step 2: Fish region
        messagebox.showinfo(
            "Step 2 of 2  —  Fish Selection Area",
            "A transparent overlay will appear.\n\n"
            "DRAG A BOX over the area where fish\n"
            "(shark / swordfish) appear on screen.\n"
            "Press ESC to cancel (will exit the program).",
            parent=self.root
        )

        self.root.withdraw()
        selector = RegionSelector(
            parent=self.root,
            instruction="STEP 2 / 2  ·  DRAG A BOX OVER THE FISH AREA  |  ESC TO CANCEL"
        )
        fish_result = selector.get_selection()
        self.root.deiconify()

        if not fish_result:
            messagebox.showerror(
                "Setup Cancelled",
                "Both regions must be configured to use the bot.\n"
                "The program will now exit.",
                parent=self.root
            )
            self.root.destroy()
            sys.exit(1)

        self.bot.fish_search_region = fish_result
        self.bot.calibrated = True
        self.bot.save_config()
        self._refresh_config_status()

        messagebox.showinfo(
            "Setup Complete!",
            "Both regions are configured!\n\n"
            "Press F1 to start fishing.\n"
            "You can recalibrate anytime with F4 and F5.",
            parent=self.root
        )

    # run

    def run(self):
        if not self.bot.calibrated:
            self.root.after(200, self._first_run_setup)
        self.root.mainloop()

# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # set console title
    try:
        ctypes.windll.kernel32.SetConsoleTitleW("Fishing Bot")
    except Exception:
        pass

    # admin check
    if not DEV_MODE and not is_admin():
        try:
            _root = tk.Tk()
            _root.withdraw()
            messagebox.showerror(
                "Administrator Required",
                "This program needs to run as Administrator\n"
                "to control your game.\n\n"
                "Right-click the .exe and select\n"
                "'Run as administrator'."
            )
            _root.destroy()
        except Exception:
            print("ERROR: This program must be run as Administrator.")
            print("Right-click the .exe → Run as administrator.")
            input("\nPress Enter to exit...")
        sys.exit(1)

    # cleanup on exit
    atexit.register(cleanup)

    # launch
    try:
        bot = FishingBot()
        gui = BotGUI(bot)

        print(f"=== FISHING BOT v{VERSION} ===")
        print("GUI is running. Use F1-F5 hotkeys or close the window to exit.")
        print(f"Config file: {CONFIG_FILE}")

        gui.run()

    except Exception as e:
        error_text = traceback.format_exc()

        # Write crash log next to the exe
        try:
            if getattr(sys, 'frozen', False):
                log_dir = os.path.dirname(sys.executable)
            else:
                log_dir = os.path.dirname(os.path.abspath(__file__))
            log_path = os.path.join(log_dir, "crash_log.txt")
            with open(log_path, "w") as f:
                f.write(f"Fishing Bot v{VERSION} — Crash Report\n")
                f.write(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"{'=' * 50}\n\n")
                f.write(error_text)
            log_msg = f"\n\nA crash log was saved to:\n{log_path}"
        except Exception:
            log_msg = ""

        # Show error dialog
        try:
            _root = tk.Tk()
            _root.withdraw()
            messagebox.showerror(
                "Fishing Bot — Error",
                f"Something went wrong:\n\n{e}{log_msg}"
            )
            _root.destroy()
        except Exception:
            print(f"\nFATAL ERROR: {e}")
            print(error_text)
            input("\nPress Enter to exit...")

        sys.exit(1)
