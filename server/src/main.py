import socketserver
import numpy as np
import cv2
import threading
from flask import Flask, Response

from config import whitelist

class UDPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        buffer_lock = self.server.buffer_lock
        clients_lock = self.server.clients_lock
        frames_lock = self.server.frames_lock

        data, socket = self.request
        client_addr = self.client_address

        # Добавление клиента в список, если его там нет
        with clients_lock:
            if client_addr[0] in whitelist:
                if client_addr not in self.server.clients:
                    self.server.clients.append(client_addr)
                    print(f"{client_addr} added to clients.")
            else:
                return  # Игнорировать клиентов, не входящих в белый список

        header = data[:8]
        payload = data[8:]

        # Извлечение заголовка
        packet_seq = int.from_bytes(header[:4], 'big')
        packet_num = int.from_bytes(header[4:6], 'big')
        total_packets = int.from_bytes(header[6:8], 'big')

        # Инициализация буфера для клиента и пакета
        if client_addr[0] in whitelist:
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

# Flask-приложение для веб-трансляции
app = Flask(__name__)

# Глобальная ссылка на сервер
server_instance = None

# Генератор MJPEG для трансляции
def mjpeg_stream():
    global server_instance
    while True:
        with server_instance.frames_lock:
            if not server_instance.frames:
                continue
            # Берем первый доступный кадр
            client_addr, frame = next(iter(server_instance.frames.items()))

        if frame is not None:
            _, buffer = cv2.imencode('.jpg', frame)
            frame_data = buffer.tobytes()

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(mjpeg_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    HOST, PORT = '0.0.0.0', 50005

    class ThreadedUDPServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
        pass

    server = ThreadedUDPServer((HOST, PORT), UDPHandler)
    server.buffer = {}  # {client_addr: {packet_seq: [packets]}}
    server.buffer_lock = threading.Lock()

    server.frames = {}  # {client_addr: frame}
    server.frames_lock = threading.Lock()

    server.clients = []
    server.clients_lock = threading.Lock()

    # Сохраняем экземпляр сервера для Flask
    server_instance = server

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

    # Запускаем поток для отображения кадров локально
    display_frames_thread = threading.Thread(target=display_frames, daemon=True)
    display_frames_thread.start()

    # Запуск Flask-сервера в отдельном потоке
    def start_flask():
        app.run(host="0.0.0.0", port=8080, threaded=True)

    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # Запускаем UDP-сервер
    server.serve_forever()

