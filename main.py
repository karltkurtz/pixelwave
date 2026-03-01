from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import time
import json
import os
import urllib.request
import urllib.parse

app = FastAPI()

# Camera stream — fetched from camera Pi at 10.0.0.8
import threading

CAMERA_PI_URL = "http://10.0.0.8:8080/?action=snapshot"
latest_frame = None
frame_lock = threading.Lock()

def camera_fetch_loop():
    global latest_frame
    while True:
        try:
            with urllib.request.urlopen(CAMERA_PI_URL, timeout=3) as resp:
                data = resp.read()
            with frame_lock:
                latest_frame = data
        except Exception:
            pass
        time.sleep(0.1)

cam_thread = threading.Thread(target=camera_fetch_loop, daemon=True)
cam_thread.start()

@app.post("/brightness")
async def set_brightness(request: Request):
    data = await request.json()
    level = int(data.get("level", 15))
    level = max(1, min(102, level))
    if HAS_LEDS:
        strip.setBrightness(level)
        strip.show()
    return {"brightness": level}

@app.get("/snapshot")
async def snapshot():
    with frame_lock:
        frame = latest_frame
    if frame is None:
        return Response(status_code=503)
    return Response(content=frame, media_type="image/jpeg", headers={
        "Cache-Control": "no-cache, no-store",
        "Access-Control-Allow-Origin": "*"
    })
app.mount("/static", StaticFiles(directory="static"), name="static")

NUM_LEDS = 256
BOARD_FILE = "board_state.json"
SHOUTOUT_FILE = "shoutout.json"
GUESTBOOK_FILE = "guestbook.json"
ARTWORK_FILE = "artwork_history.json"
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

def load_artwork():
    if os.path.exists(ARTWORK_FILE):
        with open(ARTWORK_FILE) as f:
            return json.load(f)
    return []

def save_artwork():
    with open(ARTWORK_FILE, "w") as f:
        json.dump(artwork_history, f)

board_state = load_board()

# Visitor tracking
VISITORS_FILE = "visitors.json"

def load_visitors():
    if os.path.exists(VISITORS_FILE):
        with open(VISITORS_FILE) as f:
            data = json.load(f)
            if "recent_locations" not in data:
                data["recent_locations"] = []
            return data
    return {"total": 0, "unique_ips": [], "recent_locations": []}

def save_visitors():
    with open(VISITORS_FILE, "w") as f:
        json.dump(visitors, f)

visitors = load_visitors()

anim_task = None
anim_running = False

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
artwork_history = load_artwork()

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

def snake_index(index: int) -> int:
    row = index // 16
    col = index % 16
    if row % 2 == 0:
        col = 15 - col
    return row * 16 + col

def set_physical_led(index: int, r: int, g: int, b: int):
    if HAS_LEDS:
        strip.setPixelColor(snake_index(index), ws281x.Color(r, g, b))
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

async def run_server_anim():
    global anim_running
    offset = 0
    while anim_running:
        for i in range(NUM_LEDS):
            hue = ((i / NUM_LEDS) * 360 + offset) % 360
            r, g, b = hsl_to_rgb(hue / 360)
            board_state[i] = {"r": r, "g": g, "b": b}
            set_physical_led(i, r, g, b)
        await broadcast({"type": "clear"})
        await broadcast({"type": "init", "board": board_state, "session": {"active": False}, "home": home_status["home"], "last_session": session_history[-1] if session_history else None, "shoutout": shoutout if shoutout["name"] else None})
        offset = (offset + 10) % 360
        await asyncio.sleep(0.15)

def hsl_to_rgb(h):
    import colorsys
    r, g, b = colorsys.hls_to_rgb(h, 0.5, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)    

async def end_session(reason: str, keep_anim: bool = False):
    global anim_task, anim_running
    duration = int(time.time() - session["start_time"]) if session["start_time"] else 0
    if keep_anim:
        anim_running = True
        anim_task = asyncio.create_task(run_server_anim())
    name = session.get("artist_name", "Anonymous")
    location = session.get("location", "Unknown")
    save_session(duration, list(board_state), name, location)
    if any(c["r"] > 0 or c["g"] > 0 or c["b"] > 0 for c in board_state):
        artwork_history.insert(0, {
            "board": list(board_state),
            "name": name,
            "location": location,
            "time": time.time(),
            "duration": duration
        })
        if len(artwork_history) > 5:
            artwork_history.pop()
        save_artwork()
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

def get_location(ip):
    try:
        if ip in ("127.0.0.1", "localhost") or ip.startswith("10.") or ip.startswith("192.168."):
            return None
        url = f"http://ip-api.com/json/{ip}?fields=city,country,status"
        with urllib.request.urlopen(url, timeout=2) as res:
            data = json.loads(res.read())
            if data.get("status") == "success":
                city = data.get("city", "")
                country = data.get("country", "")
                if city and country:
                    return f"{city}, {country}"
                elif country:
                    return country
    except Exception:
        pass
    return None

@app.get("/")
async def root(request: Request):
    ip = request.headers.get("x-forwarded-for", request.client.host).split(",")[0].strip()
    visitors["total"] += 1
    is_new = ip not in visitors["unique_ips"]
    if is_new:
        visitors["unique_ips"].append(ip)
        location = await asyncio.get_event_loop().run_in_executor(None, get_location, ip)
        if location and location not in visitors["recent_locations"]:
            visitors["recent_locations"].insert(0, location)
            visitors["recent_locations"] = visitors["recent_locations"][:5]
    save_visitors()
    await broadcast({
        "type": "visitor_count",
        "total": visitors["total"],
        "unique": len(visitors["unique_ips"]),
        "locations": visitors["recent_locations"]
    })
    with open("static/index.html") as f:
        content = f.read()
    return HTMLResponse(content, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache"
    })

