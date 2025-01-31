import time
import logging
import cv2
from flask import Flask, Response, render_template_string, abort, jsonify
from config import TIMEOUT, FPS

app = Flask(__name__)

_FRAME_DELAY = 1/FPS  # Оптимизация задержки между кадрами

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Главная страница с активными подключениями
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
                <h1>Активные подключения:</h1>
                <div id="client-list">
                    {% for client in clients %}
                        <a href="/video/{{ client }}">{{ client }}</a><br>
                    {% else %}
                        <p>Нет активных подключений</p>
                    {% endfor %}
                </div>
            </body>
        </html>
    ''', clients=client_list)

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
        while True:
            # Объединенная проверка состояния
            with server.clients_lock:
                current_clients = client_addr in server.clients
                last_active = server.last_activity.get(client_addr, 0)
            current_time = time.time()
            if not current_clients or (current_time - last_active) > TIMEOUT:
                break

            # Получение кадра с минимальной блокировкой
            with server.frames_lock:
                frame = server.frames.get(client_addr)
            if frame is not None:
                ret, jpeg = cv2.imencode('.jpg', frame)
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n'
                           + jpeg.tobytes() + b'\r\n')
            time.sleep(_FRAME_DELAY)

    return Response(generate(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, )