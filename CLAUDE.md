# PixelWave — Claude Code Context

## Project Overview
PixelWave is an interactive LED art board hosted at **pigarage.com**. Visitors can draw pixel art on a 16x16 WS2812B LED matrix via a web interface. A Raspberry Pi HQ Camera streams a live view of the physical board. The project combines hardware control, real-time WebSocket communication, and a polished retro-themed web interface.

## Hardware
- **Main Pi:** Raspberry Pi 4 at `10.0.0.81` (hostname: `litebrite`) — runs FastAPI server, controls LEDs
- **Camera Pi:** Raspberry Pi 4 at `10.0.0.8` (hostname: `camera`) — dedicated camera server on port 8080
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

## Deploy & Commit Workflow
After every code change:
1. **SCP to main Pi** and restart:
   ```
   scp -i ~/.ssh/pixelwave_key <file> karltkurtz@10.0.0.81:~/litebrite/<path>
   ssh -i ~/.ssh/pixelwave_key karltkurtz@10.0.0.81 "sudo systemctl restart litebrite"
   ```
   **SCP to camera Pi** (for `stream.py` only) and restart:
   ```
   scp -i ~/.ssh/pixelwave_key stream.py karltkurtz@10.0.0.8:~/stream.py
   ssh -i ~/.ssh/pixelwave_key karltkurtz@10.0.0.8 "sudo kill \$(sudo ss -tlnp | grep 8080 | grep -oP 'pid=\K[0-9]+') 2>/dev/null; sleep 1; nohup python3 ~/stream.py > ~/stream.log 2>&1 &"
   ```
   Note: `stream.py` lives at `~/stream.py` on the camera Pi (not inside `~/litebrite/`).
2. **Wait 5 seconds**, then **open pigarage.com in a Safari Private Window** so Karl can review:
   ```
   sleep 5 && osascript -e 'tell application "Safari"' -e 'activate' -e 'tell application "System Events" to keystroke "n" using {command down, shift down}' -e 'delay 0.5' -e 'set URL of current tab of front window to "https://www.pigarage.com"' -e 'end tell'
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
- Camera controls in `/admin/camera` are forwarded to `POST http://10.0.0.8:8080/controls`. MANUAL applies `set_controls()` with cam_lock. AUTO signals `auto_reset_event` so the capture loop fully recreates the Picamera2 instance (stop → close → new) for a guaranteed clean reset.
- Camera starts in AUTO mode by default on every boot
- Deploy to camera Pi: `scp -i ~/.ssh/pixelwave_key stream.py karltkurtz@10.0.0.8:~/stream.py` then restart (see Systemd Services)

### WebSocket Flow
- All clients connect to `/ws`
- Session system: one active user at a time, 300s duration, 10s claim window
- Messages: `init`, `led_update`, `session_start`, `session_end`, `claim_window`, `finish`, `visitor_count`

### LED Brightness
- Current default: slider `value=1` → sends level 1 to server → ~0.4% of hardware max (1/255)
- Displayed as 1% in the UI (formula: `value / 102 * 100`, hardcoded label on load)
- Max allowed via slider: 102/255 (~40%) — PSU safety limit
- User-facing slider shows 1–100% but maps to 1–102 internally

### CSS Cache Busting
CSS and JS files use version query params:
- `style.css?v=11`
- `templates.js?v=7`
Bump these when making CSS/JS changes to force browser refresh.

