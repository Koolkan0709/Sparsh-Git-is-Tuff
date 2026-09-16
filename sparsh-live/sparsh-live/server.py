import hmac, json, math, os, queue, re, socket, sys, threading, time
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

N = 6
PORT = int(os.environ.get("PORT", "8000"))
UDP_PORT = int(os.environ.get("UDP_PORT", "4210"))
DEVICE_KEY = os.environ.get("DEVICE_KEY") or "sparsh-demo"
VIEW_KEY = os.environ.get("VIEW_KEY", "")
PRESS_RATIO = max(1.1, float(os.environ.get("PRESS_RATIO", "4")))
LOADED_AT = 0.45
GAIN_FLOOR = PRESS_RATIO * 2
HEAT_FULL_RATIO = max(GAIN_FLOOR, float(os.environ.get("HEAT_FULL_RATIO", "100")))
GAIN_HALF_LIFE_S = 30.0
LIVE_WINDOW_S = 2.0
WEB = Path(__file__).resolve().parent / "public"
APP = "sparsh-app.html"
APP_PATHS = {"/", "/index.html", "/" + APP}
ROUTES = {"/check": "/check.html"}

subs, subs_lock, state_lock = set(), threading.Lock(), threading.Lock()
state = {"gain": GAIN_FLOOR, "heat": [0.0] * N, "at": 0.0, "src": None, "frame": None, "frames": 0,
         "recent": [[] for _ in range(N)]}


def parse(text):
    try:
        groups = [[int(x) for x in re.split(r"[\s,;]+", g.strip()) if x] for g in text.strip().split("|")]
    except ValueError:
        return None
    if any(len(g) != N for g in groups):
        return None
    if len(groups) == 1:
        t, r, m = None, None, groups[0]
    elif len(groups) == 3:
        t, r, m = groups
        if min(r) < 0 or min(t) < -3:
            return None
    else:
        return None
    return None if min(m) < 0 else {"t": t, "r": r, "m": m}


def zone_ratio(t, r):
    if t == -3 or r <= 0:
        return 0.0
    if t < 0:
        return None
    return math.inf if t == 0 else r / t


def heat_of(ratio, loaded, full):
    if ratio <= 1:
        h = 0.0
    elif ratio < PRESS_RATIO:
        h = LOADED_AT * math.log(ratio) / math.log(PRESS_RATIO)
    else:
        h = LOADED_AT + (1 - LOADED_AT) * min(1.0, math.log(ratio / PRESS_RATIO) / math.log(full / PRESS_RATIO))
    return max(h, LOADED_AT) if loaded else min(h, LOADED_AT - 0.01)


