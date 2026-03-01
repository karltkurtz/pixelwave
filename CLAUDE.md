# PixelWave — Claude Code Context

## Project Overview
PixelWave is an interactive LED art board hosted at **pigarage.com**. Visitors can draw pixel art on a 16x16 WS2812B LED matrix via a web interface. A Raspberry Pi HQ Camera streams a live view of the physical board. The project combines hardware control, real-time WebSocket communication, and a polished retro-themed web interface.

## Hardware
- **Main Pi:** Raspberry Pi 4 at `10.0.0.81` (hostname: `litebrite`) — runs FastAPI server, controls LEDs
- **Camera Pi:** Raspberry Pi at `10.0.0.8` (hostname: `camera`) — dedicated camera server on port 8080
- **SSH (main):** `ssh -i ~/.ssh/pixelwave_key karltkurtz@10.0.0.81`
- **SSH (camera):** `ssh -i ~/.ssh/pixelwave_key karltkurtz@10.0.0.8`
- **LED Matrix:** 16x16 WS2812B (256 LEDs), snake indexed, GPIO 18, **physically mounted 90° CCW**
- **Camera:** Raspberry Pi HQ Camera (IMX477, 12.3MP) + 16mm telephoto lens (on camera Pi)
- **PSU:** ALITOVE 5V 10A
- **LED Brightness:** Capped at 102/255 (~40%) for PSU safety

## Live Site
- **Main:** https://pigarage.com
- **Admin:** https://pigarage.com/admin (password: `litebrite123`)
- **Stream:** https://pigarage.com/snapshot
- **Tunnel:** Cloudflare Tunnel (cloudflared service)

## Tech Stack
- **Backend:** FastAPI (Python) — `main.py`
- **Frontend:** Vanilla HTML/CSS/JS
- **WebSockets:** Real-time LED state sync between all clients
- **LED Control:** `rpi_ws281x` library
- **Camera:** Dedicated camera Pi (`10.0.0.8:8080`) serves JPEG snapshots via Python BaseHTTP. Main Pi polls it in a background thread using `urllib.request` every 100ms and caches the latest frame. `/snapshot` serves from cache.
- **Serving:** uvicorn via systemd service (`litebrite.service`)

## File Structure
```
pixelwave/
├── main.py                  # FastAPI server, WebSocket, LED control, camera proxy
├── stream.py                # Camera Pi server — snapshot serving + camera controls (runs on 10.0.0.8)
├── static/
│   ├── index.html           # Main page — live stream, draw overlay, board status
│   ├── style.css            # All CSS (extracted from index.html)
│   ├── templates.js         # Pixel art template data and colors (extracted)
│   ├── about.html           # About page
│   ├── artwork.html         # Past artwork gallery
│   ├── guestbook.html       # Guestbook
│   ├── donate.html          # Donate page
│   └── admin.html           # Admin panel (camera controls, home status)
├── artwork_history.json     # Persisted artwork history
├── board_state.json         # Current board state
├── visitors.json            # Visitor count data
└── guestbook.json           # Guestbook entries
```

## Deployment Workflow
1. Make changes on Mac in `/Users/karlkurtz/Documents/programs/pixelwave`
2. `git push origin master` from Mac
3. On Pi: `cd ~/litebrite && git pull && sudo systemctl restart litebrite`

## Deploy & Commit Workflow
After every code change:
1. **SCP changed files to the Pi** and restart the server:
   ```
   scp -i ~/.ssh/pixelwave_key <file> karltkurtz@10.0.0.81:~/litebrite/<path>
   ssh -i ~/.ssh/pixelwave_key karltkurtz@10.0.0.81 "sudo systemctl restart litebrite"
   ```
2. **Wait 10 seconds**, then **open pigarage.com in a Safari Private Window** so Karl can review:
   ```
   sleep 10 && osascript -e 'tell application "Safari"' -e 'activate' -e 'tell application "System Events" to keystroke "n" using {command down, shift down}' -e 'delay 1' -e 'tell front window to set current tab to (make new tab with properties {URL:"https://www.pigarage.com"})' -e 'end tell'
   ```
3. **Do NOT commit** until Karl confirms it looks good.
4. When Karl says **"commit"**, then run:
   ```
   git add <changed files>
   git commit -m "<relevant description>"
   git push origin master
   ```

## Systemd Services
- **Main app (main Pi):** `sudo systemctl restart litebrite`
- **Cloudflare tunnel (main Pi):** `sudo systemctl restart cloudflared`
- **Camera server (camera Pi):** `nohup python3 ~/stream.py > ~/stream.log 2>&1 &` — restart with: `ssh -i ~/.ssh/pixelwave_key karltkurtz@10.0.0.8 "sudo kill \$(sudo ss -tlnp | grep 8080 | grep -oP 'pid=\K[0-9]+') 2>/dev/null; sleep 1; nohup python3 ~/stream.py > ~/stream.log 2>&1 &"`

