import argparse, http.client, math, random, socket, ssl, sys, time, urllib.parse

REST = [26000, 31000, 24000, 29000, 1000000, 27000]
STAND = {0: 6.0, 2: 14.0, 5: 45.0}
WALK = [(5, 0.00, 0.35, 40.0), (4, 0.20, 0.55, 5.0), (3, 0.35, 0.70, 9.0), (2, 0.35, 0.75, 14.0), (0, 0.55, 0.85, 7.0), (1, 0.60, 0.85, 5.0)]
PRESS_RATIO, RELEASE_RATIO, ALERT_MS = 4, 2, 10000


def ratios(pattern, t):
    if pattern == "idle":
        return {}
    if pattern == "stand":
        return {i: r * (1 + 0.05 * math.sin(t * 0.7 + i)) for i, r in STAND.items()}
    phase = (t / 1.1) % 1.0
    return {i: r for i, a, b, r in WALK if a <= phase < b}


class Insole:
    def __init__(self):
        self.active, self.start = [False] * 6, [0.0] * 6

    def frame(self, pattern, t):
        load = ratios(pattern, t)
        times, timers = [], []
        for i in range(6):
            x = load.get(i, 1.0) * random.uniform(0.93, 1.07)
            if REST[i] >= 1000000 and i not in load:
                reading = -3
            elif random.random() < 0.02:
                reading = -1
            else:
                reading = int((REST[i] if REST[i] < 1000000 else 20000 * 50) / x)
            if reading >= 0:
                loaded = reading * (RELEASE_RATIO if self.active[i] else PRESS_RATIO) < REST[i]
                if loaded and not self.active[i]:
                    self.start[i] = t
                self.active[i] = loaded
            elif reading == -3:
                self.active[i] = False
            times.append(reading)
            timers.append(max(1, int((t - self.start[i]) * 1000)) if self.active[i] else 0)
        return f"{','.join(map(str, times))} | {','.join(map(str, REST))} | {','.join(map(str, timers))}"


def main():
    ap = argparse.ArgumentParser(description="Pretend to be the Sparsh insole, to test a server without hardware.")
    ap.add_argument("--url", help="send over HTTP(S) to this /ingest URL instead of UDP")
    ap.add_argument("--key", default="sparsh-demo", help="device key, must match DEVICE_KEY on the server")
    ap.add_argument("--host", default="255.255.255.255", help="UDP target (default: broadcast)")
    ap.add_argument("--pattern", choices=["stand", "walk", "idle"], default="stand")
    ap.add_argument("--seconds", type=float, default=0, help="stop after this long (default: run until Ctrl+C)")
    a = ap.parse_args()
    insole, t0, sent, failed = Insole(), time.time(), 0, 0
    if a.url:
        u = urllib.parse.urlsplit(a.url)
        make = (lambda: http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=10, context=ssl.create_default_context())) \
            if u.scheme == "https" else (lambda: http.client.HTTPConnection(u.hostname, u.port or 80, timeout=10))
        conn = make()
    else:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    print(f"Sending '{a.pattern}' frames to {a.url or a.host + ':4210 (UDP)'}. Ctrl+C to stop.", flush=True)
    try:
        while not a.seconds or time.time() - t0 < a.seconds:
            line = insole.frame(a.pattern, time.time() - t0)
            if a.url:
                try:
                    conn.request("POST", u.path or "/ingest", body=line, headers={"Content-Type": "text/plain", "X-Device-Key": a.key})
                    r = conn.getresponse(); r.read()
                    if r.status != 200:
                        failed += 1
                        print(f"Server answered {r.status}. Check the URL and DEVICE_KEY.", file=sys.stderr)
                        time.sleep(1)
                except (OSError, http.client.HTTPException) as e:
                    failed += 1
                    print(f"Send failed ({e}); retrying. A sleeping Render service takes up to a minute to wake.", file=sys.stderr)
                    conn.close(); conn = make(); time.sleep(1)
            else:
                sock.sendto(line.encode(), (a.host, 4210))
            sent += 1
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    print(f"Sent {sent} frames, {failed} failed.")


if __name__ == "__main__":
    main()
