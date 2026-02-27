# PixelWave — Claude Code Context

## Project Overview
PixelWave is an interactive LED art board hosted at **pigarage.com**. Visitors can draw pixel art on a 16x16 WS2812B LED matrix via a web interface. A Raspberry Pi HQ Camera streams a live view of the physical board. The project combines hardware control, real-time WebSocket communication, and a polished retro-themed web interface.

## Hardware
- **Pi:** Raspberry Pi 4 at `10.0.0.81` (hostname: `litebrite`)
- **SSH:** `ssh karltkurtz@10.0.0.81`
- **LED Matrix:** 16x16 WS2812B (256 LEDs), snake indexed, GPIO 18
- **Camera:** Raspberry Pi HQ Camera (IMX477, 12.3MP) + 16mm telephoto lens
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
- **Camera:** `picamera2` with background capture thread
- **Serving:** uvicorn via systemd service (`litebrite.service`)

## File Structure
```
pixelwave/
├── main.py                  # FastAPI server, WebSocket, LED control, camera
├── stream.py                # Standalone camera stream server (deprecated, camera now in main.py)
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
- **Main app:** `sudo systemctl restart litebrite`
- **Cloudflare tunnel:** `sudo systemctl restart cloudflared`
- **Stream service:** `pixelwave-stream.service` (disabled — camera integrated into main.py)

## Key Technical Details

### Snake Index Remapping
The 16x16 matrix uses snake wiring. Every even row is reversed:
```python
def snake_index(index: int) -> int:
    row = index // 16
    col = index % 16
    if row % 2 == 0:
        col = 15 - col
    return row * 16 + col
```

### Camera
- Integrated into `main.py` as a background thread
- Captures JPEG every 0.02s (~50fps), serves latest frame at `/snapshot`
- Snapshot polling in JS every 150ms (~6-7fps delivery)
- Camera controls available at `/admin/camera` (exposure, gain, brightness, contrast, saturation)

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
- Visitor count shows where visitors are from
- Allow visitors to vote/react to current drawing with emojis (👍❤️🔥)
- Add Animals pixel art templates
- Add floating pixel background to all other pages
- Add sound effects — soft click when painting, chime when finishing
- Show live count of how many people are currently watching
- Rainbow wave animation button on //artwork — button not showing, needs investigation
- Site polish

## Known Issues
- Rainbow wave button on //artwork page not rendering (JS likely not re-running after cache bust)
- Cloudflare Tunnel drops persistent MJPEG streams after ~30s — using snapshot polling instead

## Instagram
- Handle: `@Pi_Garage`
- Email: `PiGarageLab@gmail.com`
