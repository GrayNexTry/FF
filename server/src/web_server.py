import time
import os
import logging
import cv2
from threading import Event
from flask import Flask, Response, render_template_string, abort, jsonify
from config import TIMEOUT, FPS

app = Flask(__name__)

_FRAME_DELAY = 1/FPS  # Оптимизация задержки между кадрами

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Общедоступные

@app.route('/')
def index():
    # logging.getLogger('werkzeug').disabled = True
    server = app.config.get('server')
    if not server:
        abort(500)
    with server.clients_lock:
        client_list = [f"{addr[0]}:{addr[1]}" for addr in server.clients]
    return render_template_string('''
        <html>
            <head>
                <title>Стримы</title>
                <script>
                    const eventSource = new EventSource("/stream");
                    eventSource.onmessage = function(event) {
                        const clients = event.data.split(',');
                        document.getElementById("client-list").innerHTML = clients.map(c => `<a href="/video/${c}">${c}</a><br>`).join('');
                    };
                </script>
            </head>
            <body>
                <h1>Доступные API запросы:</h1>
                <div>
                    <a href="/clients">Онлайн клиенты</a><br>
                    <a href="/number_clients">Количество онлайн клиентов</a><br>
                </div>
                <h1>Активные подключения:</h1>
                <div id="client-list">
                    {% for client in clients %}
                        <div>
                            <h2>{{ client }}:</h2>
                            <a href="/video/{{ client }}">Прямой поток {{ client }}</a><br>
                            <a href="/screenshot/{{ client }}">Скрин {{ client }}</a><br>
                        </div>
                    {% else %}
                        <p>Нет активных подключений</p>
                    {% endfor %}
                </div>
            </body>
        </html>
    ''', clients=client_list)


@app.route('/clients', methods=['GET'])
def get_clients():
    server = app.config.get('server')
    if not server:
        abort(500)
    with server.clients_lock:
        client_list = [[addr[0], addr[1]] for addr in server.clients]
    return jsonify(client_list)

@app.route('/number_clients',  methods=['GET'])
def get_number_clients():
    server = app.config.get('server')
    if not server:
        abort(500)
    with server.clients_lock:
        count = len(server.clients)
    return jsonify(count)

@app.route('/screenshot/<client_id>', methods=['GET'])
def screenshot(client_id):
    server = app.config.get('server')
    if not server:
        abort(500)
    try:
        ip, port = client_id.rsplit(':', 1)
        client_addr = (ip, int(port))
    except ValueError:
        abort(404)

    # Однократная проверка активности клиента
    with server.clients_lock:
        if client_addr not in server.clients:
            abort(404)

    if client_addr in server.clients:
        with server.frames_lock:
            jpeg_data = server.frames.get(client_addr)
            if not jpeg_data:
                abort(500)

    return Response(jpeg_data, mimetype='image/jpeg')

# Потоковая передача видео для конкретного клиента
@app.route('/video/<client_id>')
def video_feed(client_id):
    server = app.config.get('server')
    if not server:
        abort(500)
    try:
        ip, port = client_id.rsplit(':', 1)
        client_addr = (ip, int(port))
    except ValueError:
        abort(404)

    # Однократная проверка активности клиента
    with server.clients_lock:
        if client_addr not in server.clients:
            abort(404)

    def generate():
        next_frame_time = time.time()
        while True:
            if client_addr in server.clients:
                with server.frames_lock:
                    jpeg_data = server.frames.get(client_addr)
                    if not jpeg_data:
                        yield

                if jpeg_data:
                    yield (b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n'
                        + jpeg_data + b'\r\n')

                next_frame_time += _FRAME_DELAY
                sleep_time = next_frame_time - time.time()
                if sleep_time > 0:
                    time.sleep(sleep_time)
            else:
                break

    return Response(generate(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, )