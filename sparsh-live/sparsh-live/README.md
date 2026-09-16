# Sparsh live dashboard

The insole's real readings now drive the dashboard heatmap. The same server runs on your laptop (live demo, readings stay on the local network) or on Render (public website).

| File | What it is |
|---|---|
| `public/sparsh-app.html` | Your dashboard. The heatmap now uses each zone's measured pressure. |
| `public/check.html` | Sensor check page at `/check`: live reading, heat bar and timer per pad. |
| `server.py` | Replaces `sparsh-bridge.py`. Python 3 standard library only. |
| `firmware/sparsh/sparsh.ino` | Your firmware. Sensing and motor logic unchanged; Wi-Fi now carries readings, resting times and timers. |
| `tools/fake_insole.py` | Stand-in insole for testing without hardware. |
| `Dockerfile`, `render.yaml` | Public hosting on Render. |

## 1. Live demo on the laptop

1. Flash `firmware/sparsh/sparsh.ino`. Switch the insole on with nobody standing on it.
2. Put the laptop on the same Wi-Fi as the insole (a phone hotspot is safest), stop the old bridge, then run:
   ```
   python server.py
   ```
3. Open http://localhost:8000 for the dashboard and http://localhost:8000/check to test each pad. Phones on the same Wi-Fi can use `http://<laptop IP>:8000`.

The new firmware needs this server. The old `sparsh-bridge.py` can't read its packets.

## 2. Public website on Render

1. Push this folder to a GitHub repo. `firmware/` is git-ignored because it contains your Wi-Fi password.
2. In Render: **New → Blueprint**, pick the repo, **Apply**. When asked, set `DEVICE_KEY` and `VIEW_KEY` to your own secrets.
3. Render gives you `https://<name>.onrender.com`. With no insole sending to it, the dashboard runs its built-in simulator, so no readings leave your network.

The free plan sleeps after 15 minutes without traffic, and the first visit then takes up to a minute. Open the site a minute before presenting.

## 3. Optional: live readings on the public site

In the firmware, set:
```
const char* cloudUrl = "https://<name>.onrender.com/ingest";
const char* deviceKey = "<your DEVICE_KEY>";
```
Then open `https://<name>.onrender.com/?key=<VIEW_KEY>` (and `/check?key=<VIEW_KEY>`). Without the key the page stays in simulator mode.

**This sends readings over the internet.** Slides 3, 6, 7, 10 and 15 say readings stay on the local network, so update them first or leave this off.

Test the public site without hardware:
```
python tools/fake_insole.py --url https://<name>.onrender.com/ingest --key <DEVICE_KEY> --pattern walk
```
For the laptop server: `python tools/fake_insole.py --host 127.0.0.1`.

## What the heatmap shows

Each zone's patch is the larger of two things, as in your original design:
- **Pressure:** how many times faster the pad charges than at rest, on a log scale. The firmware's 4× "loaded" point sits exactly on the app's loaded line, and the hardest current press sets full scale. It is relative and uncalibrated, not kPa.
- **Time:** the patch reddens as the zone nears the 10 s limit.

A zone shows above the loaded line only when the firmware itself counts it as loaded. Single-sample glitches are filtered out.

Server settings (environment variables): `PRESS_RATIO` (default 4, keep equal to the firmware's), `HEAT_FULL_RATIO` (default 100), `PORT` (8000), `UDP_PORT` (4210, `0` turns UDP off).

## Troubleshooting

- **Nothing live:** allow Python through the firewall and check both devices are on the same Wi-Fi. Campus Wi-Fi often blocks device-to-device traffic, so use a phone hotspot.
- **"UDP port 4210 is busy":** the old bridge is still running.
- **A barely touched pad stays on "Held" in `/check`:** lift the foot fully and it clears within half a second.
- **Status for debugging:** `/api/status` shows the latest packet, its age and its source.