def compute_heat(frame, now):
    m = frame["m"]
    if frame["t"] is None:
        return [LOADED_AT if x > 0 else 0.0 for x in m]
    ratios = []
    for i, (t, r) in enumerate(zip(frame["t"], frame["r"])):
        x, recent = zone_ratio(t, r), state["recent"][i]
        if x is not None:
            recent[:] = (recent + [x])[-3:]
            x = sorted(recent)[len(recent) // 2]
        ratios.append(x)
    dt = now - state["at"] if state["at"] else 0.0
    gain = GAIN_FLOOR + (state["gain"] - GAIN_FLOOR) * 0.5 ** (dt / GAIN_HALF_LIFE_S)
    peak = max((x for x in ratios if x is not None), default=0.0)
    gain = min(HEAT_FULL_RATIO, max(gain, peak))
    state["gain"] = gain
    heat = [
        (max(state["heat"][i], LOADED_AT) if m[i] > 0 else min(state["heat"][i], LOADED_AT - 0.01)) if x is None
        else heat_of(x, m[i] > 0, gain)
        for i, x in enumerate(ratios)
    ]
    return [round(h, 3) for h in heat]


def publish(frame, src):
    now = time.time()
    with state_lock:
        frame["h"] = compute_heat(frame, now)
        frame["src"], frame["ts"] = src, int(now * 1000)
        state.update(heat=frame["h"], at=now, src=src, frame=frame, frames=state["frames"] + 1)
        body = "data: %s\n\nevent: frame\ndata: %s\n\n" % (
            ",".join(map(str, frame["m"])), json.dumps(frame, separators=(",", ":")))
    with subs_lock:
        targets = list(subs)
    for q in targets:
        try:
            q.put_nowait(body)
        except queue.Full:
            pass


def udp_pump(sock):
    while True:
        data = sock.recv(1024).decode(errors="ignore")
        frame = parse(data)
        if frame:
            publish(frame, "wifi")


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 75
    server_version = "Sparsh"
    sys_version = ""

    def log_request(self, code="-", size="-"):
        path = self.path.split("?", 1)[0]
        if path in ("/ingest", "/healthz") and str(code).startswith("2"):
            return
        super().log_request(code, size)

    def end_headers(self):
        if self.path.endswith(".html"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(HTTPStatus.NOT_FOUND)

    def reply(self, code, body, ctype="text/plain; charset=utf-8"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def viewer_ok(self):
        given = parse_qs(urlsplit(self.path).query).get("key", [""])[0]
        if not VIEW_KEY or hmac.compare_digest(given.encode(), VIEW_KEY.encode()):
            return True
        self.reply(403, "Add ?key=<VIEW_KEY> to the page address to see live data.")
        return False

    def route(self):
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self.reply(200, "ok")
            return True
        if path == "/api/status":
            if not self.viewer_ok():
                return True
            with state_lock:
                age = time.time() - state["at"] if state["at"] else None
                body = {"device": "online" if age is not None and age < LIVE_WINDOW_S else "offline",
                        "last_frame_age_s": None if age is None else round(age, 2), "source": state["src"],
                        "frames": state["frames"], "frame": state["frame"], "heat_full_ratio": round(state["gain"], 2)}
            with subs_lock:
                body["viewers"] = len(subs)
            self.reply(200, json.dumps(body), "application/json")
            return True
        if path in APP_PATHS:
            self.serve_app()
            return True
        if path in ROUTES:
            self.path = ROUTES[path]
        return False

    def serve_app(self):
        page = WEB / APP
        if not page.is_file():
            return self.reply(503, f"Missing public/{APP}. Copy your Sparsh app into the public folder.")
        html = page.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(html)

    def do_HEAD(self):
        if not self.route():
            super().do_HEAD()

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/events":
            return self.events() if self.viewer_ok() else None
        if not self.route():
            super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 2048:
            self.close_connection = True
            return self.reply(413, "too large")
        body = self.rfile.read(length).decode(errors="ignore")
        if self.path.split("?", 1)[0] != "/ingest":
            return self.reply(404, "not found")
        if not hmac.compare_digest(self.headers.get("X-Device-Key", "").encode(), DEVICE_KEY.encode()):
            return self.reply(401, "bad device key")
        frame = parse(body)
        if not frame:
            return self.reply(400, "expected 6 timers, or 6 readings | 6 resting times | 6 timers")
        publish(frame, "cloud")
        self.reply(200, "ok")

    def events(self):
        chunked = self.request_version == "HTTP/1.1"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Transfer-Encoding" if chunked else "Connection", "chunked" if chunked else "close")
        self.end_headers()
        q = queue.Queue(maxsize=64)
        with subs_lock:
            subs.add(q)

        def send(text):
            data = text.encode()
            self.wfile.write(b"%X\r\n%s\r\n" % (len(data), data) if chunked else data)

        try:
            send("retry: 2000\n\n")
            while True:
                try:
                    send(q.get(timeout=5))
                except queue.Empty:
                    send(":\n\n")
        except (OSError, ValueError):
            pass
        finally:
            with subs_lock:
                subs.discard(q)
            self.close_connection = True


def main():
    if UDP_PORT:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("", UDP_PORT))
        except OSError as e:
            sys.exit(f"UDP port {UDP_PORT} is busy ({e}). Close the other bridge/server first.")
        threading.Thread(target=udp_pump, args=(sock,), daemon=True).start()
    httpd = ThreadingHTTPServer(("", PORT), partial(Handler, directory=str(WEB)))
    where = f"UDP {UDP_PORT} and " if UDP_PORT else ""
    lock = " Live data needs ?key=<VIEW_KEY>." if VIEW_KEY else ""
    if not UDP_PORT and DEVICE_KEY == "sparsh-demo":
        print("Warning: DEVICE_KEY is the public default. Set your own so others cannot send readings.", flush=True)
    print(f"Sparsh server: listening on {where}HTTP {PORT}. Open http://localhost:{PORT}{lock}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
