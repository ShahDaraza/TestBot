import argparse
import json
import socket
import threading
import time
from typing import Dict, Optional, Tuple

class CommandHub:
    def __init__(self, host: str = '0.0.0.0', port: int = 9999, backlog: int = 100):
        self.host = host
        self.port = port
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((host, port))
        self.server.listen(backlog)
        self.server.settimeout(1.0)

        self.nodes: Dict[Tuple[str, int], socket.socket] = {}
        self.node_id_map: Dict[Tuple[str, int], str] = {}
        self.id_to_addr: Dict[str, Tuple[str, int]] = {}
        self.node_status: Dict[str, dict] = {}
        self.next_node_id = 1
        self.lock = threading.Lock()
        self.running = True

        print(f"[*] Command Hub Active on {host}:{port}")

    def accept_nodes(self) -> None:
        while self.running:
            try:
                conn, addr = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            with self.lock:
                self.nodes[addr] = conn
                node_id = f'node-{self.next_node_id:03d}'
                self.node_id_map[addr] = node_id
                self.id_to_addr[node_id] = addr
                self.next_node_id += 1
            conn.settimeout(1.0)
            print(f"[+] Node Connected: {addr} assigned {node_id}")
            thread = threading.Thread(target=self.handle_node, args=(conn, addr), daemon=True)
            thread.start()

    def handle_node(self, conn: socket.socket, addr: Tuple[str, int]) -> None:
        try:
            while self.running:
                try:
                    data = conn.recv(4096).decode('utf-8', errors='ignore')
                except socket.timeout:
                    continue
                except (ConnectionResetError, BrokenPipeError):
                    break

                if not data:
                    break

                for message in data.strip().splitlines():
                    message = message.strip()
                    if not message:
                        continue
                    if message.startswith("STATUS:"):
                        status_json = message[7:]
                        try:
                            status = json.loads(status_json)
                            node_id = self.node_id_map.get(addr)
                            with self.lock:
                                if node_id:
                                    self.node_status[node_id] = status
                                else:
                                    self.node_status[str(addr)] = status
                            print(f"[*] Status from {addr} ({node_id}): {status}")
                        except json.JSONDecodeError:
                            print(f"[!] Invalid status from {addr}: {status_json}")
                    else:
                        print(f"[?] Unknown message from {addr}: {message}")
        finally:
            self.remove_node(addr)

    def remove_node(self, addr: Tuple[str, int]) -> None:
        with self.lock:
            conn = self.nodes.pop(addr, None)
            node_id = self.node_id_map.pop(addr, None)
            if node_id:
                self.id_to_addr.pop(node_id, None)
                self.node_status.pop(node_id, None)

        if conn:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()

        if node_id:
            print(f"[-] Node disconnected: {addr} ({node_id})")
        else:
            print(f"[-] Node disconnected: {addr}")

    def resolve_node(self, identifier: str) -> Tuple[Optional[Tuple[str, int]], Optional[socket.socket]]:
        with self.lock:
            if ':' in identifier:
                try:
                    host, port_text = identifier.split(':')
                    addr = (host, int(port_text))
                except ValueError:
                    return None, None
            else:
                addr = self.id_to_addr.get(identifier)
            if not addr:
                return None, None
            return addr, self.nodes.get(addr)

    def broadcast_command(self, cmd: str) -> None:
        with self.lock:
            nodes = list(self.nodes.items())

        print(f"[*] Sending '{cmd}' to {len(nodes)} node(s)...")
        for addr, conn in nodes:
            try:
                conn.sendall(f"{cmd}\n".encode('utf-8'))
            except (socket.error, ConnectionResetError, BrokenPipeError):
                print(f"[!] Node {addr} failed, removing")
                self.remove_node(addr)

    def send_command(self, addr_text: str, cmd: str) -> None:
        addr, conn = self.resolve_node(addr_text)
        if not addr or not conn:
            print(f"[!] No connected node found for '{addr_text}'")
            return

        try:
            conn.sendall(f"{cmd}\n".encode('utf-8'))
            node_id = self.node_id_map.get(addr, addr)
            print(f"[*] Sent '{cmd}' to {node_id} ({addr})")
        except (socket.error, ConnectionResetError, BrokenPipeError):
            print(f"[!] Failed to send to {addr}, removing")
            self.remove_node(addr)

    def show_aggregated_status(self) -> None:
        print("\n=== Aggregated Node Status ===")
        with self.lock:
            if not self.node_status:
                print("No status reports received yet.")
            for node_id, status in sorted(self.node_status.items()):
                addr = self.id_to_addr.get(node_id, ('unknown', 0))
                print(f"{node_id} {addr}: {status}")
            print(f"Total nodes with status: {len(self.node_status)}")

    def list_nodes(self) -> None:
        with self.lock:
            if not self.nodes:
                print("No connected nodes.")
                return
            print("\n=== Connected Nodes ===")
            for addr in sorted(self.nodes):
                node_id = self.node_id_map.get(addr, 'unknown')
                status = self.node_status.get(node_id, {})
                summary = status.get('OS', 'unknown')
                print(f"- {node_id}: {addr} ({summary})")
            print(f"Total connected nodes: {len(self.nodes)}")

    def shutdown(self) -> None:
        self.running = False
        try:
            self.server.close()
        except OSError:
            pass
        with self.lock:
            nodes = list(self.nodes.items())
        for addr, conn in nodes:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()
        print("[*] Command Hub shutdown complete.")

    def cli_loop(self) -> None:
        help_text = (
            "Commands:\n"
            "  help                    Show this message\n"
            "  list                    List connected nodes\n"
            "  status                  Show aggregated status reports\n"
            "  broadcast STATUS_REPORT Ask all nodes for a status update\n"
            "  broadcast SHUTDOWN_NODE Tell all nodes to disconnect\n"
            "  broadcast PING         Send a ping to all nodes\n"
            "  send <node-id|host:port> <COMMAND> Send a command to a single node\n"
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
            elif command == 'send':
                if len(parts) < 3:
                    print("[!] send requires node id or address and command")
                    continue
                self.send_command(parts[1], ' '.join(parts[2:]))
            elif command in {'quit', 'exit'}:
                break
            else:
                print(f"[!] Unknown command: {command}")

        self.shutdown()

    def start(self) -> None:
        accept_thread = threading.Thread(target=self.accept_nodes, daemon=True)
        accept_thread.start()
        self.cli_loop()
        accept_thread.join(timeout=1.0)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Command hub for remote nodes')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind the hub')
    parser.add_argument('--port', type=int, default=9999, help='Port to bind the hub')
    args = parser.parse_args()

    hub = CommandHub(host=args.host, port=args.port)
    hub.start()
