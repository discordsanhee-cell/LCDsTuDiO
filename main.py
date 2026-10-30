"""
LCD 꾸미기 v1.4 (2026-10-09)
lcdpanel 보드의 화면을 꾸미고 보내는 앱 (Flet - 같은 코드로 exe / apk)

- 미리보기에서 위젯을 끌어서 옮기고, 오른쪽에서 속성 수정
- 위젯: 글자(치환 코드), 디지털 시계, 날짜, 아날로그 시계, D-day, 변수, 날씨 기온, 날씨, 사각형, 원, 선, 막대, 이미지
- 보드 찾기(블루투스), 화면 보내기, 실제 화면 보기, 화면/WiFi 설정, 시간 맞추기, 변수 보내기
- v1.4: 보드와 블루투스로만 통신 (화면/페이지/이미지/설정 전부), WiFi는 펌웨어 업데이트 때만, 시간·날씨는 앱이 넣어줌
- v1.3: 페이지(화면 여러 개) 편집/전환/삭제/모두 삭제, 날씨 위젯, 블루투스 모드(WiFi 없이 조종)
- v1.2: 이미지 올릴 때 PNG/투명/큰 사진을 자동으로 화면 크기의 JPG로 변환 (T-Display는 PNG를 못 그림)
- v1.1: T-Display(135x240) 지원 - 배터리 코드 {bat} {bat_pct}, 연결하면 보드 화면 크기에 맞춰 미리보기
"""

import asyncio
import copy
import datetime
import json
import os
import re
import time

import flet as ft
import flet.canvas as cv

from ble import BleLink, BleError
from device import Device, DeviceError, fetch_weather, prepare_image


def WEATHER_DESC(c):  # 보드의 weatherDesc 와 같음 (미리보기용)
    if c < 0:
        return "-"
    for lo, hi, t in ((0, 0, "맑음"), (1, 2, "구름 조금"), (3, 3, "흐림"), (45, 48, "안개"), (51, 57, "이슬비"),
                      (61, 67, "비"), (71, 77, "눈"), (80, 82, "소나기"), (85, 86, "눈 소나기"), (95, 99, "뇌우")):
        if lo <= c <= hi:
            return t
    return "?"

APP_VER = "v1.4"

FONTS = {
    "kr12": ("한글 12px", 12, 1.0),
    "kr16": ("한글 16px", 16, 1.0),
    "kr24": ("한글 24px", 24, 1.0),
    "seg7": ("7세그 숫자 (0-9 : . -)", 48, 0.67),
    "num": ("숫자/영문 26px", 26, 0.6),
    "sans": ("영문 굵게", 22, 0.6),
    "sans24": ("영문 굵게 큰", 44, 0.6),
}
ALIGNS = {"left": "왼쪽", "center": "가운데", "right": "오른쪽"}
PALETTE = ["#ffffff", "#000000", "#94a3b8", "#ef4444", "#f97316", "#fbbf24",
           "#22c55e", "#06b6d4", "#3b82f6", "#a855f7", "#ec4899", "#1e293b"]

PRESETS = {
    "글자": {"type": "text", "x": 20, "y": 20, "text": "안녕하세요", "font": "kr16", "size": 1, "color": "#ffffff", "align": "left"},
    "디지털 시계": {"type": "text", "x": 120, "y": 40, "text": "{HH}:{mm}", "font": "seg7", "size": 1, "color": "#ffffff", "align": "center"},
    "날짜": {"type": "text", "x": 120, "y": 110, "text": "{YYYY}.{MM}.{DD} ({ddd})", "font": "kr24", "size": 1, "color": "#e2e8f0", "align": "center"},
    "아날로그 시계": {"type": "clock", "x": 120, "y": 160, "r": 60, "color": "#ffffff", "hand": "#ffffff", "sec": "#ef4444", "seconds": True},
    "D-day": {"type": "text", "x": 120, "y": 200, "text": "크리스마스 {dday:2026-12-25}", "font": "kr16", "size": 1, "color": "#fbbf24", "align": "center"},
    "변수": {"type": "text", "x": 20, "y": 240, "text": "CPU {var:cpu}%", "font": "kr16", "size": 1, "color": "#7dd3fc", "align": "left"},
    "센서 온도": {"type": "text", "x": 120, "y": 60, "text": "{ntc}°C", "font": "kr24", "size": 2, "color": "#ffffff", "align": "center"},
    "날씨": {"type": "text", "x": 120, "y": 120, "text": "{wdesc}", "font": "kr24", "size": 1, "color": "#7dd3fc", "align": "center"},
    "사각형": {"type": "rect", "x": 20, "y": 20, "w": 100, "h": 60, "color": "#1e293b", "fill": True, "radius": 8},
    "원": {"type": "circle", "x": 120, "y": 160, "r": 30, "color": "#3b82f6", "fill": True},
    "선": {"type": "line", "x": 20, "y": 150, "x2": 220, "y2": 150, "color": "#64748b", "thick": 2},
    "막대": {"type": "bar", "x": 20, "y": 150, "w": 200, "h": 10, "value": "{sec_pct}", "max": 100, "color": "#22c55e", "bg": "#1e293b", "radius": 5},
}

DEFAULT_LAYOUT = {
    "bg": "#0b1020",
    "widgets": [
        copy.deepcopy(PRESETS["디지털 시계"]),
        copy.deepcopy(PRESETS["날짜"]),
        {"type": "text", "x": 120, "y": 298, "text": "{ip}", "font": "kr12", "size": 1, "color": "#64748b", "align": "center"},
    ],
}

HELP = (
    "글자 안에 넣으면 보드가 자동으로 바꿔줘요\n"
    "시간  {HH} {mm} {ss}  12시간 {hh}  {ampm}=오전/오후\n"
    "날짜  {YYYY} {MM} {DD}  요일 {ddd}=월 {dddd}=월요일 {eee}=Mon\n"
    "센서  {ntc}=보드에 연결된 온도 센서 (없으면 --)\n"
    "외부 날씨  {wtemp}=기온 {wdesc}=맑음/흐림/비.. {city}=도시\n"
    "정보  {ip} {ssid} {rssi} {temp}=칩온도 {uptime} {heap}\n"
    "배터리 (T-Display)  {bat}=전압 {bat_pct}=% {bat_txt}=충전 중/85%\n"
    "D-day  {dday:2026-12-25}  →  D-23 / D-Day / D+3\n"
    "변수  {var:이름}  (앱의 '변수 보내기'나 PC 프로그램에서 값 전달)\n"
    "막대 값  {sec_pct} {min_pct} {day_pct} 또는 {var:이름}"
)

LABELS = {
    **{"text": "내용", "value": "값", "file": "이미지 파일", "font": "글꼴", "size": "글자 배율", "align": "정렬",
       "x": "X", "y": "Y", "x2": "끝 X", "y2": "끝 Y", "w": "너비", "h": "높이", "r": "반지름",
       "radius": "모서리 둥글기", "thick": "두께", "max": "최댓값", "color": "색", "bg": "배경색"},
    **{"bgcolor": "글자 배경색", "hand": "바늘 색", "sec": "초침 색", "fill": "채우기", "seconds": "초침 표시"},
}
FIELD_ORDER = ["text", "value", "file", "font", "size", "align", "x", "y", "x2", "y2", "w", "h", "r", "radius",
               "thick", "max", "color", "bg", "bgcolor", "hand", "sec", "fill", "seconds"]
