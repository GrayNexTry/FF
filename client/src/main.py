import cv2
import sys
import socket

connect = input("Введите (ip:port): ")

try:
    ip, port = connect.strip().split(':')
    server_address = (ip, int(port))
except ValueError:
    print("Неправильный формат IP-адреса или порта.")
    sys.exit()

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

cap = cv2.VideoCapture(0)

MTU_SIZE = 1400
PACKET_SEQ = 0

while True:
    ret, frame = cap.read()
    if not ret:
        break
    
    encoded, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 50])

        # Разбиение буфера на пакеты
    data = buffer.tobytes()
    total_packets = len(data) // MTU_SIZE + (1 if len(data) % MTU_SIZE else 0)

    for i in range(total_packets):
        start = i * MTU_SIZE
        end = start + MTU_SIZE
        packet = data[start:end]

            # Добавление заголовка с номером последовательности
        header = PACKET_SEQ.to_bytes(4, 'big') + i.to_bytes(2, 'big') + total_packets.to_bytes(2, 'big')

        s.sendto(header + packet, server_address)

    PACKET_SEQ = (PACKET_SEQ + 1) % 2**32
    
