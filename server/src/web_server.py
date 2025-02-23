import time
import os
import logging
from fastapi import FastAPI, Response, Request, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from config import TIMEOUT, FPS
from typing import List
import asyncio

# Первоначальная настройка
app = FastAPI()

# log = logging.getLogger('uvicorn')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

# Константы1
_FRAME_DELAY = 1/FPS

# Шаблоны
templates = Jinja2Templates(directory="FF/server/src/templates")

# Общедоступные
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    server = app.state.server
    if not server:
        raise HTTPException(status_code=500, detail="Server not initialized")
    with server.clients_lock:
        client_list = [f"{addr[0]}:{addr[1]}" for addr in server.clients]
    return templates.TemplateResponse("index.html", {"request": request, "clients": client_list})

# Получение ip,port всех онлайн клиентов (json)
@app.get("/clients", response_model=List[List[str]])
async def get_clients():
    server = app.state.server
    if not server:
        raise HTTPException(status_code=500)
    with server.clients_lock:
        client_list = [[addr[0], str(addr[1])] for addr in server.clients]
    return client_list

# Получение количества онлайн клиентов (json)
@app.get("/number_clients")
async def get_number_clients():
    server = app.state.server
    if not server:
        raise HTTPException(status_code=500)
    with server.clients_lock:
        count = len(server.clients)
    return {"count": count}

# Получение скрина в момент времени клиента (jpg)
@app.get("/screenshot/{client_id}")
async def screenshot(client_id: str):
    server = app.state.server
    if not server:
        raise HTTPException(status_code=500)
    try:
        ip, port = client_id.rsplit(':', 1)
        client_addr = (ip, int(port))
    except ValueError:
        raise HTTPException(status_code=404)

    with server.clients_lock:
        if client_addr not in server.clients:
            raise HTTPException(status_code=404)

    with server.frames_lock:
        jpeg_data = server.frames.get(client_addr)
        if not jpeg_data:
            raise HTTPException(status_code=500)

    return Response(content=jpeg_data, media_type="image/jpeg")

# Потоковая передача видео для конкретного клиента (jpg's)
@app.get("/video/{client_id}")
async def video_feed(client_id: str):
    server = app.state.server
    if not server:
        raise HTTPException(status_code=500)
    try:
        ip, port = client_id.rsplit(':', 1)
        client_addr = (ip, int(port))
    except ValueError:
        raise HTTPException(status_code=404)

    with server.clients_lock:
        if client_addr not in server.clients:
            raise HTTPException(status_code=404)

    async def generate():
        next_frame_time = time.time()
        while client_addr in server.clients:
            with server.frames_lock:
                jpeg_data = server.frames.get(client_addr)
                if jpeg_data:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n'
                           + jpeg_data + b'\r\n')
            next_frame_time += _FRAME_DELAY
            sleep_time = next_frame_time - time.time()
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")

# Поток событий
@app.get("/stream")
async def stream():
    server = app.state.server
    if not server:
        raise HTTPException(status_code=500)

    async def event_stream():
        while True:
            with server.clients_lock:
                client_list = [f"{addr[0]}:{addr[1]}" for addr in server.clients]
            data = ','.join(client_list) if client_list else "empty"
            yield f"data: {data}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")