@app.get("/visitors")
async def get_visitors():
    return {
        "total": visitors["total"],
        "unique": len(visitors["unique_ips"]),
        "locations": visitors["recent_locations"]
    }

@app.get("/donate")
async def donate():
    with open("static/donate.html") as f:
        content = f.read()
    return HTMLResponse(content, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache"
    })

@app.get("/artwork")
async def artwork_page():
    with open("static/artwork.html") as f:
        content = f.read()
    return HTMLResponse(content, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache"
    })

@app.get("/artwork/entries")
async def get_artwork():
    return artwork_history

@app.get("/about")
async def about():
    with open("static/about.html") as f:
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
    try:
        notif_url = "https://ntfy.sh/pigarage-guestbook"
        notif_data = f"{name} from {location} signed the guestbook: {message}"
        req = urllib.request.Request(notif_url, data=notif_data.encode(), method="POST")
        urllib.request.urlopen(req, timeout=3)
    except:
        pass
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
    
@app.get("/shoutout/latest")
async def get_shoutout():
    return shoutout if shoutout["name"] else {}
    
@app.post("/shoutout")
async def post_shoutout(payload: dict):
    shoutout["name"] = payload.get("name", "Anonymous")
    shoutout["amount"] = payload.get("amount")
    shoutout["label"] = payload.get("label", "a generous amount")
    shoutout["time"] = time.time()
    save_shoutout()
    await broadcast({"type": "shoutout", "name": shoutout["name"], "label": shoutout["label"]})
    return {"status": "ok"}

@app.post("/admin/camera")
async def set_camera(payload: dict):
    if payload.get("password") != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")
    controls = {}
    if "exposure" in payload:
        controls["AeEnable"] = False
        controls["ExposureTime"] = int(payload["exposure"])
    if "gain" in payload:
        controls["AnalogueGain"] = float(payload["gain"])
    if "brightness" in payload:
        controls["Brightness"] = float(payload["brightness"])
    if "contrast" in payload:
        controls["Contrast"] = float(payload["contrast"])
    if "saturation" in payload:
        controls["Saturation"] = float(payload["saturation"])
    if "auto" in payload and payload["auto"]:
        controls["AeEnable"] = True
        controls["AwbEnable"] = True
    # Camera controls not available (camera runs on separate Pi)
    return {"status": "ok"}

@app.get("/admin")
async def admin_page():
    with open("static/admin.html") as f:
        content = f.read()
    return HTMLResponse(content)

@app.post("/admin/home")
async def set_home(payload: dict):
    if payload.get("password") != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")
    home_status["home"] = payload.get("home", False)
    await broadcast({"type": "home_status", "home": home_status["home"]})
    return {"status": "ok", "home": home_status["home"]}

@app.post("/admin/artwork/clear")
async def clear_artwork(payload: dict):
    global artwork_history
    if payload.get("password") != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")
    artwork_history = []
    save_artwork()
    return {"status": "ok"}

@app.post("/admin/guestbook/clear")
async def clear_guestbook_entries(payload: dict):
    global guestbook
    if payload.get("password") != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")
    guestbook = []
    save_guestbook()
    return {"status": "ok"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    user_id = id(websocket)

    await websocket.send_json({
        "type": "init",
        "board": board_state,
        "session": {"active": session["active"]},
        "location": session.get("location", ""),
        "home": home_status["home"],
        "last_session": session_history[-1] if session_history else None,
        "shoutout": shoutout if shoutout["name"] else None
    })

    try:
        while True:
            data = await websocket.receive_json()

            if data["type"] == "claim":
                if not session["active"] and not session["claim_window"]:
                    global anim_task, anim_running
                    anim_running = False
                    if anim_task:
                        anim_task.cancel()
                        anim_task = None
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
                                "is_you": id(client) == user_id,
                                "location": location
                            })
                        except:
                            pass

            elif data["type"] == "finish":
                if session["user_id"] == user_id:
                    name = data.get("name", "Anonymous")
                    if name:
                        session["artist_name"] = name
                    keep = data.get("keep_anim", False)
                    await end_session("finished", keep_anim=keep)

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

@app.post("/leds/batch")
async def set_leds_batch(payload: dict):
    if not session["active"]:
        return {"error": "no active session"}
    leds = payload.get("leds", [])
    for led in leds:
        idx = led.get("index")
        if idx is not None and 0 <= idx < NUM_LEDS:
            board_state[idx] = {"r": led["r"], "g": led["g"], "b": led["b"]}
            if HAS_LEDS:
                strip.setPixelColor(snake_index(idx), ws281x.Color(led["r"], led["g"], led["b"]))
    if HAS_LEDS and leds:
        strip.show()
    return {"status": "ok"}

@app.post("/clear")
async def clear_board():
    global board_state
    board_state = [{"r": 0, "g": 0, "b": 0} for _ in range(NUM_LEDS)]
    save_board()
    clear_physical_leds()
    await broadcast({"type": "clear"})
    return {"status": "ok"}
