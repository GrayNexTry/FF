# Импорты для работы с видео, сетью и потоками
import cv2
import socket
import threading
import sys
import time
import logging
from config import MTU_SIZE, ID_DEVICE, JPEG_QUALITY, FPS

# Настройка логов чтобы видеть ошибки
logging.basicConfig(level=logging.INFO)

# Задержка между кадрами (вычисляем из FPS)
DELAY = 1 / FPS

# Общие переменные между потоками (с блокировками!)
frame = None  # Текущий кадр с камеры
frame_lock = threading.Lock()  # Замок для кадра
now_time = "NONE | 00:00:00"  # Текущее время для надписи
now_time_lock = threading.Lock()  # Замок для времени

# Поток для обновления времени каждую секунду
def get_time():
    global now_time
    while True:
        t = time.localtime()
        with now_time_lock:  # Блокируем доступ на запись
            now_time = time.strftime("%H:%M:%S", t)
        time.sleep(1)

# Поток для захвата видео с камеры
def get_video():
    global frame
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    if not cap.isOpened():
        logging.error("Камера не работает! Проверь подключение.")
        sys.exit(1)

    # Рассчитываем позицию текста один раз
    text = f"{ID_DEVICE}, 00:00:00"  # Шаблон
    (text_width, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    x = (640 - text_width) // 16
    y = 30

    while True:
        # Читаем кадр и добавляем текст
        ret, current_frame = cap.read()
        if not ret:
            logging.error("Не могу прочитать кадр! Камера сломалась?")
            break

        # Обновляем время в тексте с блокировкой
        with now_time_lock:  # Блокируем доступ на чтение
            time_text = f"{ID_DEVICE} | {now_time}"

        # Рисуем текст на кадре
        frame_with_text = cv2.putText(
            current_frame, time_text, (x, y),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA
        )

        # Сохраняем кадр с блокировкой
        with frame_lock:
            frame = frame_with_text.copy()

        time.sleep(DELAY)  # Ждем перед следующим кадром

# Поток для отправки видео через UDP
def send_video(ip, port):
    server_address = (ip, port)

    try:
        # Создаем UDP-сокет с таймаутом
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5)

        packet_seq = 0  # Счетчик пакетов

        while True:
            # Берем текущий кадр с блокировкой
            with frame_lock:
                current_frame = frame

            if current_frame is None:
                continue  # Пропускаем если кадра нет

            # Конвертируем в JPEG
            success, buffer = cv2.imencode(
                '.jpg', current_frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
            )
            if not success:
                logging.warning("Не смог сжать кадр в JPEG!")
                continue

            data = buffer.tobytes()
            total_packets = (len(data) + MTU_SIZE - 1) // MTU_SIZE

            # Отправляем все пакеты кадра
            for i in range(total_packets):
                start = i * MTU_SIZE
                end = start + MTU_SIZE
                chunk = data[start:end]

                # Собираем заголовок:
                # 4 байта - номер кадра, 2 - номер пакета, 2 - всего пакетов
                header = (
                    packet_seq.to_bytes(4, 'big') +
                    i.to_bytes(2, 'big') +
                    total_packets.to_bytes(2, 'big')
                )
                sock.sendto(header + chunk, server_address)

            packet_seq = (packet_seq + 1) % 2**32  # Чтобы не переполнилось
            time.sleep(DELAY)

    except Exception as e:
        logging.error(f"Ошибка отправки: {e}")
    finally:
        sock.close()

# Запуск всего хозяйства
if __name__ == "__main__":
    # Получаем данные для подключения
    connect = input("Сервак кормушек, формат: ip:port: ").strip()
    try:
        ip, port_str = connect.split(':')
        port = int(port_str)
    except:
        logging.error("Неправильный формат! Пример: 192.168.1.10:50005")
        sys.exit(1)

    # Запускаем все потоки
    threads = [
        threading.Thread(target=get_time, daemon=True),
        threading.Thread(target=get_video, daemon=True),
        threading.Thread(target=send_video, args=(ip, port), daemon=True)
    ]

    for t in threads:
        t.start()

    # Ждем завершения (или Ctrl+C)
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Выключаемся...")
        sys.exit(0)