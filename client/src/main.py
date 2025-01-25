import cv2
import socket
import threading
import sys
from config import MTU_SIZE, ID_DEVICE

# Константы
JPEG_QUALITY = 50

# Функция для отправки кадров по UDP
def send_video(ip, port):
    try:
        server_address = (ip, int(port))
    except ValueError:
        print("\u2717 Неправильный формат IP-адреса или порта.")
        sys.exit(1)

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        cap = cv2.VideoCapture(0)

        if not cap.isOpened():
            print("\u2717 Не удалось открыть камеру.")
            sys.exit(1)

        packet_seq = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                print("\u2717 Не удалось считать кадр с камеры.")
                break

            # Кодирование кадра в JPEG
            success, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            if not success:
                print("\u2717 Ошибка при кодировании кадра.")
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
    
    except Exception as e:
        print(f"\u2717 Произошла ошибка: {e}")
    finally:
        cap.release()
        s.close()

# Функция для дополнительного потока
def another_task():
    try:
        while True:
            print("\u2714 Работает другой поток...")
            threading.Event().wait(5)
    except Exception as e:
        print(f"\u2717 Ошибка в дополнительном потоке: {e}")

if __name__ == "__main__":
    # Получение IP и порта от пользователя
    connect = input("Введите (ip:port): ")

    try:
        ip, port = connect.strip().split(':')
        port = int(port)
    except ValueError:
        print("\u2717 Неправильный формат IP-адреса или порта.")
        sys.exit(1)

    # Создание потоков
    try:
        video_thread = threading.Thread(target=send_video, args=(ip, port), daemon=True)
        additional_thread = threading.Thread(target=another_task, daemon=True)

        # Запуск потоков
        video_thread.start()
        additional_thread.start()

        # Ожидание завершения потоков
        video_thread.join()
        additional_thread.join()
    except KeyboardInterrupt:
        print("\n\u2714 Завершение работы...")
        sys.exit(0)
    except Exception as e:
        print(f"\u2717 Непредвиденная ошибка: {e}")
        sys.exit(1)
