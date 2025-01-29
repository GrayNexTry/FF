import cv2
import socket
import threading
import sys
import time
import logging
from config import MTU_SIZE, ID_DEVICE, JPEG_QUALITY, FPS

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Интервал отправки кадров
DELAY = 1 / FPS

# Глобальные переменные для обмена данными между потоками
frame = None
frame_lock = threading.Lock()
ret = None
ret_lock = threading.Lock()
now_time = "None"
now_time_lock = threading.Lock()

def get_time():
    global now_time
    while True:
        t = time.localtime()
        now_time = time.strftime("%H:%M:%S", t)

        time.sleep(1)

def get_video():
    global frame, ret, now_time

    (text_width, text_height), baseline = cv2.getTextSize(f'{now_time}', cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    x = (640 - text_width) // 16
    y = (480 + text_height) // 16

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        logging.error("Не удалось открыть камеру.")
        sys.exit(1)
    while True:
        with ret_lock:
            ret, frame = cap.read()
            frame = cv2.putText(frame, f'{now_time}',(x,y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1, cv2.LINE_AA)
        if not ret:
            logging.error("Не удалось считать кадр с камеры.")
            break
        time.sleep(DELAY)  # Ограничение FPS

# Функция для отправки кадров по UDP
def send_video(ip, port):
    global frame, ret
    try:
        server_address = (ip, int(port))
    except ValueError:
        logging.error("Неправильный формат IP-адреса или порта.")
        sys.exit(1)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(5)
        packet_seq = 0
        while True:
            with frame_lock:
                current_frame = frame
            if current_frame is None:
                continue
            # Кодирование кадра в JPEG
            success, buffer = cv2.imencode('.jpg', current_frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            if not success:
                logging.error("Ошибка при кодировании кадра.")
                continue
            data = buffer.tobytes()
            # Разбиение буфера на пакеты
            total_packets = (len(data) + MTU_SIZE - 1) // MTU_SIZE
            for i in range(total_packets):
                start = i * MTU_SIZE
                end = start + MTU_SIZE
                packet = data[start:end]
                # Добавление заголовка с номером последовательности
                header = (
                    packet_seq.to_bytes(4, 'big') +
                    i.to_bytes(2, 'big') +
                    total_packets.to_bytes(2, 'big')
                )
                s.sendto(header + packet, server_address)
            packet_seq = (packet_seq + 1) % 2**32
            time.sleep(DELAY)  # Ограничение FPS
    except Exception as e:
        logging.error(f"Произошла ошибка: {e}")
    finally:
        s.close()

if __name__ == "__main__":
    # Получение IP и порта от пользователя
    connect = input("Введите (ip:port): ")
    try:
        ip, port = connect.strip().split(':')
        port = int(port)
    except ValueError:
        logging.error("Неправильный формат IP-адреса или порта.")
        sys.exit(1)
    # Создание потоков
    try:
        send_video_thread = threading.Thread(target=send_video, args=(ip, port), daemon=True)
        get_video_thread = threading.Thread(target=get_video, daemon=True)
        get_time_thread = threading.Thread(target=get_time, daemon=True)
        # Запуск потоков
        send_video_thread.start()
        get_video_thread.start()
        get_time_thread.start()
        # Ожидание завершения потоков
        send_video_thread.join()
        get_video_thread.join()
        get_time_thread.join()
    except KeyboardInterrupt:
        logging.info("\nЗавершение работы...")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Непредвиденная ошибка: {e}")
        sys.exit(1)