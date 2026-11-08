"""Fieldcast - weather tracker + crop planting calendar (Kivy).
Live data: Open-Meteo (free, no API key)."""
import datetime
from os.path import join
from urllib.parse import quote

import certifi
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.network.urlrequest import UrlRequest
from kivy.storage.jsonstore import JsonStore
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.textinput import TextInput

BG = (0.07, 0.13, 0.09, 1)
INK = (0.90, 0.95, 0.91, 1)
MUTE = (0.58, 0.67, 0.61, 1)
GOOD, FAIR, POOR = (0.18, 0.55, 0.31, 1), (0.85, 0.70, 0.29, 1), (0.17, 0.25, 0.20, 1)
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# name, ideal avg temp C (min, max), ideal monthly rainfall mm (min, max)
CROPS = [
    ("Corn", 20, 32, 80, 200), ("Rice", 22, 32, 200, 450), ("Tomato", 18, 28, 60, 150),
    ("Soybean", 20, 30, 90, 200), ("Potato", 12, 22, 60, 150), ("Sweet potato", 21, 30, 80, 200),
    ("Cassava", 22, 32, 80, 200), ("Wheat", 10, 22, 40, 100), ("Peanut", 22, 32, 80, 180),
]
WX = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog",
      51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 61: "Light rain", 63: "Rain",
      65: "Heavy rain", 80: "Rain showers", 81: "Showers", 82: "Violent showers",
      95: "Thunderstorm", 96: "Thunderstorm, hail", 99: "Thunderstorm, hail"}


def wx_text(code):
    keys = [k for k in WX if k <= code]
    return WX[max(keys)] if keys else "Unknown"


def fetch(url, ok, fail):
    UrlRequest(url, on_success=lambda r, d: ok(d), on_failure=lambda *a: fail(),
               on_error=lambda *a: fail(), ca_file=certifi.where(), timeout=20)


class Lbl(Label):
    def __init__(self, **kw):
        kw.setdefault("halign", "left")
        kw.setdefault("markup", True)
        kw.setdefault("size_hint_y", None)
        kw.setdefault("color", INK)
        super().__init__(**kw)
        self.bind(width=lambda *a: setattr(self, "text_size", (self.width, None)))
        self.bind(texture_size=lambda *a: setattr(self, "height", self.texture_size[1] + dp(6)))


class Cell(Label):
    def __init__(self, rgb, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*rgb)
            self.rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._u, size=self._u)

    def _u(self, *a):
        self.rect.pos, self.rect.size = self.pos, self.size


def column():
    sv = ScrollView()
    box = BoxLayout(orientation="vertical", size_hint_y=None, padding=dp(12), spacing=dp(6))
    box.bind(minimum_height=box.setter("height"))
    sv.add_widget(box)
    return sv, box


def tab(title, content):
    t = TabbedPanelItem(text=title)
    t.add_widget(content)
    return t


