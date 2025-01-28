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

# Функция для отправки кадров по UDP
def send_video(ip, port):
    try:
        server_address = (ip, int(port))
    except ValueError:
        logging.error("Неправильный формат IP-адреса или порта.")
        sys.exit(1)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(5)
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            logging.error("Не удалось открыть камеру.")
            sys.exit(1)
        packet_seq = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                logging.error("Не удалось считать кадр с камеры.")
                break
            # Кодирование кадра в JPEG
            success, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
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
        cap.release()
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
        video_thread = threading.Thread(target=send_video, args=(ip, port), daemon=True)
        # additional_thread = threading.Thread(target=another_task, daemon=True)
        # Запуск потоков
        video_thread.start()
        # additional_thread.start()
        # Ожидание завершения потоков
        video_thread.join()
        # additional_thread.join()
    except KeyboardInterrupt:
        logging.info("\nЗавершение работы...")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Непредвиденная ошибка: {e}")
        sys.exit(1)