## Pixel Art Templates
Located in `static/templates.js`. Categories:
- **Gaming:** Mario, Batman, Pac-Man, Invader, Among Us, Pokéball, Creeper, Tetris, Kirby, Pikachu, Ghost
- **Pop Culture:** Vader, Stormtrooper, Skull, Yoda, R2-D2, Iron Man, Cap Shield, Thanos
- **Expressions:** Heart, Smiley, Cool, Wow, Angry
- **Animals:** Cat, Frog, Dog
- **Holiday:** 12 date-gated templates (Pumpkin, Turkey, Snowflake, Christmas Tree, Santa, Fireworks, Easter Bunny, Valentine Heart, Shamrock, Harvest Moon, Menorah, New Year's Ball)

## Current Todo List
- YouTube Live streaming
- Fill tool
- A "how to use" tooltip or mini guide for first-time visitors
- Allow visitors to vote/react to current drawing with emojis (👍❤️🔥)
- Add more pixel art templates (more Animals, more Expressions)
- Add sound effects — soft click when painting, chime when finishing

## Known Issues
- Cloudflare Tunnel drops persistent MJPEG streams after ~30s — using snapshot polling instead

## Recently Completed
- **Animations overhaul:** ANIMATE button renamed to ANIMATIONS and enabled. SURPRISE button removed. 13 total animations available via popup: The Matrix, Rainbow Wave, Twinkle, Fire, Police Lights, Game of Life, Ripple, Fireworks, Meteor Shower, Bubbles, Kaleidoscope, Clock, Pac-Man.
- **ANIMATIONS button sparkle effect:** 4 ✦/✧ sparkle characters twinkle around the button corners with staggered CSS keyframe timings. Pulsing amber glow (`animGlow` keyframe). Implemented via `.anim-sparkle-wrap` wrapper div (`::before`/`::after`) and `#anim-btn::before`/`::after`. Button sits in a `<div class="anim-sparkle-wrap">` inside the flex controls row.
- **Admin live stream preview:** `<img id="admin-stream">` added below camera controls card in `admin.html`. Polls `/snapshot?t=Date.now()` every 150ms (same pattern as main page). Lets Karl see camera setting changes take effect in real time.
- **Default brightness set to 1%** (slider `value=1`, label hardcoded `1%` on load).
- **Seasonal background animations:** Date-gated starfield themes — Christmas (falling pixelated snowflakes), Halloween (rising pixelated pumpkins with stem/eyes/mouth), Valentine's (pink rising pixels), default (colorful rising pixels). Bitmaps: `SNOWFLAKE` 5×5, `PUMPKIN` 6×5. Override line removed — production uses live date.
- **Site polish pass:** CLICK TO DRAW and DONE buttons animate with cycling color + glow (`claimColor` 10s keyframe: amber→teal→coral→green→purple). 3D VIEW button removed. Under construction banner removed.
- **Draw overlay UX:** "Artboard is free — Use it!" status text hidden. BOARD IN USE button hidden (`display:none`) instead of disabled/greyed.
- **Button layout:** Donate and Past Artwork button positions swapped on main page.
- **Open Graph / Twitter Card meta tags** added to index.html — image at `https://pigarage.com/static/og-image.png`.
- **Pixel art templates added:** Animals tab: Cat, Frog, Dog. Expressions tab: Cool (sunglasses), Wow (O-mouth), Angry (V-brows + frown).
- **About page updated:** Added Raspberry Pi 4 (camera) as a separate hardware entry; corrected matrix specs from 16x32/512 to 16x16/256.
- **Camera admin controls:** MANUAL/AUTO mode switching with greyed-out inactive button, sliders disabled in AUTO mode. AUTO does a full Picamera2 recreate for guaranteed clean AE reset.
- **Camera Pi migration:** Moved camera from main Pi to dedicated Pi at `10.0.0.8:8080`. Background cache thread using `urllib.request`.
- **LED orientation fix:** Physical matrix is mounted 90° CCW — fixed `snake_index()` to pre-rotate coordinates 90° CW.
- Admin page: ← BACK TO LIVE STREAM nav link, password-protected CLEAR ARTWORK and CLEAR GUESTBOOK buttons.
- `POST /leds/batch` endpoint: sets multiple LEDs in one `strip.show()` call (used by animations).
- Visitor footer redesigned: two lines — total visits + "Most recent visit from [location]".
- DONE popup: replaced CANCEL with NOT DONE button.
- Mobile fix: set finish name input font-size to 16px to prevent iOS Safari auto-zoom.

## Animation System Notes
- All animations use `runAnim(tickFn, intervalMs)` — sets `animRunning=true`, starts interval, sends batch LED updates via `POST /leds/batch`
- `stopAnim()` clears interval, sets `animRunning=false`, re-enables color picker
- CLEAR button stops any running animation (`clearBoard()` calls `stopAnim()` if `animRunning`)
- Starting a new animation via `runAnim` automatically cancels the previous one
- **Clock animation** checks every 500ms but only sends updates when time/colon state actually changes (key caching). Layout: digits at cols [0,3,9,12], colon at col 7, start row 6. Hours = amber, minutes = teal.
- **Pac-Man** runs on the 60-cell perimeter path (clockwise). Pac-Man moves every tick, ghost every 3rd tick. Ghost turns blue when within 5 positions ahead of Pac-Man; teleports to +30 when caught.
- **Bubbles** tracks `prevPixels` per bubble to clear exactly the old circle outline each tick (no full-board fade). Phase 1: clear all prevPixels. Phase 2: move + draw.
- **Meteor Shower** uses per-frame fade (multiply by 0.6) to create trailing effect. Meteors move diagonally top-right→bottom-left (dx=-1, dy=+1).

## Instagram
- Handle: `@Pi_Garage`
- Email: `PiGarageLab@gmail.com`