class Fieldcast(App):
    def build(self):
        Window.clearcolor = BG
        self.store = JsonStore(join(self.user_data_dir, "cache.json"))
        self.loc = (self.store.get("loc")["v"] if self.store.exists("loc")
                    else {"name": "Manila, Philippines", "lat": 14.6, "lon": 121.0})
        self.climate, self.crop, self.matches = None, 0, []

        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        bar = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        self.q = TextInput(hint_text="Search a town or city", multiline=False)
        self.q.bind(on_text_validate=lambda *a: self.search())
        go = Button(text="Search", size_hint_x=None, width=dp(90))
        go.bind(on_release=lambda *a: self.search())
        bar.add_widget(self.q)
        bar.add_widget(go)
        self.pick = Spinner(text="", size_hint_y=None, height=0, opacity=0)
        self.pick.bind(text=self.on_pick)
        self.status = Lbl(text="Connecting...", color=MUTE, font_size="13sp")

        tp = TabbedPanel(do_default_tab=False, tab_width=dp(110), background_color=BG, background_image="")
        sv, self.now = column()
        sv2, self.week = column()
        sv3, self.crops = column()
        tp.add_widget(tab("Now", sv))
        tp.add_widget(tab("Week", sv2))
        tp.add_widget(tab("Crops", sv3))
        tp.default_tab = tp.tab_list[-1]

        for w in (bar, self.pick, self.status, tp):
            root.add_widget(w)

        self.spin = Spinner(text=CROPS[0][0], values=[c[0] for c in CROPS], size_hint_y=None, height=dp(44))
        self.spin.bind(text=self.on_crop)
        self.load_all()
        Clock.schedule_interval(lambda dt: self.refresh(), 300)  # real-time refresh: 5 min
        return root

    # ---------- location ----------
    def search(self):
        name = self.q.text.strip()
        if len(name) < 2:
            return
        fetch("https://geocoding-api.open-meteo.com/v1/search?count=5&name=" + quote(name),
              self.on_matches, lambda: self.set_status("No connection", False))

    def on_matches(self, d):
        self.matches = d.get("results") or []
        if not self.matches:
            self.set_status("No match. Try another spelling.", False)
            return
        self.pick.values = [self.label_of(m) for m in self.matches]
        self.pick.size_hint_y, self.pick.height, self.pick.opacity = None, dp(44), 1
        self.pick.text = "Choose a match (%d)" % len(self.matches)

    @staticmethod
    def label_of(m):
        return ", ".join(x for x in (m["name"], m.get("admin1"), m.get("country")) if x)

    def on_pick(self, spinner, text):
        for m in self.matches:
            if self.label_of(m) == text:
                self.loc = {"name": text, "lat": m["latitude"], "lon": m["longitude"]}
                self.store.put("loc", v=self.loc)
                self.pick.height, self.pick.opacity = 0, 0
                self.q.text = ""
                self.load_all()

    def load_all(self):
        self.refresh()
        self.load_climate()

    def set_status(self, text, ok=True):
        self.status.text = ("[color=4fbf78]LIVE[/color]  " if ok else "[color=f0b84a]OFFLINE[/color]  ") + text

    # ---------- weather ----------
    def refresh(self):
        lat, lon = self.loc["lat"], self.loc["lon"]
        url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
               "&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
               "&hourly=precipitation_probability,precipitation"
               "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max"
               "&timezone=auto&forecast_days=7" % (lat, lon))
        fetch(url, self.on_weather, self.weather_failed)

    def weather_failed(self):
        if self.store.exists("wx"):
            self.render_weather(self.store.get("wx")["d"])
            self.set_status("Offline, showing saved data", False)
        else:
            self.set_status("No connection", False)

    def on_weather(self, d):
        self.store.put("wx", d=d)
        self.render_weather(d)
        self.set_status("%s - updated %s" % (self.loc["name"], datetime.datetime.now().strftime("%H:%M")))

    def render_weather(self, d):
        c, h, dy = d["current"], d["hourly"], d["daily"]
        self.now.clear_widgets()
        self.now.add_widget(Lbl(text="[b]%d°[/b]" % round(c["temperature_2m"]), font_size="72sp"))
        self.now.add_widget(Lbl(text=wx_text(c["weather_code"]), font_size="20sp"))
        self.now.add_widget(Lbl(text="Feels like %d°   Humidity %d%%\nRain now %s mm   Wind %d km/h" % (
            round(c["apparent_temperature"]), c["relative_humidity_2m"], c["precipitation"],
            round(c["wind_speed_10m"])), color=MUTE))

        i0 = max(0, next((i for i, t in enumerate(h["time"]) if t >= c["time"]), 0))
        prob, mm, times = (h["precipitation_probability"][i0:i0 + 24],
                           h["precipitation"][i0:i0 + 24], h["time"][i0:i0 + 24])
        rain24 = sum(x or 0 for x in mm)
        if rain24 >= 20:
            self.now.add_widget(Lbl(text="[color=6fb0e4][b]Heavy rain:[/b][/color] about %d mm in the next 24 h. "
                                         "Hold off on spraying and fertilizing." % rain24))
        elif prob and max(p or 0 for p in prob) >= 60:
            self.now.add_widget(Lbl(text="[color=6fb0e4][b]Rain likely[/b][/color] in the next 24 hours."))
        if dy["temperature_2m_max"][0] >= 35:
            self.now.add_widget(Lbl(text="[color=f0b84a][b]Heat warning:[/b][/color] high of %d°C today. "
                                         "Water early morning or evening." % round(dy["temperature_2m_max"][0])))
        if all((x or 0) < 1 for x in dy["precipitation_sum"][:5]):
            self.now.add_widget(Lbl(text="[color=f0b84a][b]Dry week ahead.[/b][/color] Plan irrigation."))

        self.now.add_widget(Lbl(text="[b]Rain chance, next 24 hours[/b]"))
        for k in range(0, len(prob), 3):
            p = prob[k] or 0
            self.now.add_widget(Lbl(text="%s   %3d%%  %s" % (times[k][11:16], p, "|" * (p // 5)), color=MUTE))

        self.week.clear_widgets()
        self.week.add_widget(Lbl(text="[b]7-day forecast[/b]", font_size="18sp"))
        for i, t in enumerate(dy["time"]):
            day = "Today" if i == 0 else datetime.date.fromisoformat(t).strftime("%a %d")
            self.week.add_widget(Lbl(text="[b]%s[/b]  %s\n[color=93aa9b]%d° / %d°   rain %s%%, %s mm[/color]" % (
                day, wx_text(dy["weather_code"][i]), round(dy["temperature_2m_max"][i]),
                round(dy["temperature_2m_min"][i]), dy["precipitation_probability_max"][i],
                dy["precipitation_sum"][i])))

    # ---------- crop calendar ----------
    def load_climate(self):
        key = "cl_%.2f_%.2f" % (self.loc["lat"], self.loc["lon"])
        if self.store.exists(key):
            self.climate = self.store.get(key)["m"]
            return self.render_crops()
        self.climate = None
        y = datetime.date.today().year
        url = ("https://archive-api.open-meteo.com/v1/archive?latitude=%s&longitude=%s"
               "&start_date=%d-01-01&end_date=%d-12-31&daily=temperature_2m_mean,precipitation_sum"
               "&timezone=auto" % (self.loc["lat"], self.loc["lon"], y - 3, y - 1))
        fetch(url, lambda d: self.on_climate(d, key), lambda: self.render_crops("Climate data needs a connection."))

    def on_climate(self, d, key):
        T, N, R = [0.0] * 12, [0] * 12, [0.0] * 12
        for t, tm, r in zip(d["daily"]["time"], d["daily"]["temperature_2m_mean"], d["daily"]["precipitation_sum"]):
            m = int(t[5:7]) - 1
            if tm is not None:
                T[m] += tm
                N[m] += 1
            R[m] += r or 0
        self.climate = [{"t": T[m] / max(N[m], 1), "r": R[m] / 3} for m in range(12)]
        self.store.put(key, m=self.climate)
        self.render_crops()

    @staticmethod
    def score(m, c):
        _, t0, t1, r0, r1 = c
        td = t0 - m["t"] if m["t"] < t0 else (m["t"] - t1 if m["t"] > t1 else 0)
        ts = max(0, 1 - td / 8)
        rs = m["r"] / r0 if m["r"] < r0 else (max(0.3, r1 / m["r"]) if m["r"] > r1 else 1)
        return 0.6 * ts + 0.4 * rs

    def on_crop(self, spinner, text):
        self.crop = [c[0] for c in CROPS].index(text)
        self.render_crops()

    def render_crops(self, msg=None):
        self.crops.clear_widgets()
        self.crops.add_widget(Lbl(text="[b]When to plant[/b]", font_size="18sp"))
        self.spin.parent and self.spin.parent.remove_widget(self.spin)
        self.crops.add_widget(self.spin)
        if not self.climate:
            self.crops.add_widget(Lbl(text=msg or "Analyzing local climate...", color=MUTE))
            return
        c, now = CROPS[self.crop], datetime.date.today().month - 1
        s = [self.score(m, c) for m in self.climate]
        best = [i for i, v in enumerate(s) if v >= 0.8]
        close = not best
        if close:
            best = sorted(sorted(range(12), key=lambda i: -s[i])[:2])
        self.crops.add_widget(Lbl(text="[b]Best months for %s: %s%s[/b]" % (
            c[0].lower(), ", ".join(MON[i] for i in best), " (closest match)" if close else ""), font_size="20sp"))
        grid = GridLayout(cols=6, size_hint_y=None, height=dp(100), spacing=dp(4))
        for i, m in enumerate(MON):
            col = GOOD if s[i] >= 0.8 else FAIR if s[i] >= 0.6 else POOR
            txt_col = (0.17, 0.13, 0.03, 1) if col == FAIR else INK
            grid.add_widget(Cell(col, text=("[b]%s*[/b]" % m) if i == now else m, markup=True, color=txt_col))
        self.crops.add_widget(grid)
        verdict = "good" if s[now] >= 0.8 else "fair" if s[now] >= 0.6 else "poor"
        self.crops.add_widget(Lbl(text="* = this month (%s for %s). Green good, amber fair, dark poor." % (
            verdict, c[0].lower()), color=MUTE, font_size="13sp"))
        self.crops.add_widget(Lbl(text="[b]Typical climate here[/b]"))
        top = max(m["r"] for m in self.climate) or 1
        for i, m in enumerate(self.climate):
            self.crops.add_widget(Lbl(text="%s  %s  %d mm, %d°" % (
                MON[i], "|" * int(m["r"] / top * 18), round(m["r"]), round(m["t"])), color=MUTE, font_size="13sp"))
        self.crops.add_widget(Lbl(text="Based on 3 years of recorded weather at this location. A guide only: "
                                       "check local advice on varieties and irrigation.", color=MUTE, font_size="12sp"))


if __name__ == "__main__":
    Fieldcast().run()