## Key Technical Details

### Snake Index Remapping
The 16x16 matrix uses snake wiring AND is physically mounted 90° CCW. Coordinates are pre-rotated 90° CW before applying even-row reversal:
```python
def snake_index(index: int) -> int:
    row = index // 16
    col = index % 16
    # Pre-rotate 90° CW to compensate for physical 90° CCW mounting
    new_row = col
    new_col = 15 - row
    if new_row % 2 == 0:
        new_col = 15 - new_col
    return new_row * 16 + new_col
```

### Camera
- Runs on dedicated camera Pi at `10.0.0.8:8080` (Python BaseHTTP server, single-threaded)
- Main Pi `camera_fetch_loop()` polls camera Pi every 100ms via `urllib.request`, stores frame in `latest_frame`
- `/snapshot` endpoint serves from `latest_frame` (no per-request fan-out to camera Pi)
- Snapshot polling in JS every 150ms (~6-7fps delivery)
- **Watch out:** camera Pi's BaseHTTP server is single-threaded — never make concurrent requests to it directly. Always go through the main Pi's cached `/snapshot`.
- Camera controls in `/admin/camera` are forwarded to `POST http://10.0.0.8:8080/controls` which calls `picam2.set_controls()`
- Deploy to camera Pi: `scp -i ~/.ssh/pixelwave_key stream.py karltkurtz@10.0.0.8:~/stream.py` then restart (see Systemd Services)

### WebSocket Flow
- All clients connect to `/ws`
- Session system: one active user at a time, 300s duration, 10s claim window
- Messages: `init`, `led_update`, `session_start`, `session_end`, `claim_window`, `finish`, `visitor_count`

### LED Brightness
- Current default: 15/255
- Max allowed via slider: 102/255 (~40%) — PSU safety limit
- User-facing slider shows 0-100% but maps to 0-102 internally

### CSS Cache Busting
CSS and JS files use version query params:
- `style.css?v=6`
- `templates.js?v=4`
Bump these when making CSS/JS changes to force browser refresh.

## Pixel Art Templates
Located in `static/templates.js`. Categories:
- **Gaming:** Mario, Batman, Pac-Man, Invader, Among Us, Pokéball, Creeper, Tetris, Kirby, Pikachu, Ghost
- **Pop Culture:** Vader, Stormtrooper, Skull, Yoda, R2-D2, Iron Man, Cap Shield, Thanos
- **Expressions:** Heart, Smiley
- **Animals:** (coming soon)
- **Holiday:** 12 date-gated templates (Pumpkin, Turkey, Snowflake, Christmas Tree, Santa, Fireworks, Easter Bunny, Valentine Heart, Shamrock, Harvest Moon, Menorah, New Year's Ball)

## Current Todo List
- YouTube Live streaming
- Tweak 3D viewport orbiting and panning (disabled, revisit after matrix upgrade)
- Fill tool
- A "how to use" tooltip or mini guide for first-time visitors
- Allow visitors to vote/react to current drawing with emojis (👍❤️🔥)
- Add Animals pixel art templates
- Add sound effects — soft click when painting, chime when finishing
- Show live count of how many people are currently watching
- ANIMATE button (animations: Matrix, Rainbow Wave, Twinkle, Fire, Police Lights) — built but disabled (under construction) pending polish
- Site polish

## Known Issues
- Cloudflare Tunnel drops persistent MJPEG streams after ~30s — using snapshot polling instead

## Recently Completed
- **Camera Pi migration:** Moved camera from main Pi to dedicated Pi at `10.0.0.8:8080`. Fixed livestream by replacing per-request httpx proxy (overwhelmed single-threaded camera server) with background cache thread using `urllib.request`.
- **LED orientation fix:** Physical matrix is mounted 90° CCW — fixed `snake_index()` to pre-rotate coordinates 90° CW before applying snake wiring. Affects all LED operations.
- Admin page: added ← BACK TO LIVE STREAM nav link
- Admin page: added password-protected CLEAR ARTWORK and CLEAR GUESTBOOK buttons
- `POST /leds/batch` endpoint: sets multiple LEDs in one `strip.show()` call (used by animations)
- Visitor footer redesigned: two lines — total visits + "Most recent visit from [location]"
- Main page layout reordered: nav buttons and past artwork link moved below live stream and artboard section
- Added spacing between USE THE ARTBOARD button and nav buttons
- DONE button on draw overlay hidden until user claims the artboard
- DONE popup: replaced CANCEL with NOT DONE button
- Mobile fix: set finish name input font-size to 16px to prevent iOS Safari auto-zoom

## Instagram
- Handle: `@Pi_Garage`
- Email: `PiGarageLab@gmail.com`
