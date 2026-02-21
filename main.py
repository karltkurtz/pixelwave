from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import time
import json
import os
import urllib.request
import urllib.parse

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

NUM_LEDS = 180
BOARD_FILE = "board_state.json"
SHOUTOUT_FILE = "shoutout.json"
GUESTBOOK_FILE = "guestbook.json"
CLAIM_WINDOW = 10
ADMIN_PASSWORD = "litebrite123"
NTFY_TOPIC = "theledboard-notify"

def load_board():
    if os.path.exists(BOARD_FILE):
        with open(BOARD_FILE) as f:
            return json.load(f)
    return [{"r": 0, "g": 0, "b": 0} for _ in range(NUM_LEDS)]

def save_board():
    with open(BOARD_FILE, "w") as f:
        json.dump(board_state, f)

def load_shoutout():
    if os.path.exists(SHOUTOUT_FILE):
        with open(SHOUTOUT_FILE) as f:
            return json.load(f)
    return {"name": None, "amount": None, "label": None, "time": None}

def save_shoutout():
    with open(SHOUTOUT_FILE, "w") as f:
        json.dump(shoutout, f)

def load_guestbook():
    if os.path.exists(GUESTBOOK_FILE):
        with open(GUESTBOOK_FILE) as f:
            return json.load(f)
    return []

def save_guestbook():
    with open(GUESTBOOK_FILE, "w") as f:
        json.dump(guestbook, f)

board_state = load_board()

session = {
    "active": False,
    "user_id": None,
    "start_time": None,
    "duration": 300,
    "claim_window": False,
    "claim_window_end": None,
    "artist_name": None,
    "location": None
}

home_status = {"home": False}

session_history = []

shoutout = load_shoutout()

guestbook = load_guestbook()

def save_session(duration_seconds, board_snapshot, name, location="Unknown"):
    session_history.append({
        "ended_at": time.time(),
        "duration": duration_seconds,
        "board": board_snapshot,
        "name": name,
        "location": location
    })
    if len(session_history) > 10:
        session_history.pop(0)

clients = set()

try:
    import rpi_ws281x as ws281x
    LED_PIN = 18
    LED_FREQ_HZ = 800000
    LED_DMA = 10
    LED_BRIGHTNESS = 15
    LED_INVERT = False
    LED_CHANNEL = 0
    strip = ws281x.PixelStrip(NUM_LEDS, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
    strip.begin()
    HAS_LEDS = True
except Exception as e:
    print(f"LED hardware not available: {e}")
    HAS_LEDS = False

def set_physical_led(index: int, r: int, g: int, b: int):
    if HAS_LEDS:
        strip.setPixelColor(index, ws281x.Color(r, g, b))
        strip.show()

def clear_physical_leds():
    if HAS_LEDS:
        for i in range(NUM_LEDS):
            strip.setPixelColor(i, ws281x.Color(0, 0, 0))
        strip.show()

def boot_animation():
    if not HAS_LEDS:
        return
    for _ in range(6):
        for i in range(NUM_LEDS):
            strip.setPixelColor(i, ws281x.Color(0, 0, 30))
        strip.show()
        time.sleep(0.4)
        for i in range(NUM_LEDS):
            strip.setPixelColor(i, ws281x.Color(0, 0, 0))
        strip.show()
        time.sleep(0.4)
    clear_physical_leds()

async def broadcast(message: dict):
    disconnected = set()
    for client in clients:
        try:
            await client.send_json(message)
        except:
            disconnected.add(client)
    clients.difference_update(disconnected)

async def end_session(reason: str):
    duration = int(time.time() - session["start_time"]) if session["start_time"] else 0
    name = session.get("artist_name", "Anonymous")
    save_session(duration, list(board_state), name, session.get("location", "Unknown"))
    await broadcast({"type": "last_session", "ended_at": session_history[-1]["ended_at"], "duration": duration, "name": name, "location": session_history[-1].get("location", "Unknown")})
    session["active"] = False
    session["user_id"] = None
    session["start_time"] = None
    session["artist_name"] = None
    session["location"] = None
    session["claim_window"] = True
    session["claim_window_end"] = time.time() + CLAIM_WINDOW
    await broadcast({"type": "session_end", "reason": reason})
    await broadcast({"type": "claim_window", "seconds": CLAIM_WINDOW})
    try:
        mins = duration // 60
        secs = duration % 60
        duration_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
        msg = f"{name} just finished drawing on The LED Board! (drew for {duration_str})"
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=msg.encode("utf-8"),
            headers={"Title": "New artwork on The LED Board!", "Priority": "default"}
        )
        urllib.request.urlopen(req, timeout=5)
    except:
        pass

async def session_timer():
    while True:
        await asyncio.sleep(1)
        if session["active"] and session["start_time"]:
            elapsed = time.time() - session["start_time"]
            remaining = int(session["duration"] - elapsed)
            if remaining <= 0:
                await end_session("timeout")
            else:
                await broadcast({"type": "timer", "remaining": remaining})

        if session["claim_window"] and session["claim_window_end"]:
            remaining = int(session["claim_window_end"] - time.time())
            if remaining <= 0:
                session["claim_window"] = False
                session["claim_window_end"] = None
                await broadcast({"type": "claim_window_end"})
            else:
                await broadcast({"type": "claim_window_tick", "seconds": remaining})

