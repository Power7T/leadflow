import subprocess
import base64
import os
import json
import time

def take_screenshot(device_ip="192.168.8.157:5555"):
    """Takes a screenshot via ADB and pulls it to the Mac."""
    print("[*] Capturing screen...")
    subprocess.run(f"adb -s {device_ip} shell screencap -p /sdcard/screen.png", shell=True)
    subprocess.run(f"adb -s {device_ip} pull /sdcard/screen.png /tmp/screen.png", shell=True)
    return "/tmp/screen.png"

def tap_screen(x, y, device_ip="192.168.8.157:5555"):
    """Taps the screen at the given coordinates."""
    subprocess.run(f"adb -s {device_ip} shell input tap {x} {y}", shell=True)

print("AI Captcha & UI Automation Engine Ready.")
