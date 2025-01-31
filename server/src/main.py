# Импорты всяких штук для работы с сетью, картинками и т.д.
import socketserver
import time
import numpy as np
import cv2
import socket
import threading
import logging
from threading import RLock
from config import WHITELIST, TIMEOUT
from web_server import app

# Настраиваем логер чтобы видеть что происходит
logging.basicConfig(level=logging.INFO)

# Класс для UDP сервера с потоками (чтобы всё не лагало)
class ThreadedUDPServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
    daemon_threads = True  # Потоки сами умрут когда надо
    block_on_close = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffer = {}    # Здесь храним кусочки видео от клиентов
        self.frames = {}    # Собранные кадры для отображения
        self.clients = set()   # Подключенные клиенты
        self.last_activity = {}  # Когда последний раз что-то присылали
        self.is_running = False
        self.server_ready = threading.Event()  # Событие для синхронизации
        self.buffer_lock = threading.RLock()
        self.frames_lock = threading.RLock()
        self.clients_lock = threading.RLock()

    def serve_forever(self):
        self.is_running = True
        self.server_ready.set()  # Сигнализируем о готовности сервера
        logging.info("Сервер запускается...")
        try:
            super().serve_forever()
            logging.info("Сервер запущен без ошибок.")
        finally:
            self.is_running = False
            logging.info("Сервер выключен.")

# Обработчик входящих UDP пакетов
class UDPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            data, socket = self.request
            client_addr = self.client_address  # Адрес того, кто прислал данные

            # Проверяем белый список чтобы пускать только своих
            with self.server.clients_lock:
                if client_addr[0] in WHITELIST:
                    if client_addr not in self.server.clients:
                        self.server.clients.add(client_addr)
                        self.server.last_activity[client_addr] = time.time()
                        logging.info(f"{client_addr} подключился.")
                else:
                    return  # Если не в белом списке, игнорируем

            # Обновляем время последней активности
            self.server.last_activity[client_addr] = time.time()

            # Разбираем заголовок пакета
            header = data[:8]
            payload = data[8:]
            packet_seq = int.from_bytes(header[:4], 'big')      # Номер кадра
            packet_num = int.from_bytes(header[4:6], 'big')     # Номер пакета
            total_packets = int.from_bytes(header[6:8], 'big')  # Всего пакетов

            # Собираем кадр из кусочков
            with self.server.buffer_lock:
                if client_addr not in self.server.buffer:
                    self.server.buffer[client_addr] = {}

                client_buffer = self.server.buffer[client_addr]
                if packet_seq not in client_buffer:
                    client_buffer[packet_seq] = [None] * total_packets

                # Записываем кусочек в нужное место
                client_buffer[packet_seq][packet_num] = payload

                # Если все кусочки кадра собраны
                if all(part is not None for part in client_buffer[packet_seq]):
                    frame_data = b''.join(client_buffer[packet_seq])  # Склеиваем
                    frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_UNCHANGED)

                    if frame is not None:
                        with self.server.frames_lock:
                            self.server.frames[client_addr] = frame  # Сохраняем кадр

                    del client_buffer[packet_seq]  # Чистим память
                    if not client_buffer:
                        del self.server.buffer[client_addr]

        except Exception as e:
            logging.error(f"Ошибка при обработке данных от {self.client_address}: {e}ю")

# Удаляем клиентов которые долго не пишут
def cleanup_inactive_clients(server):
    server.server_ready.wait()  # Ждем готовности сервера
    logging.info("Цикл очистки неактивных клиентов запущен.")
    while server.is_running:
        time.sleep(5)
        current_time = time.time()
        with server.clients_lock:
            # Ищем тех, кто превысил таймаут
            inactive_clients = [
                addr for addr in server.clients
                if current_time - server.last_activity.get(addr, 0) > TIMEOUT
            ]
            for addr in inactive_clients:
                # Чистим все данные по клиенту
                server.clients.discard(addr)
                with server.frames_lock:
                    server.frames.pop(addr, None)
                with server.buffer_lock:
                    server.buffer.pop(addr, None)
                server.last_activity.pop(addr, None)
                logging.info(f"{addr} отключен по таймауту.")

# Запускаем всё здесь
if __name__ == "__main__":
    HOST, PORT = '0.0.0.0', 50005       # Настройки для UDP
    WEB_HOST, WEB_PORT = '0.0.0.0', 5000  # Настройки для веб-сервера

    server = ThreadedUDPServer((HOST, PORT), UDPHandler)
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4*1024*1024)  # Буфер побольше

    app.config['server'] = server  # Даем веб-серверу доступ к нашему серверу

    # Запускаем три важные штуки параллельно
    threads = [
        threading.Thread(target=cleanup_inactive_clients, args=(server,)),  # Очистка
        threading.Thread(target=app.run, kwargs={                           # Веб-интерфейс
            'host': WEB_HOST,
            'port': WEB_PORT,
            'debug': False,
            'use_reloader': False
        })
    ]

    for t in threads:
        t.daemon = True  # Чтобы потоки умерли когда основной умрет
        t.start()
    try:
        logging.info(f"Сервер слушает на {HOST}:{PORT}")
        logging.info(f"Вебка доступна тут: http://{WEB_HOST}:{WEB_PORT}")
        server.serve_forever()  # Главный цикл сервера
    except KeyboardInterrupt:
        logging.info("Выключение...")
    finally:
        server.shutdown()
        server.server_close()
        cv2.destroyAllWindows()