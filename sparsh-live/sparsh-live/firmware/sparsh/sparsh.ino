#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
const char* ssid = "Kanav has Nothing";
const char* password = "10050709";
const char* cloudUrl = "";
const char* deviceKey = "sparsh-demo";
const int udpPort = 4210;
WiFiUDP udp;
QueueHandle_t frames;
const int SENSORS = 6;
const int HALLUX = 23, TOES_2_5 = 22, MT_1 = 21, MT_4_5 = 19, MIDFOOT = 18, HEEL = 5;
const int digitalPins[SENSORS] = {HALLUX, TOES_2_5, MT_1, MT_4_5, MIDFOOT, HEEL};
const int MOTOR_PIN = 27;
const int adcPin = 34;
const int RISE = 150, START_MAX = 1500, CAL_SCANS = 9;
const double FULL = 4360;
const unsigned long TIMEOUT_US = 10000, DWELL_US = 1000, TAU_OPEN = 1000000;
const unsigned long DURATION = 10000, DEBOUNCE = 500;
const double PRESS_RATIO = 4, RELEASE_RATIO = 2;
unsigned long rest[SENSORS], runMin[SENSORS], thresholdStartTime[SENSORS], lastHigh[SENSORS], scanTime, lastSend, gapLimit;
int runCount[SENSORS];
long Times[SENSORS];
bool active[SENSORS], alerting[SENSORS];

void setLow() {
  for (int j = 0; j < SENSORS; j++) {
    pinMode(digitalPins[j], OUTPUT);
    digitalWrite(digitalPins[j], LOW);
  }
}

long chargeTime(int i) {
  for (int attempt = 0; attempt < 3; attempt++) {
    setLow();
    delayMicroseconds(DWELL_US);
    unsigned long start = micros();
    while (analogRead(adcPin) > START_MAX) if (micros() - start > TIMEOUT_US) return -2;
    for (int j = 0; j < SENSORS; j++) if (j != i) pinMode(digitalPins[j], INPUT);
    int v0 = analogRead(adcPin), v = v0;
    unsigned long t0 = micros(), tb = t0, ta = t0;
    digitalWrite(digitalPins[i], HIGH);
    while (v < v0 + RISE && tb - t0 < TIMEOUT_US) {
      tb = micros();
      v = analogRead(adcPin);
      ta = micros();
    }
    setLow();
    if (v < v0 + RISE) return -3;
    if (ta - tb < gapLimit) return (tb - t0) / log((FULL - v0) / (FULL - v));
  }
  return -1;
}

bool isLoaded(int i, long t) {
  if (t < 0) {
    runCount[i] = 0;
    return false;
  }
  if ((unsigned long)t > rest[i] && rest[i] < TAU_OPEN) {
    runMin[i] = runCount[i]++ ? min(runMin[i], (unsigned long)t) : t;
    if (runCount[i] >= 3) rest[i] = runMin[i], runCount[i] = 0;
  } else runCount[i] = 0;
  return t * (active[i] ? RELEASE_RATIO : PRESS_RATIO) < rest[i];
}

bool checkThresholdTimer(int i, bool loaded, unsigned long now) {
  if (loaded) {
    if (!active[i]) thresholdStartTime[i] = now;
    active[i] = true;
    lastHigh[i] = now;
  } else if (now - lastHigh[i] + scanTime >= DEBOUNCE) active[i] = false;
  return active[i] && lastHigh[i] - thresholdStartTime[i] >= DURATION;
}

void uplink(void*) {
  WiFiClientSecure client;
  client.setInsecure();
  client.setHandshakeTimeout(10);
  HTTPClient http;
  http.setReuse(true);
  http.setConnectTimeout(5000);
  http.setTimeout(3000);
  char frame[256];
  for (;;) {
    xQueueReceive(frames, frame, portMAX_DELAY);
    if (WiFi.status() != WL_CONNECTED) continue;
    http.begin(client, cloudUrl);
    http.addHeader("Content-Type", "text/plain");
    http.addHeader("X-Device-Key", deviceKey);
    int code = http.POST((uint8_t*)frame, strlen(frame));
    http.end();
    if (code != 200) delay(1000);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(MOTOR_PIN, OUTPUT);
  digitalWrite(MOTOR_PIN, LOW);
  analogRead(adcPin);
  unsigned long readUs = ULONG_MAX;
  for (int k = 0; k < 20; k++) {
    unsigned long s = micros();
    analogRead(adcPin);
    readUs = min(readUs, micros() - s);
  }
  gapLimit = max(1000UL, 10 * readUs);
  long cal[SENSORS][CAL_SCANS];
  for (int k = 0; k < CAL_SCANS; k++)
    for (int i = 0; i < SENSORS; i++) cal[i][k] = chargeTime(i);
  for (int i = 0; i < SENSORS; i++) {
    long v[CAL_SCANS];
    int n = 0;
    for (int k = 0; k < CAL_SCANS; k++) if (cal[i][k] >= 0 || cal[i][k] == -3) v[n++] = cal[i][k] < 0 ? TAU_OPEN : cal[i][k];
    for (int a = 1; a < n; a++)
      for (int b = a; b > 0 && v[b - 1] > v[b]; b--) std::swap(v[b], v[b - 1]);
    rest[i] = n ? v[n / 2] : 0;
  }
  Serial.printf("ADC read %lu us, resting times:", readUs);
  for (int i = 0; i < SENSORS; i++) Serial.printf(" %lu", rest[i]);
  Serial.println();
  WiFi.begin(ssid, password);
  if (*cloudUrl) {
    frames = xQueueCreate(1, 256);
    xTaskCreatePinnedToCore(uplink, "uplink", 16384, nullptr, 1, nullptr, 0);
  }
}

void loop() {
  static unsigned long lastLoop = millis();
  scanTime = millis() - lastLoop;
  lastLoop = millis();
  bool buzz = false, changed = false;
  for (int i = 0; i < SENSORS; i++) {
    bool wasActive = active[i], wasAlerting = alerting[i];
    Times[i] = chargeTime(i);
    alerting[i] = checkThresholdTimer(i, isLoaded(i, Times[i]), millis());
    buzz |= alerting[i];
    changed |= active[i] != wasActive || alerting[i] != wasAlerting;
  }
  digitalWrite(MOTOR_PIN, buzz);
  if (!changed && millis() - lastSend < 100) return;
  lastSend = millis();
  String times, rests, timers;
  for (int i = 0; i < SENSORS; i++) {
    const char* sep = i < SENSORS - 1 ? "," : "";
    times += String(Times[i]) + sep;
    rests += String(rest[i]) + sep;
    timers += String(active[i] ? max(1UL, lastHigh[i] - thresholdStartTime[i]) : 0UL) + sep;
  }
  String line = times + " | " + rests + " | " + timers;
  Serial.println(line);
  if (frames) {
    char frame[256];
    line.toCharArray(frame, sizeof frame);
    xQueueOverwrite(frames, frame);
  }
  if (WiFi.status() != WL_CONNECTED) return;
  udp.beginPacket(WiFi.broadcastIP(), udpPort);
  udp.print(line);
  udp.endPacket();
}
