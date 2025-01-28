import socketserver
import time
import numpy as np
import cv2
import threading
import logging
from config import WHITELIST, TIMEOUT

# Настройка логирования
logging.basicConfig(level=logging.INFO)

def display_frames():
    while True:
        with server.frames_lock:
            frames = list(server.frames.values())
        if frames:
            # Объединяем все кадры для отображения
            combined_frame = cv2.hconcat(frames)
            cv2.imshow("Clients", combined_frame)
        else:
            # Если кадров нет, очищаем окно
            blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.imshow("Clients", blank_frame)
        # Проверяем нажатие клавиши
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
    cv2.destroyAllWindows()
    server.shutdown()

def cleanup_inactive_clients():
    while True:
        time.sleep(1)
        current_time = time.time()
        with server.clients_lock:
            inactive_clients = []
            for client_addr in server.clients:
                last_active = server.last_activity.get(client_addr, 0)
                if current_time - last_active > TIMEOUT:
                    inactive_clients.append(client_addr)
            for client_addr in inactive_clients:
                if client_addr in server.clients:
                    server.clients.remove(client_addr)
                with server.frames_lock:
                    server.frames.pop(client_addr, None)
                with server.buffer_lock:
                    server.buffer.pop(client_addr, None)
                server.last_activity.pop(client_addr, None)
                logging.info(f"{client_addr} отключен по таймауту.")

class UDPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            buffer_lock = self.server.buffer_lock
            clients_lock = self.server.clients_lock
            frames_lock = self.server.frames_lock
            data, socket = self.request
            client_addr = self.client_address
            with clients_lock:
                if client_addr[0] in WHITELIST:
                    if client_addr not in self.server.clients:
                        self.server.clients.append(client_addr)
                        self.server.last_activity[client_addr] = time.time()  # Инициализация активности
                        logging.info(f"{client_addr} подключился.")
                else:
                    return  # Игнорировать клиентов, не входящих в белый список
            # Обновление активности клиента
            self.server.last_activity[client_addr] = time.time()
            header = data[:8]
            payload = data[8:]
            # Извлечение заголовка
            packet_seq = int.from_bytes(header[:4], 'big')
            packet_num = int.from_bytes(header[4:6], 'big')
            total_packets = int.from_bytes(header[6:8], 'big')
            if client_addr[0] in WHITELIST:
                with buffer_lock:
                    if client_addr not in self.server.buffer:
                        self.server.buffer[client_addr] = {}
                    client_buffer = self.server.buffer[client_addr]
                    if packet_seq not in client_buffer:
                        client_buffer[packet_seq] = [None] * total_packets
                    client_buffer[packet_seq][packet_num] = payload
                    if all(part is not None for part in client_buffer[packet_seq]):
                        frame_data = b''.join(client_buffer[packet_seq])
                        frame = np.frombuffer(frame_data, dtype=np.uint8)
                        frame = cv2.imdecode(frame, cv2.IMREAD_COLOR)
                        if frame is not None:
                            with frames_lock:
                                self.server.frames[client_addr] = frame
                        del client_buffer[packet_seq]
                        if not client_buffer:
                            del self.server.buffer[client_addr]
        except Exception as e:
            logging.error(f"Ошибка при обработке данных от {self.client_address}: {e}")

if __name__ == "__main__":
    HOST, PORT = '0.0.0.0', 50005
    class ThreadedUDPServer(socketserver.ThreadingMixIn, socketserver.UDPServer): pass
    server = ThreadedUDPServer((HOST, PORT), UDPHandler)
    server.buffer = {}  # {client_addr: {packet_seq: [packets]}}
    server.buffer_lock = threading.Lock()
    server.frames = {}  # {client_addr: frame}
    server.frames_lock = threading.Lock()
    server.clients = []  # [client_addr]
    server.clients_lock = threading.Lock()
    # Запускаем поток для отображения кадров локально
    display_frames_thread = threading.Thread(target=display_frames, daemon=True)
    display_frames_thread.start()
    # Timeout
    cleanup_thread = threading.Thread(target=cleanup_inactive_clients, daemon=True)
    cleanup_thread.start()
    server.last_activity = {}  # {client_addr: timestamp}
    # Запускаем UDP-сервер
    server.serve_forever()