@app.on_event("startup")
async def startup_event():
    boot_animation()
    asyncio.create_task(session_timer())

@app.get("/")
async def root():
    with open("static/index.html") as f:
        content = f.read()
    return HTMLResponse(content, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache"
    })

@app.get("/donate")
async def donate():
    with open("static/donate.html") as f:
        content = f.read()
    return HTMLResponse(content, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache"
    })

@app.get("/guestbook")
async def guestbook_page():
    with open("static/guestbook.html") as f:
        content = f.read()
    return HTMLResponse(content, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache"
    })

@app.post("/guestbook")
async def post_guestbook(payload: dict, request: Request):
    name = payload.get("name", "Anonymous").strip() or "Anonymous"
    message = payload.get("message", "").strip()
    if not message:
        return {"error": "message required"}
    ip = request.headers.get("x-forwarded-for", request.client.host)
    location = "Unknown"
    try:
        with urllib.request.urlopen(f"http://ip-api.com/json/{ip}?fields=city,regionName,country", timeout=3) as r:
            geo = json.loads(r.read())
            if geo.get("city"):
                location = f"{geo['city']}, {geo['regionName']}, {geo['country']}"
            elif geo.get("country"):
                location = geo["country"]
    except:
        pass
    entry = {
        "name": name,
        "message": message,
        "time": time.time(),
        "location": location
    }
    guestbook.insert(0, entry)
    if len(guestbook) > 100:
        guestbook.pop()
    save_guestbook()
    return {"status": "ok"}

@app.get("/guestbook/entries")
async def get_guestbook():
    return guestbook

@app.get("/test-notify")
async def test_notify():
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data="Test notification from The LED Board!".encode("utf-8"),
            headers={"Title": "Test!", "Priority": "default"}
        )
        urllib.request.urlopen(req, timeout=5)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
    
@app.post("/shoutout")
async def post_shoutout(payload: dict):
    shoutout["name"] = payload.get("name", "Anonymous")
    shoutout["amount"] = payload.get("amount")
    shoutout["label"] = payload.get("label", "a generous amount")
    shoutout["time"] = time.time()
    save_shoutout()
    await broadcast({"type": "shoutout", "name": shoutout["name"], "label": shoutout["label"]})
    return {"status": "ok"}

@app.post("/admin/home")
async def set_home(payload: dict):
    if payload.get("password") != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")
    home_status["home"] = payload.get("home", False)
    await broadcast({"type": "home_status", "home": home_status["home"]})
    return {"status": "ok", "home": home_status["home"]}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    user_id = id(websocket)

    await websocket.send_json({
        "type": "init",
        "board": board_state,
        "session": {"active": session["active"]},
        "home": home_status["home"],
        "last_session": session_history[-1] if session_history else None,
        "shoutout": shoutout if shoutout["name"] else None
    })

    try:
        while True:
            data = await websocket.receive_json()

            if data["type"] == "claim":
                if not session["active"] and not session["claim_window"]:
                    session["active"] = True
                    session["user_id"] = user_id
                    session["start_time"] = time.time()
                    session["artist_name"] = data.get("name", "Anonymous")
                    ip = websocket.headers.get("x-forwarded-for", websocket.client.host)
                    location = "Unknown"
                    try:
                        with urllib.request.urlopen(f"http://ip-api.com/json/{ip}?fields=city,regionName,country", timeout=3) as r:
                            geo = json.loads(r.read())
                            if geo.get("city"):
                                location = f"{geo['city']}, {geo['regionName']}, {geo['country']}"
                            elif geo.get("country"):
                                location = geo["country"]
                    except:
                        pass
                    session["location"] = location
                    for client in clients:
                        try:
                            await client.send_json({
                                "type": "session_start",
                                "is_you": id(client) == user_id
                            })
                        except:
                            pass

            elif data["type"] == "finish":
                if session["user_id"] == user_id:
                    await end_session("finished")

    except WebSocketDisconnect:
        clients.discard(websocket)
        if session["user_id"] == user_id:
            await end_session("disconnected")

@app.post("/led/{index}")
async def set_led(index: int, color: dict):
    if not session["active"]:
        return {"error": "no active session"}
    if index < 0 or index >= NUM_LEDS:
        return {"error": "invalid index"}
    board_state[index] = color
    save_board()
    set_physical_led(index, color["r"], color["g"], color["b"])
    await broadcast({
        "type": "led_update",
        "index": index,
        "color": color
    })
    return {"status": "ok"}

@app.post("/clear")
async def clear_board():
    global board_state
    board_state = [{"r": 0, "g": 0, "b": 0} for _ in range(NUM_LEDS)]
    save_board()
    clear_physical_leds()
    await broadcast({"type": "clear"})
    return {"status": "ok"}
