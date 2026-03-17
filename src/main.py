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
        # pyinstaller shoves stuff in a temp folder called _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)

# random thing we need
# where we keep our junk
CONFIG_FILE = "config.json"
FISH_TEMPLATE = resource_path("essentials/fish.png")
BAR_RED_TEMPLATE = resource_path("essentials/bar_red.png")
BAR_GREEN_TEMPLATE = resource_path("essentials/bar_green.png")

BAR_HEIGHT = 86
BAR_CENTER_OFFSET = 43
FISH_HEIGHT = 30
FISH_CENTER_OFFSET = 15
TARGET_FPS = 60
FRAME_TIME = 1.0 / TARGET_FPS

# magic numbers that make it work somehow
VELOCITY_FACTOR = 0.5
GRAVITY_COMPENSATION = 5
DEADZONE = 12
HOLD_THRESHOLD_LOW = -20
HOLD_THRESHOLD_HIGH = -8
MIN_HOLD_DURATION = 0.015
MAX_HOLD_DURATION = 0.050

class RegionSelector:
    def __init__(self):
        self.root = tk.Tk()
        self.root.attributes('-alpha', 0.2) # barely see this damn thing
        self.root.attributes('-fullscreen', True)
        self.root.attributes("-topmost", True)
        # screwed up transparentcolor, makes clicks go through on windows
        self.root.config(cursor="cross")
        
        # black background so the red thing stands out
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
    def __init__(self):
        self.running = False
        self.mouse_pressed = False
        self.previous_fish_center = None
        self.debug_info = {}
        self.catching_active = False
        
        # setup screen hijacking (starts in thread cuz reasons)
        self.sct = None
        
        # load or figure out where the hell to look
        self.monitor = self.load_config()
        if not self.monitor:
            print("No configuration found. Starting calibration...")
            self.calibrate()
            if not self.monitor:
                print("Calibration cancelled or failed. Using defaults.")
                self.monitor = {"top": 330, "left": 1850, "width": 70, "height": 410}
        
        # load the picture templates
        self.fish_template = cv2.imread(FISH_TEMPLATE, cv2.IMREAD_GRAYSCALE)
        self.bar_red_template = cv2.imread(BAR_RED_TEMPLATE, cv2.IMREAD_GRAYSCALE)
        self.bar_green_template = cv2.imread(BAR_GREEN_TEMPLATE, cv2.IMREAD_GRAYSCALE)
        
        if self.fish_template is None or self.bar_red_template is None or self.bar_green_template is None:
            raise FileNotFoundError("Template files not found in essentials/ directory")
        
        # keyboard shortcuts n stuff
        keyboard.on_press_key("F1", lambda _: self.start_bot())
        keyboard.on_press_key("F2", lambda _: self.stop_bot())
        keyboard.on_press_key("F3", lambda _: self.exit_bot())
        keyboard.on_press_key("F4", lambda _: self.calibrate()) # cuz you'll probably mess this up
    
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading config: {e}")
        return None

    def save_config(self):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.monitor, f)
            print(f"Configuration saved to {CONFIG_FILE}")
        except Exception as e:
            print(f"Error saving config: {e}")

    def calibrate(self):
        print("Please drag a box over your fishing bar area...")
        selector = RegionSelector()
        new_region = selector.get_selection()
        if new_region:
            self.monitor = new_region
            self.save_config()
            print(f"Calibration successful: {self.monitor}")
            # if bot's running, gotta restart the damn screen thing
            if self.sct:
                # mss doesn't give a shit, just uses the monitor dict
                pass 
        else:
            print("Calibration cancelled.")
    
    def release_bait(self):
        """Click and press E to release bait"""
        print("Releasing bait...")
        pyautogui.click()
        time.sleep(0.1)
        # try every damn way to press e
        try:
            pydirectinput.press('e')
        except:
            try:
                pyautogui.press('e')
            except:
                keyboard.press('e')
                time.sleep(0.05)
                keyboard.release('e')
        time.sleep(0.5)
    
    def recast_line(self):
        """Click and press E to recast fishing line"""
        print("Recasting line...")
        pyautogui.click()
        time.sleep(0.1)
        # try every damn way to press e
        try:
            pydirectinput.press('e')
        except:
            try:
                pyautogui.press('e')
            except:
                keyboard.press('e')
                time.sleep(0.05)
                keyboard.release('e')
        time.sleep(1.0)  # let the line chill for a sec
    
    def capture_screen(self):
        if self.sct is None:
            return np.zeros((410, 70), dtype=np.uint8)
        screenshot = self.sct.grab(self.monitor)
        img = np.array(screenshot)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    
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
    
    def compute_control(self, fish_pos, bar_pos):
        if fish_pos is None or bar_pos is None:
            return "none", 0, 0, 0
            
        fish_center = fish_pos[1] + FISH_CENTER_OFFSET
        bar_center = bar_pos[1] + BAR_CENTER_OFFSET
        
        # calculate how badly we're screwing up: > 0 means bar is below the fish
        error = bar_center - fish_center
        
        # set up previous thing
        if not hasattr(self, 'prev_bar_center'):
            self.prev_bar_center = bar_center
            self.prev_fish_center = fish_center
            
        bar_vel = bar_center - self.prev_bar_center
        fish_vel = fish_center - self.prev_fish_center
        
        self.prev_bar_center = bar_center
        self.prev_fish_center = fish_center
        
        # how fast we're screwing up
        error_vel = bar_vel - fish_vel
        
        # smooth out the jittery mess
        if not hasattr(self, 'smoothed_error_vel'):
            self.smoothed_error_vel = error_vel
        self.smoothed_error_vel = self.smoothed_error_vel * 0.6 + error_vel * 0.4
        
        # sliding mode controller (fancy name for some magic that works)
        Kp = 0.85  # pull strength (random number that seems to work)
        Kd = 12.0  # brake thingy (stops the wild swinging)
        
        # calculate the base magic number
        control_signal = (Kp * error) + (Kd * self.smoothed_error_vel)
        
        # deadzone thing
        # if we're kinda close and not moving like crazy, chill out
        if abs(error) < DEADZONE:
            if abs(self.smoothed_error_vel) < 1.0:
                # almost there and stable: just fight gravity a bit
                control_signal = -2 # tiny lift thing
            else:
                # almost there but moving: hit the brakes harder
                control_signal *= 0.5
        
        # hysteresis loop thingy to build up speed
        # avoiding tiny clicks that mess everything up
        if self.mouse_pressed:
            # we're holding. let go earlier so we don't overshoot like an idiot
            threshold = -8 
        else:
            # we're not holding. need a good reason to start
            # low number so we catch falling bars fast
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
        # "none" means do jack squat
    
    def print_debug_info(self):
        if self.debug_info:
            status = "Catching" if self.catching_active else "Waiting"
            print(f"\r{status} | Fish: {'Found' if self.debug_info.get('fish_pos') else 'Not Found'} | "
                  f"Bar: {'Found' if self.debug_info.get('bar_pos') else 'Not Found'} | "
                  f"Action: {self.debug_info.get('action', 'unknown')} | "
                  f"Difference: {self.debug_info.get('difference', 0):.1f} | "
                  f"Mouse: {'Pressed' if self.mouse_pressed else 'Released'}", end="", flush=True)
    
    def run_bot(self):
        print("Fishing bot started. Press F2 to stop, F3 to exit.")
        
        # start mss thingy in the bot thread
        self.sct = mss.mss()
        
        # throw the bait out first
        self.release_bait()
        
        no_detection_count = 0
        max_no_detection = 60  # 1 second if we're not screwing up the fps
        
        while self.running:
            start_time = time.time()
            
            # grab the screen
            frame = self.capture_screen()
            
            # find the thing we're looking for
            fish_pos, bar_pos, fish_conf, bar_conf = self.detect_objects(frame)
            
            if fish_pos is not None and bar_pos is not None:
                # reset the "can't find shit" counter
                no_detection_count = 0
                self.catching_active = True
                
                # check if the bar is stuck (failsafe thing)
                current_time = time.time()
                if not hasattr(self, 'last_bar_y') or self.last_bar_y != bar_pos[1]:
                    self.last_bar_y = bar_pos[1]
                    self.bar_stagnant_since = current_time
                elif current_time - self.bar_stagnant_since > 5.0:
                    # bar been stuck in same spot for way too long
                    print("\n[Failsafe] Bar seems stuck! Clicking to un-stuck...")
                    pyautogui.click()
                    self.bar_stagnant_since = current_time # reset the damn timer
                
                # figure out what to do
                action, duration, difference, target = self.compute_control(fish_pos, bar_pos)
                
                # do the thing we figured out
                self.execute_control(action, duration)
                
                # update debug thing
                self.debug_info = {
                    "fish_pos": fish_pos,
                    "bar_pos": bar_pos,
                    "action": action,
                    "difference": difference,
                    "target": target,
                    "mouse_pressed": self.mouse_pressed
                }
            else:
                no_detection_count += 1
                
                # if we can't find anything for a while, we're done
                if self.catching_active and no_detection_count >= max_no_detection:
                    print("\nCatching complete! Recasting line...")
                    self.catching_active = False
                    
                    # let go of mouse before throwing again
                    if self.mouse_pressed:
                        pyautogui.mouseUp()
                        self.mouse_pressed = False
                        
                    self.recast_line()
                    no_detection_count = 0
                
                # can't find thing, let go of mouse now
                if self.mouse_pressed:
                    pyautogui.mouseUp()
                    self.mouse_pressed = False
                
                self.debug_info = {
                    "fish_pos": fish_pos,
                    "bar_pos": bar_pos,
                    "action": "no_detection",
                    "mouse_pressed": self.mouse_pressed
                }
            
            # print debug stuff
            self.print_debug_info()
            
            # fps limiting thing
            elapsed = time.time() - start_time
            if elapsed < FRAME_TIME:
                time.sleep(FRAME_TIME - elapsed)
    
    def start_bot(self):
        if not self.running:
            self.running = True
            self.bot_thread = threading.Thread(target=self.run_bot, daemon=True)
            self.bot_thread.start()
            print("Bot started!")
    
    def stop_bot(self):
        self.running = False
        if self.mouse_pressed:
            pyautogui.mouseUp()
            self.mouse_pressed = False
        # clean up mss mess
        if self.sct:
            self.sct = None
        print("Bot stopped!")
    
    def emergency_release(self):
        if self.mouse_pressed:
            pyautogui.mouseUp()
            self.mouse_pressed = False
        print("Emergency mouse release!")
    
    def exit_bot(self):
        self.stop_bot()
        print("\nExiting...")
        exit()
    
    def run(self):
        print("Fishing Bot Ready!")
        print("F1 - Start bot")
        print("F2 - Stop bot") 
        print("F3 - Exit")
        print("F4 - Re-calibrate region")
        print(f"Current Region: {self.monitor}")
        print("Waiting for hotkeys...")
        
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.exit_bot()

if __name__ == "__main__":
    bot = FishingBot()
    bot.run()