NUMERIC = {"x", "y", "x2", "y2", "w", "h", "r", "radius", "thick", "max", "size"}
COLORS = {"color", "bg", "bgcolor", "hand", "sec"}
TYPE_NAMES = {"text": "글자", "rect": "사각형", "circle": "원", "line": "선", "bar": "막대", "clock": "아날로그 시계", "image": "이미지"}

WK_KO = ["월", "화", "수", "목", "금", "토", "일"]
WK_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# 미리보기용 치환 (보드와 같은 코드, 보드 정보는 연결했을 때 값 또는 예시)
def expand(s, ctx):
    now = datetime.datetime.now()

    def tok(m):
        t = m.group(1)
        h12 = now.hour % 12 or 12
        table = {
            "YYYY": f"{now.year}", "YY": f"{now.year % 100:02d}", "MM": f"{now.month:02d}", "M": f"{now.month}",
            "DD": f"{now.day:02d}", "D": f"{now.day}", "HH": f"{now.hour:02d}", "H": f"{now.hour}",
            "hh": f"{h12:02d}", "h": f"{h12}", "mm": f"{now.minute:02d}", "ss": f"{now.second:02d}",
            "ampm": "오전" if now.hour < 12 else "오후", "AMPM": "AM" if now.hour < 12 else "PM",
            "ddd": WK_KO[now.weekday()], "dddd": WK_KO[now.weekday()] + "요일", "eee": WK_EN[now.weekday()],
            **{"ip": ctx.get("ip", "192.168.0.10"), "ssid": ctx.get("ssid", "MyWiFi"), "rssi": "-55",
               "temp": "42.5", "heap": "180", "bat": "4.05", "bat_pct": "83", "bat_txt": "83%",
               "name": ctx.get("name", "lcd"), "uptime": "0d 01:23",
               "ntc": ctx.get("ntc", "--"), "wtemp": ctx.get("wtemp", "18.4"), "wdesc": ctx.get("wdesc", "구름 조금"), "city": ctx.get("city", "Seoul"),
               "sec_pct": str(now.second * 100 // 59), "min_pct": str(now.minute * 100 // 59),
               "day_pct": str((now.hour * 3600 + now.minute * 60 + now.second) * 100 // 86399)},
        }
        if t in table:
            return table[t]
        if t.startswith("dday:"):
            try:
                d = (datetime.date.fromisoformat(t[5:]) - now.date()).days
            except ValueError:
                return "D-?"
            if d == 0:
                return "D-Day"
            return f"D-{d}" if d > 0 else f"D+{-d}"
        if t.startswith("var:"):
            return str(ctx.get("vars", {}).get(t[4:], "-"))
        return "{" + t + "}"

    return re.sub(r"\{([^}]+)\}", tok, str(s or ""))


def text_width(s, px, ratio):
    return sum(px if ord(c) > 0x2000 else px * ratio for c in s)


def num(v, default=0):
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return default


def safe_name(name):
    base, ext = os.path.splitext(name)
    ext = ext.lower()
    base = re.sub(r"[^A-Za-z0-9_-]", "", base)[:28] or f"img{int(time.time()) % 100000}"
    return base + ext


def main(page: ft.Page):
    page.title = f"LCD 꾸미기 {APP_VER}"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 12
    page.scroll = ft.ScrollMode.AUTO

    prefs = ft.SharedPreferences()
    picker = ft.FilePicker()
    page.services.extend([prefs, picker])

    st = {
        "layout": copy.deepcopy(DEFAULT_LAYOUT), "sel": None, "ctx": {"vars": {}},
        "files": [], "img": {}, "w": 240, "h": 320, "settings": {},
        "page": 0, "pages": [0], "max_pages": 1,  # 편집 중인 페이지 / 보드에 있는 페이지
    }

    ble = BleLink(page)

    def dev():
        return Device(link=ble)  # 모든 기능은 블루투스로

    def scale():
        pw = page.width or 1000
        if pw >= 760:
            return 1.5
        return max(1.0, min(1.5, (pw - 40) / st["w"]))

    def toast(msg, error=False):
        page.show_dialog(ft.SnackBar(ft.Text(msg), bgcolor="#7f1d1d" if error else None))

    async def pref_set(k, v):
        try:
            await prefs.set(k, v)
        except Exception:
            pass

    status = ft.Text("'찾기'를 눌러 블루투스로 보드를 찾으세요 (지난번 보드는 바로 '연결')", size=12, color="#94a3b8")

    async def run_net(label, fn, *args):
        status.value = f"{label}..."
        status.update()
        st["busy"] = st.get("busy", 0) + 1  # 전송 중엔 미리보기 1초 갱신을 쉼 (블루투스 수신이 밀리지 않게)
        try:
            r = await asyncio.to_thread(fn, *args)
            status.value = f"{label} 완료"
            status.update()
            return r
        except DeviceError as e:
            status.value = f"{label} 실패: {e}"
            status.update()
            toast(f"{label} 실패: {e}", True)
            return None
        except Exception as e:
            status.value = f"{label} 실패: {e}"
            status.update()
            toast(f"{label} 실패: {e}", True)
            return None
        finally:
            st["busy"] -= 1

    # ───────── 미리보기 ─────────
    preview = ft.Stack(width=240, height=320, clip_behavior=ft.ClipBehavior.HARD_EDGE)
    preview_box = ft.Container(content=preview, border=ft.Border.all(2, "#334155"), border_radius=6)

    def select(i):
        st["sel"] = i
        build_props()
        build_list()
        refresh_preview()

    def mover(i):
        def on_pan(e: ft.DragUpdateEvent):
            S = scale()
            if i >= len(st["layout"]["widgets"]):
                return
            w = st["layout"]["widgets"][i]
            dx, dy = e.local_delta.x / S, e.local_delta.y / S
            for kx, ky in (("x", "y"), ("x2", "y2")):
                if kx not in w:
                    continue
                w[kx] = round(num(w[kx]) + dx)
                w[ky] = round(num(w[ky]) + dy)
            if st["sel"] != i:
                st["sel"] = i
                build_list()
            refresh_preview()
            sync_xy()

        return on_pan

    def wrap(i, ctrl, left, top):
        sel = st["sel"] == i
        return (ft.Container(content=ctrl, bgcolor="#00000000",
                             border=ft.Border.all(1, "#f59e0b") if sel else None), left, top)

    def draw_widget(i, w, S):
        t = w.get("type")
        col = w.get("color", "#ffffff")
        x, y = num(w.get("x")), num(w.get("y"))
        if t == "text":
            name, px, ratio = FONTS.get(w.get("font", "kr16"), FONTS["kr16"])
            sz = num(w.get("size"), 1) or 1
            lines = expand(w.get("text", ""), st["ctx"]).split("\n")
            tw = max(text_width(l, px, ratio) for l in lines) * sz + 4
            th = px * sz * len(lines)
            al = w.get("align", "left")
            left = x - tw / 2 if al == "center" else (x - tw if al == "right" else x)
            txt = ft.Text("\n".join(lines), size=px * sz * S * 0.82, color=col, no_wrap=True,
                          weight=ft.FontWeight.BOLD if w.get("font") in ("sans", "sans24", "seg7") else None,
                          font_family="Consolas" if w.get("font") == "seg7" else None,
                          text_align={"center": ft.TextAlign.CENTER, "right": ft.TextAlign.RIGHT}.get(al, ft.TextAlign.LEFT))
            al_box = {"center": ft.Alignment.TOP_CENTER, "right": ft.Alignment.TOP_RIGHT}.get(al, ft.Alignment.TOP_LEFT)
            c = ft.Container(content=txt, width=tw * S, height=th * S, alignment=al_box, bgcolor=w.get("bgcolor"))
            return wrap(i, c, left * S, y * S)
        if t == "rect":
            ww, hh, r = num(w.get("w"), 10), num(w.get("h"), 10), num(w.get("radius"))
            fill = w.get("fill", False)
            c = ft.Container(width=ww * S, height=hh * S, border_radius=r * S, bgcolor=col if fill else None,
                             border=None if fill else ft.Border.all(max(1, S), col))
            return wrap(i, c, x * S, y * S)
        if t == "circle":
            r = num(w.get("r"), 10)
            fill = w.get("fill", False)
            c = ft.Container(width=2 * r * S, height=2 * r * S, shape=ft.BoxShape.CIRCLE, bgcolor=col if fill else None,
                             border=None if fill else ft.Border.all(max(1, S), col))
            return wrap(i, c, (x - r) * S, (y - r) * S)
        if t == "line":
            x2, y2, th = num(w.get("x2")), num(w.get("y2")), max(1, num(w.get("thick"), 1))
            lx, ly = min(x, x2) - th, min(y, y2) - th
            bw, bh = abs(x2 - x) + 2 * th, abs(y2 - y) + 2 * th
            canvas = cv.Canvas(width=bw * S, height=bh * S, shapes=[
                cv.Line((x - lx) * S, (y - ly) * S, (x2 - lx) * S, (y2 - ly) * S,
                        paint=ft.Paint(color=col, stroke_width=th * S))])
            return wrap(i, ft.Container(content=canvas, width=bw * S, height=bh * S), lx * S, ly * S)
        if t == "bar":
            ww, hh, r = num(w.get("w"), 100), num(w.get("h"), 10), num(w.get("radius"))
            v, mx = num(expand(w.get("value", "0"), st["ctx"])), num(w.get("max"), 100) or 1
            fw = max(0, min(ww, ww * v / mx))
            c = ft.Stack(width=ww * S, height=hh * S, controls=[
                ft.Container(width=ww * S, height=hh * S, bgcolor=w.get("bg", "#333333"), border_radius=r * S),
                ft.Container(width=fw * S, height=hh * S, bgcolor=col, border_radius=r * S)])
            return wrap(i, c, x * S, y * S)
        if t == "clock":
            r = num(w.get("r"), 60)
            now = datetime.datetime.now()
            import math
            c0 = r * S
            shapes = []
            if w.get("fill"):
                shapes.append(cv.Circle(c0, c0, c0, paint=ft.Paint(color=w["fill"], style=ft.PaintingStyle.FILL)))
            shapes.append(cv.Circle(c0, c0, c0 - 1, paint=ft.Paint(color=col, style=ft.PaintingStyle.STROKE, stroke_width=1)))
            for k in range(12):
                a = k * math.pi / 6
                l = r / 6 if k % 3 == 0 else r / 12
                shapes.append(cv.Line(c0 + math.sin(a) * (r - l) * S, c0 - math.cos(a) * (r - l) * S,
                                      c0 + math.sin(a) * (r - 2) * S, c0 - math.cos(a) * (r - 2) * S,
                                      paint=ft.Paint(color=col, stroke_width=1)))
            hand = w.get("hand", "#ffffff")
            for ang, ln, wd, cc in (((now.hour % 12 + now.minute / 60) * math.pi / 6, 0.5, max(3, r / 15), hand),
                                    ((now.minute + now.second / 60) * math.pi / 30, 0.75, max(2, r / 22), hand)):
                shapes.append(cv.Line(c0, c0, c0 + math.sin(ang) * r * ln * S, c0 - math.cos(ang) * r * ln * S,
                                      paint=ft.Paint(color=cc, stroke_width=wd * S * 0.6)))
            if w.get("seconds", True):
                a = now.second * math.pi / 30
                shapes.append(cv.Line(c0, c0, c0 + math.sin(a) * r * 0.85 * S, c0 - math.cos(a) * r * 0.85 * S,
                                      paint=ft.Paint(color=w.get("sec", "#ef4444"), stroke_width=1)))
            shapes.append(cv.Circle(c0, c0, max(2, r / 20) * S, paint=ft.Paint(color=w.get("sec", "#ef4444"))))
            canvas = cv.Canvas(width=2 * c0, height=2 * c0, shapes=shapes)
            return wrap(i, ft.Container(content=canvas, width=2 * c0, height=2 * c0), (x - r) * S, (y - r) * S)
        if t == "image":
            ww, hh = num(w.get("w"), 100), num(w.get("h"), 100)
            data = st["img"].get(w.get("file"))
            inner = (ft.Image(src=data, width=ww * S, height=hh * S, fit=ft.BoxFit.CONTAIN) if data
                     else ft.Text(w.get("file") or "이미지", size=11, color="#94a3b8"))
            c = ft.Container(content=inner, width=ww * S, height=hh * S, alignment=ft.Alignment.CENTER,
                             bgcolor=None if data else "#1f2937")
            return wrap(i, c, x * S, y * S)
        return None

    bg_layer = ft.Container(on_click=lambda e: select(None))
    slots = []
    preview.controls.append(bg_layer)

    def refresh_preview():
        S = scale()
        preview.width, preview.height = st["w"] * S, st["h"] * S
        bg_layer.width, bg_layer.height = st["w"] * S, st["h"] * S
        bg_layer.bgcolor = st["layout"].get("bg", "#000000")
        items = [draw_widget(i, w, S) for i, w in enumerate(st["layout"]["widgets"])]
        while len(slots) < len(items):
            k = len(slots)
            g = ft.GestureDetector(drag_interval=16, mouse_cursor=ft.MouseCursor.MOVE,
                                   on_tap=lambda e, k=k: select(k), on_pan_update=mover(k))
            slots.append(g)
            preview.controls.append(g)
        for k, g in enumerate(slots):
            if k < len(items) and items[k]:
                g.content, g.left, g.top = items[k]
                g.visible = True
            else:
                g.visible = False
        preview.update()

    # ───────── 위젯 목록 ─────────
    widget_list = ft.Column(spacing=2)

    def label_of(w):
        t = TYPE_NAMES.get(w.get("type"), w.get("type"))
        extra = w.get("text") or w.get("file") or w.get("value") or ""
        return f"{t}  {str(extra)[:22]}"

    def move(i, d):
        ws = st["layout"]["widgets"]
        j = i + d
        if not (0 <= j < len(ws)):
            return
        ws[i], ws[j] = ws[j], ws[i]
        st["sel"] = j
        build_list()
        build_props()
        refresh_preview()

    def dup(i):
        w = copy.deepcopy(st["layout"]["widgets"][i])
        w["x"] = num(w.get("x")) + 10
        w["y"] = num(w.get("y")) + 10
        st["layout"]["widgets"].insert(i + 1, w)
        select(i + 1)

    def delete(i):
        st["layout"]["widgets"].pop(i)
        st["sel"] = None
        build_props()
        build_list()
        refresh_preview()

    def build_list():
        rows = []
        for i, w in enumerate(st["layout"]["widgets"]):
            sel = st["sel"] == i
            rows.append(ft.Container(
                bgcolor="#1e3a5f" if sel else "#1b1f27", border_radius=6, padding=ft.Padding.only(left=10),
                on_click=lambda e, i=i: select(i),
                content=ft.Row([
                    ft.Text(label_of(w), expand=True, size=13, no_wrap=True),
                    ft.IconButton(ft.Icons.ARROW_UPWARD, icon_size=16, tooltip="뒤로 (먼저 그림)", on_click=lambda e, i=i: move(i, -1)),
                    ft.IconButton(ft.Icons.ARROW_DOWNWARD, icon_size=16, tooltip="앞으로 (나중에 그림)", on_click=lambda e, i=i: move(i, 1)),
                    ft.IconButton(ft.Icons.COPY, icon_size=16, tooltip="복제", on_click=lambda e, i=i: dup(i)),
                    ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=16, tooltip="삭제", on_click=lambda e, i=i: delete(i)),
                ], spacing=0)))
        if not rows:
            rows.append(ft.Text("위젯이 없어요. 위의 버튼으로 추가하세요.", color="#94a3b8", size=12))
        widget_list.controls = rows
        widget_list.update()

    # ───────── 속성 ─────────
    props = ft.Column(spacing=8)
    xy_fields = {}

    def sync_xy():
        # 끌어서 옮길 때 X/Y 칸도 같이 바꿔줌
        if st["sel"] is None:
            return
        w = st["layout"]["widgets"][st["sel"]]
        for k, f in xy_fields.items():
            if k in w:
                f.value = str(w[k])
                f.update()

    def color_field(w, k):
        swatch = ft.Container(width=28, height=28, border_radius=6, bgcolor=w.get(k) or "#00000000",
                              border=ft.Border.all(1, "#475569"))
        tf = ft.TextField(value=w.get(k, ""), label=LABELS[k], width=130, dense=True)

        def set_color(v):
            v = v.strip()
            if v and not v.startswith("#"):
                v = "#" + v
            if v == "" and k == "bgcolor":
                w.pop(k, None)
            elif re.fullmatch(r"#[0-9a-fA-F]{6}", v):
                w[k] = v.lower()
            else:
                return
            swatch.bgcolor = w.get(k) or "#00000000"
            swatch.update()
            refresh_preview()

        def pick(c):
            tf.value = c
            tf.update()
            set_color(c)

        tf.on_change = lambda e: set_color(tf.value)
        dots = [ft.Container(width=18, height=18, bgcolor=c, border_radius=9, border=ft.Border.all(1, "#475569"),
                             on_click=lambda e, c=c: pick(c)) for c in PALETTE]
        return ft.Column([ft.Row([tf, swatch]), ft.Row(dots, spacing=4, wrap=True)], spacing=4)

    def build_props():
        xy_fields.clear()
        i = st["sel"]
        if i is None or i >= len(st["layout"]["widgets"]):
            props.controls = [ft.Text("화면 배경", weight=ft.FontWeight.BOLD), bg_field(),
                              ft.Text("미리보기에서 위젯을 누르면 여기서 수정할 수 있어요.", size=12, color="#94a3b8")]
            props.update()
            return
        w = st["layout"]["widgets"][i]
        ctrls = [ft.Text(TYPE_NAMES.get(w.get("type"), "위젯"), weight=ft.FontWeight.BOLD, size=16)]
        num_row = []
        keys = [k for k in FIELD_ORDER if k in w or (k == "bgcolor" and w.get("type") == "text")]
        for k in keys:
            if k in NUMERIC:
                tf = ft.TextField(value=str(w.get(k, "")), label=LABELS[k], width=92, dense=True,
                                  keyboard_type=ft.KeyboardType.NUMBER)

                def on_num(e, k=k, tf=tf):
                    try:
                        w[k] = num(tf.value) if k != "size" else float(tf.value)
                        refresh_preview()
                    except ValueError:
                        pass

                tf.on_change = on_num
                if k in ("x", "y", "x2", "y2"):
                    xy_fields[k] = tf
                num_row.append(tf)
            elif k in COLORS:
                ctrls.append(color_field(w, k))
            elif k == "font":
                dd = ft.Dropdown(label="글꼴", value=w.get(k, "kr16"), width=230, dense=True,
                                 options=[ft.DropdownOption(key=f, text=v[0]) for f, v in FONTS.items()])
                dd.on_select = lambda e, dd=dd: (w.__setitem__("font", dd.value), refresh_preview())
                ctrls.append(dd)
            elif k == "align":
                dd = ft.Dropdown(label="정렬 (X 기준)", value=w.get(k, "left"), width=160, dense=True,
                                 options=[ft.DropdownOption(key=a, text=t) for a, t in ALIGNS.items()])
                dd.on_select = lambda e, dd=dd: (w.__setitem__("align", dd.value), refresh_preview())
                ctrls.append(dd)
            elif k in ("fill", "seconds"):
                sw = ft.Switch(label=LABELS[k], value=bool(w.get(k)))
                sw.on_change = lambda e, k=k, sw=sw: (w.__setitem__(k, sw.value), refresh_preview())
                ctrls.append(sw)
            elif k == "file":
                dd = ft.Dropdown(label="보드에 있는 이미지", value=w.get(k), width=230, dense=True,
                                 options=[ft.DropdownOption(key=f["name"], text=f["name"]) for f in st["files"]])

                async def on_file(e, dd=dd):
                    w["file"] = dd.value
                    await load_image(dd.value)
                    refresh_preview()

                dd.on_select = on_file
                ctrls.append(dd)
            else:
                tf = ft.TextField(value=str(w.get(k, "")), label=LABELS[k], multiline=k == "text",
                                  min_lines=1, max_lines=4, dense=True)
                tf.on_change = lambda e, k=k, tf=tf: (w.__setitem__(k, tf.value), refresh_preview(), build_list())
                ctrls.append(tf)
        if num_row:
            ctrls.append(ft.Row(num_row, wrap=True, spacing=6))
        if w.get("type") in ("text", "bar"):
            ctrls.append(ft.Container(ft.Text(HELP, size=11, color="#94a3b8", selectable=True),
                                      bgcolor="#111827", padding=8, border_radius=6))
        props.controls = ctrls
        props.update()

    def bg_field():
        lay = st["layout"]
        holder = {"color": lay.get("bg", "#000000")}
        col = color_field(holder, "color")
        tf = col.controls[0].controls[0]
        tf.label = "배경색"

        def on_bg(e):
            v = tf.value.strip()
            if re.fullmatch(r"#?[0-9a-fA-F]{6}", v):
                lay["bg"] = ("#" + v.lstrip("#")).lower()
                refresh_preview()

        tf.on_change = on_bg
        for d in col.controls[1].controls:
            orig = d.on_click

            def click(e, orig=orig):
                orig(e)
                lay["bg"] = holder["color"]
                refresh_preview()

            d.on_click = click
        return col

    def fit(w):
        # 프리셋은 240x320 기준 -> 보드 화면 크기에 맞춰 위치/크기 조정
        kx, ky = st["w"] / 240, st["h"] / 320
        if kx == 1 and ky == 1:
            return w
        k = min(kx, ky)
        for key in ("x", "x2", "w"):
            if key in w:
                w[key] = round(num(w[key]) * kx)
        for key in ("y", "y2", "h"):
            if key in w:
                w[key] = round(num(w[key]) * ky)
        if "r" in w:
            w["r"] = max(4, round(num(w["r"]) * k))
        if w.get("type") == "text" and k < 0.8:
            if w.get("font") == "seg7":
                w["size"] = round(num(w.get("size"), 1) * 0.75, 2)
            elif w.get("font") == "kr24":
                if num(w.get("size"), 1) > 1:
                    w["size"] = round(num(w.get("size"), 1) * 0.65, 2)
                else:
                    w["font"] = "kr16"
        return w

    def add_widget(name):
        st["layout"]["widgets"].append(fit(copy.deepcopy(PRESETS[name])))
        select(len(st["layout"]["widgets"]) - 1)

    async def load_image(name):
        if not name or name in st["img"] or not ble.connected:
            return
        data = await asyncio.to_thread(lambda: _try(lambda: dev().file(name)))
        if data:
            st["img"][name] = data

    def _try(fn):
        try:
            return fn()
        except Exception:
            return None

    async def upload_image(e):
        files = await picker.pick_files(dialog_title="LCD에 올릴 이미지",
                                        allowed_extensions=["jpg", "jpeg", "png", "bmp", "webp", "gif"],
                                        file_type=ft.FilePickerFileType.CUSTOM, with_data=True)
        if not files:
            return
        f = files[0]
        data = f.bytes
        if data is None and f.path:
            with open(f.path, "rb") as fh:
                data = fh.read()
        if not data:
            toast("파일을 읽지 못했어요", True)
            return
        name = safe_name(f.name)
        bg = st["layout"].get("bg", "#000000")
        try:
            data, name, w, h = await asyncio.to_thread(prepare_image, data, name, st["w"], st["h"], bg)
        except DeviceError as ex:
            toast(str(ex), True)
            return
        if len(data) > 600000:
            toast(f"이미지가 너무 커요 ({len(data) // 1024}KB). 600KB 이하로 줄여주세요.", True)
            return
        r = await run_net(f"이미지 업로드 ({len(data) // 1024}KB)", dev().upload, name, data)
        if not r:
            return
        name = r.get("name", name)
        st["img"][name] = data
        await refresh_files()
        st["layout"]["widgets"].append({"type": "image", "x": max(0, (st["w"] - w) // 2), "y": max(0, (st["h"] - h) // 2),
                                        "w": w, "h": h, "file": name})
        select(len(st["layout"]["widgets"]) - 1)

    async def refresh_files():
        r = await run_net("파일 목록", dev().files)
        if r is None:
            return False
        st["files"] = r.get("files", [])
        used, total = r.get("fs_used", 0), r.get("fs_total", 1)
        files_text.value = f"보드 저장공간 {used // 1024}/{total // 1024}KB · 이미지 {len(st['files'])}개"
        files_text.update()
        return True

    files_text = ft.Text("", size=12, color="#94a3b8")

    async def manage_files(e):
        if not await refresh_files():
            return

        async def remove(name):
            if await run_net(f"{name} 삭제", dev().delete_file, name):
                st["img"].pop(name, None)
                page.pop_dialog()
                await manage_files(None)

        def remove_all(e):
            names = [f["name"] for f in st["files"]]
            if not names:
                toast("삭제할 이미지가 없어요")
                return

            async def go():
                failed = []
                for index, name in enumerate(names, 1):
                    toast(f"사진 삭제 중 {index}/{len(names)}: {name}")
                    if await run_net(f"{name} 삭제", dev().delete_file, name):
                        st["img"].pop(name, None)
                    else:
                        failed.append(name)
                        break  # 연결이나 응답 문제가 있으면 나머지는 유지한다.
                page.pop_dialog()
                await manage_files(None)
                deleted = index if not failed else index - 1
                toast(f"{deleted}개 삭제 완료" + (f". {failed[0]} 삭제 실패로 중단했어요. 목록을 확인하세요." if failed else ""), bool(failed))

            confirm("사진 모두 삭제", f"보드에 저장된 사진 {len(names)}개를 모두 삭제할까요?\n복구할 수 없어요.", go)

        items = [ft.Row([ft.Text(f"{f['name']}  ({f['size'] // 1024}KB)", expand=True),
                         ft.IconButton(ft.Icons.DELETE_OUTLINE, on_click=lambda e, n=f["name"]: page.run_task(remove, n))])
                 for f in st["files"]] or [ft.Text("보드에 이미지가 없어요")]
        page.show_dialog(ft.AlertDialog(title=ft.Text("보드의 이미지"),
                                        content=ft.Column(items, tight=True, scroll=ft.ScrollMode.AUTO),
                                        actions=[ft.TextButton("사진 모두 삭제", on_click=remove_all),
                                                 ft.TextButton("닫기", on_click=lambda e: page.pop_dialog())]))

    # ───────── 페이지 (화면 여러 개, 펌웨어 v1.8+) ─────────
    page_dd = ft.Dropdown(label="편집할 페이지", width=150, dense=True, value="0",
                          options=[ft.DropdownOption(key="0", text="0")])

    def update_page_dd():
        cur = st.get("board_page")
        page_dd.options = [ft.DropdownOption(key=str(n), text=f"{n}" + (" (LCD)" if n == cur else ""))
                           for n in st["pages"]]
        if st["page"] not in st["pages"]:
            page_dd.options.append(ft.DropdownOption(key=str(st["page"]), text=f"{st['page']} (새로)"))
        page_dd.value = str(st["page"])
        page_dd.update()

    async def refresh_pages():
        r = await asyncio.to_thread(lambda: _try(lambda: dev().pages()))
        if not r:
            return
        st["pages"] = r.get("pages", [0])
        st["max_pages"] = r.get("max", 1)
        st["board_page"] = r.get("current", 0)
        update_page_dd()

    async def load_page(n):
        lay = await run_net(f"페이지 {n} 불러오기", dev().layout, n)
        if lay and "widgets" in lay:
            st["layout"] = lay
            st["page"] = n
            st["sel"] = None
            for w in st["layout"]["widgets"]:
                if w.get("type") == "image":
                    await load_image(w.get("file"))
            update_page_dd()
            build_props()
            build_list()
            refresh_preview()

    async def on_page_select(e):
        n = int(page_dd.value)
        if n in st["pages"]:
            await load_page(n)

    page_dd.on_select = on_page_select

    async def show_page_on_lcd(e):
        if st["page"] not in st["pages"]:
            toast("먼저 'LCD로 보내기'로 이 페이지를 저장하세요", True)
            return
        if await run_net(f"LCD에 페이지 {st['page']} 띄우기", dev().set_page, st["page"]):
            await refresh_pages()

    async def new_page(e):
        await refresh_pages()
        free = [n for n in range(st["max_pages"]) if n not in st["pages"]]
        if not free:
            toast(f"페이지는 최대 {st['max_pages']}개예요", True)
            return
        st["page"] = free[0]
        st["layout"] = {"bg": "#0b1020", "widgets": []}
        st["sel"] = None
        update_page_dd()
        build_props()
        build_list()
        refresh_preview()
        toast(f"페이지 {st['page']}를 만들었어요. 꾸민 뒤 'LCD로 보내기'를 누르면 저장돼요")

    def confirm(title, msg, on_yes):
        async def yes(e):
            page.pop_dialog()
            await on_yes()

        page.show_dialog(ft.AlertDialog(title=ft.Text(title), content=ft.Text(msg), actions=[
            ft.TextButton("취소", on_click=lambda e: page.pop_dialog()),
            ft.FilledButton("삭제", on_click=yes, style=ft.ButtonStyle(bgcolor="#b91c1c"))]))

    def delete_page(e):
        n = st["page"]
        if n == 0:
            toast("0번 페이지는 지울 수 없어요 (모든 페이지 삭제를 쓰면 기본 화면으로 돌아가요)", True)
            return

        async def go():
            if n in st["pages"] and not await run_net(f"페이지 {n} 삭제", dev().delete_page, n):
                return
            await refresh_pages()
            await load_page(0)

        confirm("페이지 삭제", f"{n}번 페이지를 지울까요?", go)

    def delete_all_pages(e):
        async def go():
            if not await run_net("모든 페이지 삭제", dev().delete_all_pages):
                return
            await refresh_pages()
            await load_page(0)
            toast("모든 페이지를 지웠어요. 0번은 기본 화면으로 돌아갔어요")

        confirm("모든 페이지 삭제", "1~4번 페이지를 모두 지우고 0번 페이지는 기본 화면으로 되돌려요.\n되돌릴 수 없어요.", go)

    def delete_all_widgets(e):
        if not st["layout"]["widgets"]:
            toast("삭제할 위젯이 없어요")
            return

        async def go():
            st["layout"]["widgets"].clear()
            st["sel"] = None
            build_props()
            build_list()
            refresh_preview()
            toast("현재 페이지의 위젯을 모두 지웠어요. LCD에 적용하려면 'LCD로 보내기'를 누르세요")

        confirm("위젯 모두 삭제", "현재 편집 중인 페이지의 위젯을 모두 지울까요?", go)

    # ───────── 연결 (블루투스) / 보내기 / 대화상자 ─────────
    # 보드와는 블루투스로만 통신. WiFi는 펌웨어 업데이트(OTA) 때만 (펌웨어 v2.1+)
    board_dd = ft.Dropdown(label="보드 (블루투스)", width=210, dense=True, options=[])

    async def do_scan(e):
        status.value = "블루투스로 보드를 찾는 중... (5초)"
        status.update()
        try:
            found = await ble.scan(5)
        except BleError as ex:
            status.value = f"찾기 실패: {ex}"
            status.update()
            return
        if not found:
            status.value = "보드를 못 찾았어요. 보드가 켜져 있는지(꺼졌으면 버튼 누르기), 다른 기기(PC 앱 등)가 연결 중인지, 휴대폰은 블루투스·위치(GPS)가 켜져 있고 근처 기기·위치 권한을 허용했는지 확인하세요."
            status.update()
            return
        board_dd.options = [ft.DropdownOption(key=a, text=n) for a, n in found]
        board_dd.value = found[0][0]
        board_dd.update()
        if len(found) == 1:
            await connect(None)
        else:
            status.value = f"{len(found)}개 찾음 - 고른 뒤 '연결'을 누르세요"
            status.update()

    async def connect(e):
        if not board_dd.value:
            await do_scan(None)
            return
        name = next((o.text for o in board_dd.options if o.key == board_dd.value), board_dd.value)
        status.value = f"{name} 블루투스 연결 중..."
        status.update()
        try:
            await ble.close()
            await ble.connect(board_dd.value, name)
        except BleError as ex:
            status.value = f"연결 실패: {ex}"
            status.update()
            toast(f"연결 실패: {ex}", True)
            return
        await pref_set("ble_addr", board_dd.value)
        await pref_set("ble_name", name)
        info = await run_net("정보 불러오기", dev().info)
        if not info:
            return
        st["ctx"].update(ip=info.get("ip"), ssid=info.get("ssid"), name=info.get("name"))
        sensor = info.get("ntc")
        st["ctx"]["ntc"] = f"{sensor:.1f}" if isinstance(sensor, (int, float)) else "--"
        # 보드는 평소 인터넷이 없어서 시간/날씨를 이 기기에서 넣어줌
        await run_net("시간 맞추기", dev().set_time, time.time())
        wt = await asyncio.to_thread(fetch_weather)
        if wt:
            await run_net("날씨 보내기", dev().set_weather, *wt)
            info["weather"] = {"temp": wt[0], "desc": WEATHER_DESC(wt[1]), "city": wt[2]}
        wt = info.get("weather") or {}
        if wt:
            st["ctx"].update(wtemp=f"{wt.get('temp', 0):.1f}", wdesc=wt.get("desc", "-"), city=wt.get("city", "-"))
        st["w"], st["h"] = info.get("w", 240), info.get("h", 320)
        await refresh_pages()
        st["page"] = st.get("board_page", 0)
        lay = await run_net("화면 불러오기", dev().layout, st["page"] if "pages" in info else None)
        if lay and "widgets" in lay:
            st["layout"] = lay
            st["sel"] = None
        st["settings"] = await run_net("설정 불러오기", dev().settings) or {}
        await refresh_files()
        for w in st["layout"]["widgets"]:
            if w.get("type") == "image":
                await load_image(w.get("file"))
        bat = f" · 배터리 {info.get('bat', 0):.2f}V" if "bat" in info else ""
        status.value = f"연결됨 (블루투스): {info.get('name')} {info.get('version')} · {st['w']}x{st['h']}{bat}"
        status.update()
        update_page_dd()
        build_props()
        build_list()
        refresh_preview()

    async def send(e):
        n = st["page"] if st["max_pages"] > 1 else None
        if await run_net("LCD로 보내기" + (f" (페이지 {n})" if n is not None else ""), dev().set_layout, st["layout"], n):
            await pref_set("layout", json.dumps(st["layout"], ensure_ascii=False))
            if n is not None and n not in st["pages"]:
                await refresh_pages()
            toast("LCD에 적용했어요")

    async def sync_time(e):
        if await run_net("시간 맞추기", dev().set_time, time.time()):
            toast("보드 시간을 이 기기 시간으로 맞췄어요")

    async def show_screen(e):
        data = await run_net("실제 화면 가져오기", dev().screenshot)
        if not data:
            return
        page.show_dialog(ft.AlertDialog(
            title=ft.Text("LCD 실제 화면"),
            content=ft.Image(src=data, width=st["w"] * 1.5, height=st["h"] * 1.5, fit=ft.BoxFit.CONTAIN),
            actions=[ft.TextButton("닫기", on_click=lambda e: page.pop_dialog())]))

    async def settings_dialog(e):
        s = dict(st["settings"] or await run_net("설정 불러오기", dev().settings) or {})
        name = ft.TextField(label="이름 (mDNS: 이름.local)", value=s.get("name", "lcd"), dense=True)
        rot = ft.Dropdown(label="화면 방향", value=str(s.get("rotation", 0)), dense=True, options=[
            ft.DropdownOption(key=str(k), text=t) for k, t in ((0, "세로 0°"), (1, "가로 90°"), (2, "세로 180°"), (3, "가로 270°"))])
        bri = ft.Slider(min=0, max=255, value=s.get("brightness", 200), label="{value}", divisions=51)
        inv = ft.Switch(label="색 반전 (화면이 반전돼 보이면 바꾸기)", value=s.get("invert", False))
        bgr = ft.Switch(label="빨강/파랑 바꾸기 (재부팅 후 적용)", value=s.get("bgr", False))
        offx = ft.TextField(label="X 오프셋", value=str(s.get("offx", 0)), width=100, dense=True)
        offy = ft.TextField(label="Y 오프셋", value=str(s.get("offy", 0)), width=100, dense=True)
        tz = ft.TextField(label="시간대 (한국 KST-9)", value=s.get("tz", "KST-9"), dense=True)
        ntp = ft.TextField(label="시간 서버", value=s.get("ntp", "pool.ntp.org"), dense=True)
        idle = ft.TextField(label="자동 끄기 (분, 0=안 함)", value=str(s.get("idle_min", 5)), width=160, dense=True)

        async def save(e):
            new = {"name": name.value.strip() or "lcd", "rotation": int(rot.value), "brightness": int(bri.value),
                   "invert": inv.value, "bgr": bgr.value, "offx": num(offx.value), "offy": num(offy.value),
                   "tz": tz.value.strip() or "KST-9", "ntp": ntp.value.strip() or "pool.ntp.org"}
            if "idle_min" in s:
                new["idle_min"] = int(num(idle.value, 5))
            r = await run_net("설정 저장", dev().set_settings, new)
            if r:
                st["settings"] = new
                page.pop_dialog()
                if r.get("reboot"):
                    toast("일부 설정은 재부팅해야 적용돼요 (설정 → 재부팅)")
                await connect(None)

        async def reboot(e):
            await run_net("재부팅", dev().reboot)
            page.pop_dialog()

        ctrls = [name, rot, ft.Text("밝기"), bri, inv, bgr, ft.Row([offx, offy]), tz, ntp]
        if "idle_min" in s:
            ctrls.append(idle)
        page.show_dialog(ft.AlertDialog(
            title=ft.Text("화면 설정"),
            content=ft.Column(ctrls, tight=True, scroll=ft.ScrollMode.AUTO, width=340),
            actions=[ft.TextButton("재부팅", on_click=reboot), ft.TextButton("취소", on_click=lambda e: page.pop_dialog()),
                     ft.FilledButton("저장", on_click=save)]))

    async def wifi_dialog(e):
        ssid = ft.TextField(label="WiFi 이름 (SSID)", dense=True)
        pw = ft.TextField(label="비밀번호", password=True, can_reveal_password=True, dense=True)

        async def save(e):
            if not ssid.value.strip():
                return
            await run_net("WiFi 저장", dev().set_wifi, ssid.value.strip(), pw.value)
            await ble.close()
            page.pop_dialog()
            toast("저장했어요. 보드가 재시작해요 - 몇 초 뒤 '연결'을 다시 누르세요.")

        page.show_dialog(ft.AlertDialog(
            title=ft.Text("보드 WiFi (펌웨어 업데이트용)"),
            content=ft.Column([ft.Text("보드는 평소 WiFi를 끄고 블루투스로만 통신해요.\n"
                                       "여기 저장한 WiFi는 '펌웨어 업데이트' 할 때만 잠깐 켜요.\n"
                                       "(이 기기도 같은 WiFi에 있어야 업데이트돼요)",
                                       size=12, color="#94a3b8"), ssid, pw], tight=True, width=340),
            actions=[ft.TextButton("취소", on_click=lambda e: page.pop_dialog()), ft.FilledButton("저장", on_click=save)]))

    async def vars_dialog(e):
        key = ft.TextField(label="이름 (예: cpu)", width=140, dense=True)
        val = ft.TextField(label="값 (예: 37)", width=140, dense=True)

        async def send_var(e):
            if not key.value.strip():
                return
            if await run_net("변수 보내기", dev().set_vars, {key.value.strip(): val.value}):
                st["ctx"]["vars"][key.value.strip()] = val.value
                refresh_preview()
                toast(f"{{var:{key.value.strip()}}} = {val.value}")

        page.show_dialog(ft.AlertDialog(
            title=ft.Text("변수 보내기"),
            content=ft.Column([ft.Text("글자에 {var:이름} 을 넣어두면 여기서 보낸 값이 표시돼요.\n"
                                       "보드에는 블루투스로 보내요 (이 앱이 연결돼 있을 때).",
                                       size=12, color="#94a3b8", selectable=True), ft.Row([key, val])], tight=True, width=340),
            actions=[ft.TextButton("닫기", on_click=lambda e: page.pop_dialog()), ft.FilledButton("보내기", on_click=send_var)]))

    def json_dialog(e):
        tf = ft.TextField(value=json.dumps(st["layout"], ensure_ascii=False, indent=1), multiline=True,
                          min_lines=12, max_lines=20, text_size=12, width=420)

        def apply(e):
            try:
                lay = json.loads(tf.value)
                assert isinstance(lay.get("widgets"), list)
            except Exception:
                toast("JSON 형식이 잘못됐어요", True)
                return
            st["layout"] = lay
            st["sel"] = None
            page.pop_dialog()
            build_props()
            build_list()
            refresh_preview()

        page.show_dialog(ft.AlertDialog(
            title=ft.Text("화면 JSON (복사해서 보관 / 붙여넣어 불러오기)"), content=tf,
            actions=[ft.TextButton("닫기", on_click=lambda e: page.pop_dialog()), ft.FilledButton("적용", on_click=apply)]))

    def reset_layout(e):
        st["layout"] = copy.deepcopy(DEFAULT_LAYOUT)
        st["layout"]["widgets"] = [fit(w) for w in st["layout"]["widgets"]]
        st["sel"] = None
        build_props()
        build_list()
        refresh_preview()

    # ───────── 리모컨 (블루투스로 바로 조종) ─────────
    async def remote_dialog(e):
        if not ble.connected:
            toast("먼저 '찾기' → '연결'로 보드에 블루투스 연결하세요", True)
            return
        state = ft.Text("", size=13)
        bri = ft.Slider(min=0, max=255, divisions=51, label="{value}", value=200)
        page_row = ft.Row(wrap=True, spacing=4)

        def show_status(s):
            if not s:
                return
            bat = f"  배터리 {'충전 중' if s.get('chg') else str(s.get('pct', '-')) + '%'} ({s.get('bat', '-')}V)" if "bat" in s else ""
            state.value = f"{s.get('ver', '')}  화면 {s.get('page', 0)}{bat}"
            bri.value = s.get("bri", bri.value)
            page_row.controls = [ft.OutlinedButton(f"{n}", on_click=lambda e, n=n: page.run_task(cmd, {"c": "page", "n": n}))
                                 for n in range(max(1, s.get("pages", 1)))]
            page.update()

        async def cmd(c):
            try:
                show_status(await ble.send(c))
            except BleError as ex:
                toast(f"블루투스: {ex}", True)

        async def on_bri(e):
            await cmd({"c": "bri", "v": int(bri.value)})

        bri.on_change_end = on_bri
        page.show_dialog(ft.AlertDialog(
            title=ft.Text("리모컨"),
            content=ft.Column([
                state,
                ft.Row([ft.OutlinedButton("◀ 이전 화면", on_click=lambda e: page.run_task(cmd, {"c": "prev"})),
                        ft.FilledButton("다음 화면 ▶", on_click=lambda e: page.run_task(cmd, {"c": "next"}))], wrap=True),
                ft.Text("화면 바로 가기", size=12, color="#94a3b8"), page_row,
                ft.Text("밝기", size=12, color="#94a3b8"), bri,
                ft.Row([ft.OutlinedButton("새로고침", icon=ft.Icons.REFRESH, on_click=lambda e: page.run_task(cmd, {"c": "status"})),
                        ft.OutlinedButton("재시작", icon=ft.Icons.RESTART_ALT, on_click=lambda e: page.run_task(cmd, {"c": "reboot"}))],
                       wrap=True),
                ft.FilledButton("끄기 (딥슬립)", icon=ft.Icons.POWER_SETTINGS_NEW, style=ft.ButtonStyle(bgcolor="#b91c1c"),
                                on_click=lambda e: page.run_task(cmd, {"c": "off"})),
            ], tight=True, scroll=ft.ScrollMode.AUTO, width=360),
            actions=[ft.TextButton("닫기", on_click=lambda e: page.pop_dialog())]))
        await cmd({"c": "status"})

    # ───────── 펌웨어 업데이트 (이때만 WiFi) ─────────
    async def firmware_update(e):
        if not ble.connected:
            toast("먼저 블루투스로 연결하세요 (업데이트 모드로 바꾸는 데 필요해요)", True)
            return
        files = await picker.pick_files(dialog_title="펌웨어 (.bin) 고르기", allowed_extensions=["bin"],
                                        file_type=ft.FilePickerFileType.CUSTOM, with_data=True)
        if not files:
            return
        f = files[0]
        data = f.bytes
        if data is None and f.path:
            with open(f.path, "rb") as fh:
                data = fh.read()
        if not data or data[:1] != b"\xe9":
            toast("ESP32 펌웨어(.bin) 파일이 아니에요 (merged.bin 말고 lcdpanel.ino.bin)", True)
            return
        msg = ft.Text("1/4 보드를 업데이트 모드로 바꾸는 중...", size=13)
        prog = ft.ProgressBar(width=320)
        page.show_dialog(ft.AlertDialog(title=ft.Text("펌웨어 업데이트"), modal=True,
                                        content=ft.Column([msg, prog], tight=True, width=340)))

        def say(t):
            msg.value = t
            page.update()

        try:
            await ble.send({"c": "ota"})
        except BleError:
            pass
        await ble.close()
        say("2/4 보드가 WiFi에 연결할 때까지 기다리는 중... (최대 1분)")
        s, addr = {}, board_dd.value
        for _ in range(12):
            await asyncio.sleep(4)
            try:
                s = await ble.connect(addr, ble.name)
                if s.get("ota") and s.get("ip") not in (None, "", "-", "0.0.0.0"):
                    break
                await ble.close()
            except BleError:
                pass
        if not s.get("ota"):
            page.pop_dialog()
            toast("보드가 업데이트 모드로 안 바뀌었어요. 다시 시도하세요", True)
            return
        ip = s["ip"]
        await ble.close()
        if s.get("ap"):
            say(f"3/4 보드가 저장된 WiFi에 못 붙어서 설정용 WiFi를 열었어요.\n이 기기를 'LCD-Setup-XXXX' WiFi에 연결한 뒤 기다리세요... ({ip})")
        else:
            say(f"3/4 WiFi로 펌웨어 보내는 중... ({len(data) // 1024}KB → {ip})\n이 기기도 같은 WiFi에 있어야 해요")
        r = None
        for _ in range(5 if s.get("ap") else 1):
            try:
                r = await asyncio.to_thread(Device(ip).ota, data)
                break
            except DeviceError as ex:
                r = ex
                await asyncio.sleep(8)
        if not isinstance(r, dict) or not r.get("ok"):
            page.pop_dialog()
            toast(f"업로드 실패: {r} (보드는 10분 뒤 원래대로 돌아가요)", True)
            return
        say("4/4 완료! 보드가 재시작해요. 다시 연결하는 중...")
        await asyncio.sleep(10)
        page.pop_dialog()
        await connect(None)
        toast("펌웨어 업데이트 완료")

    # ───────── 화면 구성 ─────────
    def btn(text, icon, handler, primary=False):
        B = ft.FilledButton if primary else ft.OutlinedButton
        return B(content=text, icon=icon, on_click=handler)

    top = ft.Column([
        ft.Row([board_dd, btn("찾기", ft.Icons.BLUETOOTH_SEARCHING, do_scan), btn("연결", ft.Icons.BLUETOOTH_CONNECTED, connect),
                btn("LCD로 보내기", ft.Icons.SEND, send, True)], wrap=True, spacing=6),
        ft.Row([btn("리모컨", ft.Icons.SETTINGS_REMOTE, remote_dialog),
                btn("실제 화면", ft.Icons.SCREENSHOT_MONITOR, show_screen), btn("화면 설정", ft.Icons.TUNE, settings_dialog),
                btn("시간 맞추기", ft.Icons.SCHEDULE, sync_time),
                btn("변수 보내기", ft.Icons.DATA_OBJECT, vars_dialog), btn("JSON", ft.Icons.CODE, json_dialog),
                btn("초기화", ft.Icons.RESTART_ALT, reset_layout),
                btn("WiFi (업데이트용)", ft.Icons.WIFI, wifi_dialog), btn("펌웨어 업데이트", ft.Icons.SYSTEM_UPDATE, firmware_update)],
               wrap=True, spacing=6),
        ft.Row([page_dd, btn("LCD에 띄우기", ft.Icons.TV, show_page_on_lcd), btn("새 페이지", ft.Icons.ADD, new_page),
                btn("페이지 삭제", ft.Icons.DELETE_OUTLINE, delete_page),
                btn("모든 페이지 삭제", ft.Icons.DELETE_FOREVER, delete_all_pages)], wrap=True, spacing=6),
        status,
    ], spacing=6)

    add_row = ft.Row([ft.OutlinedButton(content=n, on_click=lambda e, n=n: add_widget(n)) for n in PRESETS] + [
        ft.FilledButton(content="이미지 올리기", icon=ft.Icons.IMAGE, on_click=upload_image),
        ft.TextButton(content="보드 이미지 관리", on_click=manage_files)], wrap=True, spacing=6)

    page.add(
        ft.Text(f"LCD 꾸미기 {APP_VER}", size=20, weight=ft.FontWeight.BOLD),
        top,
        ft.Divider(height=8),
        ft.ResponsiveRow([
            ft.Column([preview_box, ft.Text("위젯을 끌어서 옮기고, 눌러서 선택하세요", size=12, color="#94a3b8"), files_text],
                      col={"xs": 12, "md": 5}, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Column([ft.Text("위젯 추가", weight=ft.FontWeight.BOLD), add_row, ft.Divider(height=8),
                       ft.Row([ft.Text("위젯 목록 (아래일수록 위에 그려짐)", weight=ft.FontWeight.BOLD),
                               ft.OutlinedButton(content="위젯 모두 삭제", icon=ft.Icons.DELETE_SWEEP, on_click=delete_all_widgets)], wrap=True), widget_list,
                       ft.Divider(height=8), props], col={"xs": 12, "md": 7}),
        ]),
    )

    async def pref_get(k):
        try:
            return await prefs.get(k)
        except Exception:
            return None

    async def start():
        addr, name = await pref_get("ble_addr"), await pref_get("ble_name")
        if addr:  # 지난번 보드 (바로 '연결' 누르면 됨)
            board_dd.options = [ft.DropdownOption(key=addr, text=name or addr)]
            board_dd.value = addr
            board_dd.update()
        saved = await pref_get("layout")
        if saved:
            try:
                st["layout"] = json.loads(saved)
            except ValueError:
                pass
        build_props()
        build_list()
        refresh_preview()

    page.on_resize = lambda e: refresh_preview()

    async def ticker():
        # 시계/초가 있는 화면이면 미리보기를 1초마다 다시 그림
        while True:
            await asyncio.sleep(1)
            if st.get("busy"):
                continue
            try:
                if any("{" in str(w.get("text", "")) or w.get("type") in ("clock", "bar") for w in st["layout"]["widgets"]):
                    refresh_preview()
            except Exception:
                pass

    async def sensor_ticker():
        while True:
            await asyncio.sleep(10)
            if not ble.connected or st.get("busy"):
                continue
            if not any("{ntc}" in str(w.get("text", "")) for w in st["layout"]["widgets"]):
                continue
            info = await run_net("센서 온도 확인", dev().info)
            if info is not None:
                sensor = info.get("ntc")
                st["ctx"]["ntc"] = f"{sensor:.1f}" if isinstance(sensor, (int, float)) else "--"
                refresh_preview()

    page.run_task(start)
    page.run_task(ticker)
    page.run_task(sensor_ticker)


if __name__ == "__main__":
    if os.environ.get("LCDAPP_WEB"):
        ft.run(main, view=ft.AppView.WEB_BROWSER, port=int(os.environ.get("LCDAPP_WEB")))
    else:
        ft.run(main)
