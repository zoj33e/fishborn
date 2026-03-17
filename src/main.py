import pydirectinput
import json
import os
import tkinter as tk
from tkinter import messagebox
import cv2
import numpy as np
import time
import pyautogui
import keyboard
import mss
import threading
import sys

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temporary folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # In development, use the project root directory
        # Assuming the script is run from the root or src/ directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if os.path.basename(current_dir) == "src":
            base_path = os.path.dirname(current_dir)
        else:
            base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)

# Configuration and Asset Paths
CONFIG_FILE = os.path.join("config", "config.json")
FISH_TEMPLATE = resource_path(os.path.join("essentials", "fish.png"))
BAR_RED_TEMPLATE = resource_path(os.path.join("essentials", "bar_red.png"))
BAR_GREEN_TEMPLATE = resource_path(os.path.join("essentials", "bar_green.png"))

# Constants
BAR_HEIGHT = 86
BAR_CENTER_OFFSET = 43
FISH_HEIGHT = 30
FISH_CENTER_OFFSET = 15
TARGET_FPS = 60
FRAME_TIME = 1.0 / TARGET_FPS

# Control System Parameters
DEADZONE = 12

class RegionSelector:
    """Utility class to allow user to select a screen region via a transparent overlay."""
    def __init__(self):
        self.root = tk.Tk()
        self.root.attributes('-alpha', 0.2)
        self.root.attributes('-fullscreen', True)
        self.root.attributes("-topmost", True)
        self.root.config(cursor="cross")
        
        self.canvas = tk.Canvas(self.root, cursor="cross", bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        self.start_x = None
        self.start_y = None
        self.rect = None
        self.selection = None
        
        self.label = tk.Label(self.root, text="DRAG A BOX OVER THE FISHING BAR AREA | ESC TO CANCEL", 
                             fg="white", bg="black", font=("Arial", 20, "bold"))
        self.label.place(relx=0.5, rely=0.1, anchor="center")
        
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_move_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.root.bind("<Escape>", lambda e: self.root.destroy())

    def on_button_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, 1, 1, outline='red', width=3)

    def on_move_press(self, event):
        cur_x, cur_y = (event.x, event.y)
        self.canvas.coords(self.rect, self.start_x, self.start_y, cur_x, cur_y)

    def on_button_release(self, event):
        end_x, end_y = (event.x, event.y)
        self.selection = {
            "top": min(self.start_y, end_y),
            "left": min(self.start_x, end_x),
            "width": max(10, abs(self.start_x - end_x)),
            "height": max(10, abs(self.start_y - end_y))
        }
        self.root.destroy()

    def get_selection(self):
        self.root.mainloop()
        return self.selection

