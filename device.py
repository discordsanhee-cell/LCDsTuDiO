"""
lcdpanel 보드와 통신 (표준 라이브러리만 사용 - exe/apk 둘 다 그대로 동작)

펌웨어 v2.1+: 평소엔 블루투스로 모든 API (Device(link=BleLink)) - WiFi는 펌웨어 업데이트(OTA) 때만 (Device(host))
"""
import concurrent.futures as cf
import json
import os
import socket
import urllib.error
import urllib.request
import uuid

SKETCH = "lcdpanel"
AP_IP = "192.168.4.1"


class DeviceError(Exception):
    pass


class Device:
    def __init__(self, host: str = "", link=None):
        self.host = (host or "").strip().replace("http://", "").replace("https://", "").rstrip("/")
        self.link = link  # BleLink: 있으면 블루투스로 (HTTP 요청을 그대로 블루투스로 실어 보냄)

    def _req(self, method, path, data=None, ctype=None, timeout=6.0):
        if self.link is not None:
            st, _ct, body = self.link.request_sync(method, path, data or b"", ctype, max(timeout * 3, 20))
            if st >= 400 or st == 0:
                try:
                    msg = json.loads(body).get("error", f"HTTP {st}")
                except Exception:
                    msg = f"HTTP {st}"
                raise DeviceError(msg)
            return body
        req = urllib.request.Request(f"http://{self.host}{path}", data=data, method=method)
        if ctype:
            req.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("error", str(e))
            except Exception:
                msg = str(e)
            raise DeviceError(msg) from None
        except (urllib.error.URLError, OSError) as e:
            raise DeviceError(f"{self.host} 에 연결할 수 없어요 ({getattr(e, 'reason', e)})") from None

    def get_json(self, path, timeout=6.0):
        return json.loads(self._req("GET", path, timeout=timeout) or b"{}")

    def post_json(self, path, obj, timeout=10.0):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        return json.loads(self._req("POST", path, body, "application/json", timeout) or b"{}")

    def info(self, timeout=4.0):
        return self.get_json("/api/info", timeout)

    # 페이지(화면 여러 개): page=None 이면 지금 보이는 페이지 (펌웨어 v1.8+)
    def layout(self, page=None):
        return self.get_json("/api/layout" + ("" if page is None else f"?page={int(page)}"))

    def set_layout(self, layout, page=None):
        return self.post_json("/api/layout" + ("" if page is None else f"?page={int(page)}"), layout)

    def pages(self):
        """{"current": n, "max": 5, "pages": [0, 1, 2]} - 페이지 기능이 없는 옛 펌웨어면 0번 하나만"""
        try:
            return self.get_json("/api/pages")
        except DeviceError:
            return {"current": 0, "max": 1, "pages": [0]}

    def set_page(self, n):
        return self.post_json("/api/page", {"page": int(n)})

    def delete_page(self, n):
        return json.loads(self._req("DELETE", f"/api/layout?page={int(n)}") or b"{}")

    def delete_all_pages(self):
        """1~4번 페이지를 지우고 0번은 기본 화면으로 (펌웨어 v1.9+)"""
        return json.loads(self._req("DELETE", "/api/pages") or b"{}")

    def settings(self):
        return self.get_json("/api/settings")

    def set_settings(self, s):
        return self.post_json("/api/settings", s)

    def set_vars(self, d):
        return self.post_json("/api/vars", d)

    def set_time(self, epoch):
        return self.post_json("/api/time", {"epoch": int(epoch)})

    def set_wifi(self, ssid, password):
        # 저장하자마자 보드가 재시작해서 응답이 끊길 수 있음 -> 성공으로 봄
        try:
            return self.post_json("/api/wifi", {"ssid": ssid, "pass": password}, timeout=5)
        except DeviceError:
            return {"ok": True}

    def reboot(self):
        try:
            return self.post_json("/api/reboot", {}, timeout=3)
        except DeviceError:
            return {"ok": True}

    def files(self):
        return self.get_json("/api/files")

    def file(self, name):
        return self._req("GET", "/api/file?name=" + urllib.request.quote(name), timeout=15)

    def delete_file(self, name):
        return json.loads(self._req("DELETE", "/api/file?name=" + urllib.request.quote(name)) or b"{}")

    def set_weather(self, temp, code, city):
        """보드는 평소 인터넷이 없어서 앱이 받은 날씨를 넣어줌 (펌웨어 v2.1+)"""
        return self.post_json("/api/weather", {"temp": float(temp), "code": int(code), "city": city or ""})

    def ota_mode(self):
        """업데이트 모드로 재시작 (WiFi를 켜고 OTA 대기)"""
        try:
            return self.post_json("/api/ota_mode", {}, timeout=3)
        except DeviceError:
            return {"ok": True}

    def ota(self, data: bytes):
        """WiFi로 펌웨어 올리기 (업데이트 모드의 IP로 Device(host) 를 만들어서 호출)"""
        b = uuid.uuid4().hex
        body = (
            f'--{b}\r\nContent-Disposition: form-data; name="firmware"; filename="firmware.bin"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n".encode()
            + data
            + f"\r\n--{b}--\r\n".encode()
        )
        return json.loads(self._req("POST", "/api/ota", body, f"multipart/form-data; boundary={b}", 240) or b"{}")

    def screenshot(self):
        """보드 실제 화면 -> 이미지 바이트 (펌웨어 v2.2+는 압축본을 받아서 PNG로 풀어줌: 블루투스로 0.3초)"""
        if self.link is not None:
            try:
                data = self._req("GET", "/api/screenshot?fmt=rle", timeout=20)
                if len(data) > 4 and not data.startswith(b"BM"):
                    return rle565_to_png(data)
            except (DeviceError, ImportError):
                pass
        return self._req("GET", "/api/screenshot", timeout=20)

    def upload(self, name, data: bytes):
        b = uuid.uuid4().hex
        body = (
            f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n".encode()
            + data
            + f"\r\n--{b}--\r\n".encode()
        )
        return json.loads(self._req("POST", "/api/upload", body, f"multipart/form-data; boundary={b}", 60) or b"{}")


