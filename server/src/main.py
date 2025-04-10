import socketserver
import time
import threading
import os
import socket
import logging
from threading import RLock
from config import WHITELIST, TIMEOUT, MAX_BUFFER_SIZE, CLIENT_RECEIVE_PORT
from web_server import app

# Настраиваем логгер
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
class ThreadedUDPServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffer = {}
        self.frames = {}
        self.clients = set()
        self.last_activity = {}
        self.server_ready = threading.Event()
        self.buffer_lock = threading.RLock()
        self.frames_lock = threading.RLock()
        self.clients_lock = threading.RLock()

    def serve_forever(self):
        self.server_ready.set()
        logging.info("Сервер запускается...")
        try:
            super().serve_forever()
            logging.info("Сервер запущен без ошибок.")
        finally:
            logging.info("Сервер выключен.")

    def shutdown(self):
        super().shutdown()
        
    
    def send_command_to_client(self, ip, command):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            server = self
            if server is None:
                logging.error("Сервер не инициализирован в app.state.")
                return False
            with server.clients_lock:
                if not any(ip in ips for ips in server.clients):
                    logging.error(f"IP {ip} не в списке клиентов.")
                    return False
            #     if ip not in server.clients:
            #         logging.warning(f"Клиент {ip} не подключен")
            #         return False
                                
            sock.settimeout(2)
                        
                        # Use client's IP but different port for commands
            command_addr = (ip, CLIENT_RECEIVE_PORT)
            sock.sendto(command.encode(), command_addr)
            return True
                        
        except Exception as e:
            logging.error(f"Ошибка отправки команды: {e}")
            return False
        finally:
            sock.close()

    def handle_buffer_size(self, client_addr):
        with self.buffer_lock:
            if client_addr in self.buffer and len(self.buffer[client_addr]) > MAX_BUFFER_SIZE:
                sorted_frames = sorted(self.buffer[client_addr].keys())
                frames_to_remove = len(self.buffer[client_addr]) - MAX_BUFFER_SIZE
                for old_frame in sorted_frames[:frames_to_remove]:
                    del self.buffer[client_addr][old_frame]

class UDPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            data, socket = self.request
            client_addr = self.client_address

            with self.server.clients_lock:
                allowed = not WHITELIST or client_addr[0] in WHITELIST
                if allowed and client_addr not in self.server.clients:
                    self.server.clients.add(client_addr)
                    self.server.last_activity[client_addr] = time.time()
                    logging.info(f"{client_addr} подключился.")

            self.server.last_activity[client_addr] = time.time()

            header = data[:8]
            payload = data[8:]
            packet_seq = int.from_bytes(header[:4], 'big')
            packet_num = int.from_bytes(header[4:6], 'big')
            total_packets = int.from_bytes(header[6:8], 'big')

            with self.server.buffer_lock:
                if client_addr not in self.server.buffer:
                    self.server.buffer[client_addr] = {}

                client_buffer = self.server.buffer[client_addr]
                if packet_seq not in client_buffer:
                    client_buffer[packet_seq] = [None] * total_packets

                client_buffer[packet_seq][packet_num] = payload

                self.server.handle_buffer_size(client_addr)

                if all(part is not None for part in client_buffer[packet_seq]):
                    frame_data = b''.join(client_buffer[packet_seq])

                    with self.server.frames_lock:
                        self.server.frames[client_addr] = frame_data

                    del client_buffer[packet_seq]
                    if not client_buffer:
                        del self.server.buffer[client_addr]

        except Exception as e:
            logging.error(f"Ошибка при обработке данных от {self.client_address}: {e}")

def cleanup_inactive_clients(server):
    server.server_ready.wait()
    logging.info("Поток удаление неактивных клиентов успешно запущен.")
    while True:
        time.sleep(5)
        current_time = time.time()
        with server.clients_lock:
            inactive_clients = [
                addr for addr in server.clients
                if current_time - server.last_activity.get(addr, 0) > TIMEOUT
            ]
            for addr in inactive_clients:
                server.clients.discard(addr)
                with server.frames_lock:
                    server.frames.pop(addr, None)
                with server.buffer_lock:
                    server.buffer.pop(addr, None)
                server.last_activity.pop(addr, None)
                logging.warning(f"{addr} отключен по таймауту.")

if __name__ == "__main__":
    HOST, PORT = '0.0.0.0', 50005
    WEB_HOST, WEB_PORT = '0.0.0.0', 5000

    os.system('clear||cls')

    server = ThreadedUDPServer((HOST, PORT), UDPHandler)
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4*1024*1024)

    app.state.server = server

    def run_uvicorn():
        import uvicorn
        uvicorn.run(app, host=WEB_HOST, port=WEB_PORT, access_log=False,log_level="critical")

    threads = [
        threading.Thread(target=cleanup_inactive_clients, args=(server,)),
        # threading.Thread(target=server.serve_forever),
        threading.Thread(target=run_uvicorn),
    ]

    for t in threads:
        t.daemon = True
        t.start()

    try:
        logging.info(f"Сервер слушает на {HOST}:{PORT}")
        logging.info(f"Вебка доступна тут: http://{WEB_HOST}:{WEB_PORT}")
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Получен сигнал завершения (Ctrl+C), выключаем...")
        server.shutdown()
        server.server_close()
        logging.info("Сервер полностью остановлен.")