class FishingBot:
    """Core logic for the automated fishing assistant."""
    def __init__(self):
        self.running = False
        self.mouse_pressed = False
        self.previous_fish_center = None
        self.debug_info = {}
        self.catching_active = False
        self.sct = None
        
        # Load configuration or initiate calibration
        self.monitor = self.load_config()
        if not self.monitor:
            print("[INFO] No configuration found. Starting calibration...")
            self.calibrate()
            if not self.monitor:
                print("[WARNING] Calibration skipped. Using default region.")
                self.monitor = {"top": 330, "left": 1850, "width": 70, "height": 410}
        
        # Load image templates for computer vision detection
        self.fish_template = cv2.imread(FISH_TEMPLATE, cv2.IMREAD_GRAYSCALE)
        self.bar_red_template = cv2.imread(BAR_RED_TEMPLATE, cv2.IMREAD_GRAYSCALE)
        self.bar_green_template = cv2.imread(BAR_GREEN_TEMPLATE, cv2.IMREAD_GRAYSCALE)
        
        if self.fish_template is None or self.bar_red_template is None or self.bar_green_template is None:
            raise FileNotFoundError(f"Critical asset files not found. Checked: {FISH_TEMPLATE}, {BAR_RED_TEMPLATE}, {BAR_GREEN_TEMPLATE}")
        
        # Register global hotkeys
        keyboard.on_press_key("F1", lambda _: self.start_bot())
        keyboard.on_press_key("F2", lambda _: self.stop_bot())
        keyboard.on_press_key("F3", lambda _: self.exit_bot())
        keyboard.on_press_key("F4", lambda _: self.calibrate())
    
    def load_config(self):
        """Loads calibration data from the config file."""
        config_path = resource_path(CONFIG_FILE)
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[ERROR] Failed to load config: {e}")
        return None

    def save_config(self):
        """Saves current calibration data to the config file."""
        try:
            config_path = resource_path(CONFIG_FILE)
            # Ensure config directory exists
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, 'w') as f:
                json.dump(self.monitor, f)
            print(f"[INFO] Configuration saved to {config_path}")
        except Exception as e:
            print(f"[ERROR] Failed to save config: {e}")

    def calibrate(self):
        """Opens the region selector for user-defined monitoring area."""
        print("[INFO] Please drag a box over your fishing bar area...")
        selector = RegionSelector()
        new_region = selector.get_selection()
        if new_region:
            self.monitor = new_region
            self.save_config()
            print(f"[INFO] Calibration successful: {self.monitor}")
        else:
            print("[INFO] Calibration cancelled.")
    
    def simulate_interaction(self, key='e'):
        """Helper to simulate a mouse click followed by a key press."""
        pyautogui.click()
        time.sleep(0.1)
        try:
            pydirectinput.press(key)
        except Exception:
            try:
                pyautogui.press(key)
            except Exception:
                keyboard.press(key)
                time.sleep(0.05)
                keyboard.release(key)
    
    def release_bait(self):
        """Initial bait release sequence."""
        print("[INFO] Releasing bait...")
        self.simulate_interaction('e')
        time.sleep(0.5)
    
    def recast_line(self):
        """Recast sequence after a catch or failure."""
        print("[INFO] Recasting line...")
        self.simulate_interaction('e')
        time.sleep(1.0)
    
    def capture_screen(self):
        """Grabs the defined screen region and converts to grayscale."""
        if self.sct is None:
            return np.zeros((410, 70), dtype=np.uint8)
        screenshot = self.sct.grab(self.monitor)
        img = np.array(screenshot)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    
    def find_template(self, frame, template, threshold=0.8):
        """Performs template matching to find objects in the frame."""
        if template is None:
            return None, None
        
        result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        
        if max_val >= threshold:
            return max_loc, max_val
        return None, None
    
    def detect_objects(self, frame):
        """Detects the fish and the bar color in the current frame."""
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
    
    def compute_control(self, fish_pos, bar_pos):
        """Calculates the necessary mouse actions based on positional error and velocity."""
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
        
        # Proportional-Derivative (PD) Control logic
        Kp = 0.85
        Kd = 12.0
        
        control_signal = (Kp * error) + (Kd * self.smoothed_error_vel)
        
        # Deadzone handling to minimize jitter
        if abs(error) < DEADZONE:
            if abs(self.smoothed_error_vel) < 1.0:
                control_signal = -2
            else:
                control_signal *= 0.5
        
        # Hysteresis thresholding
        threshold = -8 if self.mouse_pressed else 1
            
        if control_signal > threshold:
            return "hold_continuous", 0, control_signal, fish_center
        else:
            return "release", 0, control_signal, fish_center
    
    def execute_control(self, action):
        """Translates high-level actions into OS-level mouse events."""
        if action == "hold_continuous":
            if not self.mouse_pressed:
                pyautogui.mouseDown()
                self.mouse_pressed = True
        elif action == "release":
            if self.mouse_pressed:
                pyautogui.mouseUp()
                self.mouse_pressed = False
    
    def print_debug_info(self):
        """Prints live status of the bot to the console."""
        if self.debug_info:
            status = "Catching" if self.catching_active else "Waiting"
            print(f"\r{status} | Fish: {'Found' if self.debug_info.get('fish_pos') else 'Not Found'} | "
                  f"Bar: {'Found' if self.debug_info.get('bar_pos') else 'Not Found'} | "
                  f"Action: {self.debug_info.get('action', 'Unknown')} | "
                  f"Diff: {self.debug_info.get('difference', 0):.1f} | "
                  f"Mouse: {'DOWN' if self.mouse_pressed else 'UP'}", end="", flush=True)
    
    def run_bot(self):
        """Primary loop for screen monitoring and control execution."""
        print("[INFO] Fishing bot initialized. Monitoring starting...")
        self.sct = mss.mss()
        self.release_bait()
        
        no_detection_count = 0
        max_no_detection = 60
        
        while self.running:
            start_time = time.time()
            frame = self.capture_screen()
            fish_pos, bar_pos, _, _ = self.detect_objects(frame)
            
            if fish_pos is not None and bar_pos is not None:
                no_detection_count = 0
                self.catching_active = True
                
                # Failsafe: Check if bar has stagnated
                current_time = time.time()
                if not hasattr(self, 'last_bar_y') or self.last_bar_y != bar_pos[1]:
                    self.last_bar_y = bar_pos[1]
                    self.bar_stagnant_since = current_time
                elif current_time - self.bar_stagnant_since > 5.0:
                    print("\n[FAILSAFE] Bar seems stuck! Forcing interaction...")
                    pyautogui.click()
                    self.bar_stagnant_since = current_time
                
                action, _, difference, target = self.compute_control(fish_pos, bar_pos)
                self.execute_control(action)
                
                self.debug_info = {
                    "fish_pos": fish_pos,
                    "bar_pos": bar_pos,
                    "action": action,
                    "difference": difference,
                    "target": target
                }
            else:
                no_detection_count += 1
                if self.catching_active and no_detection_count >= max_no_detection:
                    print("\n[INFO] Detection lost. Assuming catch complete. Recasting...")
                    self.catching_active = False
                    if self.mouse_pressed:
                        pyautogui.mouseUp()
                        self.mouse_pressed = False
                    self.recast_line()
                    no_detection_count = 0
                
                if self.mouse_pressed:
                    pyautogui.mouseUp()
                    self.mouse_pressed = False
                
                self.debug_info = {
                    "fish_pos": fish_pos,
                    "bar_pos": bar_pos,
                    "action": "no_detection"
                }
            
            self.print_debug_info()
            
            elapsed = time.time() - start_time
            if elapsed < FRAME_TIME:
                time.sleep(FRAME_TIME - elapsed)
    
    def start_bot(self):
        """Starts the bot execution thread."""
        if not self.running:
            self.running = True
            self.bot_thread = threading.Thread(target=self.run_bot, daemon=True)
            self.bot_thread.start()
            print("[INFO] Bot thread started.")
    
    def stop_bot(self):
        """Stops the bot and releases any held controls."""
        self.running = False
        if self.mouse_pressed:
            pyautogui.mouseUp()
            self.mouse_pressed = False
        self.sct = None
        print("\n[INFO] Bot stopped.")
    
    def exit_bot(self):
        """Cleans up and exits the application."""
        self.stop_bot()
        print("[INFO] Exiting application.")
        sys.exit()
    
    def run(self):
        """Main execution block with hotkey information."""
        print("="*30)
        print("  FISHBORN: AUTOMATED FISHING")
        print("="*30)
        print("Hotkeys:")
        print("F1 - Start Bot")
        print("F2 - Stop Bot") 
        print("F3 - Exit Program")
        print("F4 - Re-calibrate Detection Region")
        print(f"Current Region: {self.monitor}")
        print("Waiting for hotkey input...")
        
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.exit_bot()

if __name__ == "__main__":
    bot = FishingBot()
    bot.run()
