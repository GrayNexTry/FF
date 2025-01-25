import cv2
import socket
import threading
import sys
import numpy as np

from config import MTU_SIZE, ID_DEVICE


# Функция для отправки кадров по UDP
def send_video(ip, port):
    try:
        server_address = (ip, int(port))
    except ValueError:
        print("Неправильный формат IP-адреса или порта.")
        sys.exit()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    cap = cv2.VideoCapture(0)  # Камера 0

    # Настройка кодека H.264
    fourcc = cv2.VideoWriter_fourcc(*'H264')
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = int(cap.get(cv2.CAP_PROP_FPS)) or 30  # Фиксируем FPS для стабильности

    # Создание видеопотока сжатия
    out = cv2.VideoWriter('appsrc ! videoconvert ! x264enc tune=zerolatency bitrate=500 speed-preset=superfast ! appsink',
                          fourcc, fps, (width, height))

    PACKET_SEQ = 0  # Номер последовательности пакетов

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Сжатие с использованием H.264
        out.write(frame)
        _, buffer = cv2.imencode('.h264', frame)

        data = buffer.tobytes()

        # Разбиение буфера на пакеты
        total_packets = len(data) // MTU_SIZE + (1 if len(data) % MTU_SIZE else 0)

        for i in range(total_packets):
            start = i * MTU_SIZE
            end = start + MTU_SIZE
            packet = data[start:end]

            # Добавление заголовка с номером последовательности
            header = PACKET_SEQ.to_bytes(4, 'big') + i.to_bytes(2, 'big') + total_packets.to_bytes(2, 'big')
            s.sendto(header + packet, server_address)

        PACKET_SEQ = (PACKET_SEQ + 1) % 2**32

    cap.release()
    out.release()
    s.close()


# Функция для дополнительного потока
def another_task():
    while True:
        # Пример задачи
        print("Работает другой поток...")
        threading.Event().wait(5)  # Задержка для примера


if __name__ == "__main__":
    # Получение IP и порта от пользователя
    connect = input("Введите (ip:port): ")

    try:
        ip, port = connect.strip().split(':')
    except ValueError:
        print("Неправильный формат IP-адреса или порта.")
        sys.exit()

    # Создание потоков
    video_thread = threading.Thread(target=send_video, args=(ip, port), daemon=True)
    additional_thread = threading.Thread(target=another_task, daemon=True)

    # Запуск потоков
    video_thread.start()
    additional_thread.start()

    # Ожидание завершения потоков
    try:
        video_thread.join()
        additional_thread.join()
    except KeyboardInterrupt:
        print("Завершение работы...")
