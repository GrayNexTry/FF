import socketserver
import time
import threading
import os
import socket
import logging
from config import WHITELIST, TIMEOUT, MAX_BUFFER_SIZE, CLIENT_RECEIVE_PORT
from web_server import app

class Client:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.last_activity = time.time()
        self.buffer = {}  # Буфер для хранения пакетов
        self.frames = []  # Список собранных фреймов

    def add_packet(self, packet_seq, packet_num, total_packets, payload):
        # Если последовательность новая, создаём список для пакетов
        if packet_seq not in self.buffer:
            self.buffer[packet_seq] = [None] * total_packets

        # Сохраняем пакет в соответствующую позицию
        self.buffer[packet_seq][packet_num] = payload

        # Проверяем, завершена ли последовательность
        if all(self.buffer[packet_seq]):
            # Собираем данные в один фрейм
            frame_data = b"".join(self.buffer[packet_seq])
            self.frames.append(frame_data)
            # Удаляем завершённую последовательность
            del self.buffer[packet_seq]

    def get_frames(self):
        # Возвращаем собранные фреймы и очищаем список
        frames = self.frames[:]
        self.frames.clear()
        return frames

# Настраиваем логгер
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
class ThreadedUDPServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clients = {}  # Хранит объекты Client {client_addr: Client}
        self.server_ready = threading.Event()
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

    def get_or_create_client(self, client_addr):
        with self.clients_lock:
            if client_addr not in self.clients:
                ip, port = client_addr
                self.clients[client_addr] = Client(ip, port)
            return self.clients[client_addr]

    def remove_client(self, client_addr):
        with self.clients_lock:
            if client_addr in self.clients:
                del self.clients[client_addr]

class UDPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            data, socket = self.request
            client_addr = self.client_address

            # Проверяем, разрешён ли клиент
            with self.server.clients_lock:
                allowed = not WHITELIST or client_addr[0] in WHITELIST
                if allowed and client_addr not in self.server.clients:
                    self.server.clients[client_addr] = Client(*client_addr)
                    logging.info(f"{client_addr} подключился.")

            # Получаем или создаём клиента
            client = self.server.get_or_create_client(client_addr)
            client.last_activity = time.time()

            # Разбираем заголовок и полезную нагрузку
            header = data[:8]
            payload = data[8:]
            packet_seq = int.from_bytes(header[:4], 'big')
            packet_num = int.from_bytes(header[4:6], 'big')
            total_packets = int.from_bytes(header[6:8], 'big')

            # Добавляем пакет в буфер клиента
            client.add_packet(packet_seq, packet_num, total_packets, payload)

            # Обрабатываем собранные фреймы
            frames = client.get_frames()
            for frame in frames:
                with self.server.clients_lock:
                    self.server.clients[client_addr].frames.append(frame)

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
                addr for addr, client in server.clients.items()
                if current_time - client.last_activity > TIMEOUT
            ]
            for addr in inactive_clients:
                server.remove_client(addr)
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
        uvicorn.run(app, host=WEB_HOST, port=WEB_PORT, access_log=False, log_level="critical")

    threads = [
        threading.Thread(target=cleanup_inactive_clients, args=(server,)),
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