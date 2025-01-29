# Импорты для работы с временем, логами и видео
import time
import logging
import cv2
from flask import Flask, Response, render_template_string, abort
from config import TIMEOUT

# Создаем Flask приложение для веб-интерфейса
app = Flask(__name__)

# Главная страница со списком клиентов
@app.route('/')
def index():
    server = app.config.get('server')
    if not server:  # Если сервер не подключен - ошибка
        abort(500)

    # Берем список активных клиентов
    with server.clients_lock:
        clients = list(server.clients)

    # Превращаем адреса в строки типа "ip:порт"
    client_list = [f"{addr[0]}:{addr[1]}" for addr in clients]

    # Рендерим простой HTML с автоматическим обновлением
    return render_template_string('''
        <html>
            <head>
                <title>Video Streams</title>
                <meta http-equiv="refresh" content="5"> <!-- Обновляем страницу каждые 5 сек -->
            </head>
            <body>
                <h1>Active Clients:</h1>
                {% for client in clients %}
                    <a href="/video/{{ client }}">{{ client }}</a><br> <!-- Ссылки на видео -->
                {% else %}
                    <p>No active clients</p> <!-- Если клиентов нет -->
                {% endfor %}
            </body>
        </html>
    ''', clients=client_list)

# Страница с видео-потоком конкретного клиента
@app.route('/video/<client_id>')
def video_feed(client_id):
    server = app.config.get('server')
    if not server:
        abort(500)  # Сервер не подключен

    try:
        # Парсим адрес из строки "ip:port"
        ip, port = client_id.split(':')
        client_addr = (ip, int(port))
    except:
        abort(404)  # Если адрес кривой

    # Проверяем что клиент действительно активен
    with server.clients_lock:
        if client_addr not in server.clients:
            abort(404)

    # Генерим видео-поток
    def generate():
        while True:
            # Если клиент отвалился - выходим
            with server.clients_lock:
                if client_addr not in server.clients:
                    break

            # Проверяем таймаут
            current_time = time.time()
            last_active = server.last_activity.get(client_addr, 0)
            if current_time - last_active > TIMEOUT:
                break

            # Берем последний кадр
            with server.frames_lock:
                frame = server.frames.get(client_addr, None)

            # Кодируем в JPEG и отправляем
            if frame is not None:
                ret, jpeg = cv2.imencode('.jpg', frame)
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')

            time.sleep(0.05)  # Не грузим процессор

    # Возвращаем видео-поток специальным форматом
    return Response(generate(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')