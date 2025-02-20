import time
import os
import logging
import cv2
from os.path import join, dirname
from dotenv import load_dotenv
from threading import Event
from functools import wraps
from flask import Flask, Response, render_template, abort, jsonify, session, redirect, url_for, request
from config import TIMEOUT, FPS

# Первоначальная настройка

app = Flask(__name__, template_folder='web')

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)

# Константы

_FRAME_DELAY = 1/FPS  # Оптимизация задержки между кадрами

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')

SECRET_KEY = os.getenv('SECRET_KEY')

# Доп. настройки

app.secret_key = SECRET_KEY


# Декоратор для проверки доступа
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# Страничка для входа
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if (request.form.get('login') == ADMIN_USERNAME and
            request.form.get('password') == ADMIN_PASSWORD):
            session['authenticated'] = True
            session.permanent = True
            return redirect(url_for('index'))
        return "Ошибка доступа.", 401
    return '''
        <form method="post">
            <input type="text" name="login" placeholder="Login">
            <input type="password" name="password" placeholder="Password">
            <button type="submit">Войти</button>
        </form>
    '''

# Страничка для выхода
@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    return "<p>Вы успешно вышли из аккаунта</p>"

# Приватные

@app.route("/test_required")
@login_required
def test():
    return "<p>Если ты это видишь, значит ты авторизован.</p>"

# Общедоступные
@app.route('/')
def index():
    # logging.getLogger('werkzeug').disabled = True
    server = app.config.get('server')
    if not server:
        abort(500)
    with server.clients_lock:
        client_list = [f"{addr[0]}:{addr[1]}" for addr in server.clients]
    return render_template('index.html', clients=client_list)

# Получение ip,port всех онлайн клиентов. json
@app.route('/clients', methods=['GET'])
@login_required
def get_clients():
    server = app.config.get('server')
    if not server:
        abort(500)
    with server.clients_lock:
        client_list = [[addr[0], addr[1]] for addr in server.clients]
    return jsonify(client_list)
# Получение количество онлайн клиентов, json
@app.route('/number_clients',  methods=['GET'])
def get_number_clients():
    server = app.config.get('server')
    if not server:
        abort(500)
    with server.clients_lock:
        count = len(server.clients)
    return jsonify(count)
# Получение скрина в момент времени клиента. jpg
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

# Потоковая передача видео для конкретного клиента. jpg's
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

@app.route('/stream')
def stream():
    server = app.config.get('server')
    if not server:
        abort(500)

    def event_stream():
            while True:
                with server.clients_lock:
                    client_list = [f"{addr[0]}:{addr[1]}" for addr in server.clients]
                # Отправляем "empty" если клиентов нет
                data = ','.join(client_list) if client_list else "empty"
                yield f"data: {data}\n\n"
                time.sleep(1)

    return Response(event_stream(), mimetype="text/event-stream")

# if __name__ == "__main__":
#     app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, )