def rle565_to_png(data: bytes) -> bytes:
    """보드의 압축 화면(가로, 세로, [개수, RGB565]...) -> PNG"""
    from io import BytesIO

    from PIL import Image

    w, h = data[0] | data[1] << 8, data[2] | data[3] << 8
    out = bytearray()
    for i in range(4, len(data) - 2, 3):
        c = data[i + 1] | data[i + 2] << 8
        r, g, b = (c >> 11) << 3, ((c >> 5) & 63) << 2, (c & 31) << 3
        out += bytes((r | r >> 5, g | g >> 6, b | b >> 5)) * data[i]
    if len(out) != w * h * 3:
        raise DeviceError("화면 데이터가 깨졌어요")
    im = Image.frombytes("RGB", (w, h), bytes(out))
    buf = BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def scan(timeout=0.7):
    """같은 WiFi에서 lcdpanel 보드 찾기 -> [(ip, info), ...]"""
    hosts = []
    ip = local_ip()
    if ip:
        prefix = ip.rsplit(".", 1)[0]
        hosts = [f"{prefix}.{i}" for i in range(1, 255) if f"{prefix}.{i}" != ip]
    hosts.append(AP_IP)

    def probe(h):
        try:
            info = Device(h).info(timeout)
            if info.get("sketch") == SKETCH:
                return h, info
        except Exception:
            pass
        return None

    found = []
    with cf.ThreadPoolExecutor(64) as ex:
        for r in ex.map(probe, dict.fromkeys(hosts)):
            if r:
                found.append(r)
    return found


def fetch_weather():
    """이 기기(휴대폰/PC)의 인터넷으로 현재 날씨 -> (기온, 날씨코드, 도시) / 실패하면 None"""
    try:
        with urllib.request.urlopen("http://ip-api.com/json/?fields=status,lat,lon,city", timeout=5) as r:
            g = json.loads(r.read())
        if g.get("status") != "success":
            return None
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={g['lat']:.3f}&longitude={g['lon']:.3f}"
               "&current=temperature_2m,weather_code&timezone=auto")
        with urllib.request.urlopen(url, timeout=6) as r:
            c = json.loads(r.read())["current"]
        return float(c["temperature_2m"]), int(c.get("weather_code", -1)), g.get("city", "")
    except Exception:
        return None


def _hex_rgb(c, default=(0, 0, 0)):
    c = c.lstrip("#")
    try:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except Exception:
        return default


def prepare_image(data: bytes, name: str, max_w: int, max_h: int, bg: str = "#000000", quality: int = 88):
    """사진을 보드에 맞게: 크기 줄이고, 회전 정보 반영, 투명 부분은 배경색으로, 일반(baseline) JPG로 저장
    -> (데이터, 새 파일 이름, 가로, 세로)"""
    new_name = os.path.splitext(name)[0] + ".jpg"
    try:
        from io import BytesIO

        from PIL import Image, ImageOps
    except ImportError:
        if data[:2] == b"\xff\xd8" and len(data) <= 300000:
            return data, new_name, 0, 0
        raise DeviceError("이 환경에는 이미지 변환 기능이 없어요. 작은 JPG 파일을 골라주세요.")
    try:
        im = Image.open(BytesIO(data))
        im.load()
    except Exception as e:
        raise DeviceError(f"이미지를 열 수 없어요 ({e})") from None
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:
        pass
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        base = Image.new("RGBA", im.size, _hex_rgb(bg) + (255,))
        base.alpha_composite(im)
        im = base
    im = im.convert("RGB")
    im.thumbnail((max(1, max_w), max(1, max_h)), getattr(Image, "Resampling", Image).LANCZOS)
    out = BytesIO()
    im.save(out, "JPEG", quality=quality, optimize=True, progressive=False)
    return out.getvalue(), new_name, im.size[0], im.size[1]
