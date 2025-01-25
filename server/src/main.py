import socketserver
import numpy as np
import cv2
import threading

class UDPHandler(socketserver.BaseRequestHandler):
    def handle(self):
      # Использование атрибутов сервера
        buffer_lock = self.server.buffer_lock
        clients_lock = self.server.clients_lock
        frames_lock = self.server.frames_lock

        data, socket = self.request
        client_addr = self.client_address

        # Добавление клиента в список, если его там нет
        with clients_lock:
            if client_addr not in self.server.clients:
                self.server.clients.append(client_addr)

        header = data[:8]
        payload = data[8:]

        # Извлечение заголовка
        packet_seq = int.from_bytes(header[:4], 'big')
        packet_num = int.from_bytes(header[4:6], 'big')
        total_packets = int.from_bytes(header[6:8], 'big')

        # Инициализация буфера для клиента и пакета
        with buffer_lock:
            if client_addr not in self.server.buffer:
                self.server.buffer[client_addr] = {}
            client_buffer = self.server.buffer[client_addr]

            if packet_seq not in client_buffer:
                client_buffer[packet_seq] = [None] * total_packets

            client_buffer[packet_seq][packet_num] = payload

            # Проверка, все ли пакеты кадра получены
            if all(part is not None for part in client_buffer[packet_seq]):
                # Сборка пакетов
                frame_data = b''.join(client_buffer[packet_seq])
                frame = np.frombuffer(frame_data, dtype=np.uint8)
                frame = cv2.imdecode(frame, cv2.IMREAD_COLOR)

                if frame is not None:
                    with frames_lock:
                        self.server.frames[client_addr] = frame  # Сохранение кадра для отображения

                # Очистка буфера кадра
                del client_buffer[packet_seq]

                # Очистка буфера клиента, если он пуст
                if not client_buffer:
                    del self.server.buffer[client_addr]

if __name__ == "__main__":
    HOST, PORT = '0.0.0.0', 50005  # Прослушивание на всех интерфейсах

    class ThreadedUDPServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
        pass

    server = ThreadedUDPServer((HOST, PORT), UDPHandler)
    server.buffer = {}  # {client_addr: {packet_seq: [packets]}}
    server.buffer_lock = threading.Lock()

    server.frames = {}  # {client_addr: frame}
    server.frames_lock = threading.Lock()

    server.clients = []
    server.clients_lock = threading.Lock()

    def display_frames():
        while True:
            with server.frames_lock:
                frames = server.frames.copy()

            if frames:
                for client_addr, frame in frames.items():
                    window_name = f"{client_addr[0]}:{client_addr[1]}"
                    cv2.imshow(window_name, frame)

                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break

        cv2.destroyAllWindows()
        server.shutdown()

    # Отображение видео в главном потоке
    display_frames_thread = threading.Thread(target=display_frames)
    display_frames_thread.start()

    server.serve_forever()
