"""
블루투스(BLE)로 lcdpanel 보드 조종 (펌웨어 v1.9+) - WiFi 없이 페이지 전환, 밝기, 끄기, 시간 맞추기

- PC(exe): bleak 라이브러리 (Windows 블루투스)
- 휴대폰(apk): flet_lcdble 확장 (Flutter의 flutter_blue_plus) - Python만으로는 안드로이드 블루투스를 못 씀

보드 쪽 규칙 (lcdpanel.ino 의 BLE_* 와 같아야 함)
  서비스 a7c00001-... / 명령(쓰기) a7c00002-... JSON / 상태(읽기·알림) a7c00003-... JSON
"""
import asyncio
import base64
import json

SVC_UUID = "a7c00001-1d3a-4d2b-9c8e-6c6364706e6c"
CMD_UUID = "a7c00002-1d3a-4d2b-9c8e-6c6364706e6c"
STAT_UUID = "a7c00003-1d3a-4d2b-9c8e-6c6364706e6c"
RPC_IN_UUID = "a7c00004-1d3a-4d2b-9c8e-6c6364706e6c"   # 쓰기: HTTP 요청 조각 (펌웨어 v2.0+)
RPC_OUT_UUID = "a7c00005-1d3a-4d2b-9c8e-6c6364706e6c"  # 알림: HTTP 응답 조각
NAME_PREFIX = "LCD-"


class BleError(Exception):
    pass


def _parse(raw):
    if raw is None:
        return {}
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


class _BleakBackend:
    """PC (Windows/macOS/Linux)"""

    def __init__(self):
        self.client = None
        self._rpcq = None

    def _on_rpc(self, _ch, data: bytearray):
        if self._rpcq is not None:
            self._rpcq.put_nowait(bytes(data))

    async def request(self, method, path, body=b"", ctype=None, timeout=60.0):
        """보드의 HTTP API를 블루투스로: (상태코드, 내용 종류, 내용 바이트)"""
        if not self.client or not self.client.is_connected:
            raise BleError("블루투스 연결이 끊겼어요. 다시 연결하세요")
        body = body or b""
        mtu = getattr(self.client, "mtu_size", 23) or 23
        ch = max(16, min(240, mtu - 4))
        q = self._rpcq = asyncio.Queue()
        head = json.dumps({"m": method, "p": path, "ct": ctype or "", "len": len(body)}).encode() + b"\n"
        try:
            for o in range(0, len(head), ch):
                await self.client.write_gatt_char(RPC_IN_UUID, b"H" + head[o:o + ch], response=True)
            # 몸통은 응답 없이 연달아 (속도), 마지막 조각만 응답 받아서 다 들어갔는지 확인
            # (보드가 바쁘면 블루투스가 알아서 속도를 늦춤 -> 빠지는 조각 없음)
            for o in range(0, len(body), ch):
                last = o + ch >= len(body)
                await self.client.write_gatt_char(RPC_IN_UUID, b"D" + body[o:o + ch], response=last)
            rhead, data = b"", bytearray()
            while True:
                f = await asyncio.wait_for(q.get(), timeout)
                if f[:1] == b"H":
                    rhead += f[1:]
                elif f[:1] == b"D":
                    data += f[1:]
                elif f[:1] == b"E":
                    break
        except asyncio.TimeoutError:
            raise BleError("보드 응답이 없어요 (블루투스)") from None
        except BleError:
            raise
        except Exception as e:
            raise BleError(str(e)) from None
        finally:
            self._rpcq = None
        h = _parse(rhead.split(b"\n")[0])
        return h.get("st", 0), h.get("ct", ""), bytes(data)

    async def scan(self, timeout):
        try:
            from bleak import BleakScanner
        except ImportError:
            raise BleError("이 PC에는 블루투스 라이브러리(bleak)가 없어요") from None
        try:
            found = await BleakScanner.discover(timeout=timeout, return_adv=True)
        except Exception as e:
            raise BleError(f"블루투스를 켜 주세요 ({e})") from None
        out = []
        for addr, (d, adv) in found.items():
            name = adv.local_name or d.name or ""
            if name.startswith(NAME_PREFIX) or SVC_UUID in [u.lower() for u in adv.service_uuids]:
                out.append((addr, name or addr))
        return out

    async def connect(self, addr):
        from bleak import BleakClient
        await self.close()
        self.client = BleakClient(addr, timeout=15)
        try:
            await self.client.connect()
            await self.client.start_notify(RPC_OUT_UUID, self._on_rpc)
            await asyncio.sleep(1.0)  # 패킷 크기(MTU)·연결 간격 협상이 끝날 때까지 (중간에 보내면 응답이 사라질 수 있음)
        except Exception as e:
            self.client = None
            raise BleError(f"연결 실패 ({e})") from None
        return await self.status()

    async def send(self, cmd: dict):
        if not self.client or not self.client.is_connected:
            raise BleError("연결이 끊겼어요. 다시 '찾기'를 누르세요")
        try:
            await self.client.write_gatt_char(CMD_UUID, json.dumps(cmd).encode(), response=True)
        except Exception as e:
            if cmd.get("c") in ("off", "reboot"):  # 보드가 바로 꺼져서 응답이 없을 수 있음
                return {}
            raise BleError(str(e)) from None
        if cmd.get("c") in ("off", "reboot"):
            return {}
        await asyncio.sleep(0.25)  # 보드가 loop에서 처리할 시간
        return await self.status()

    async def status(self):
        try:
            return _parse(await self.client.read_gatt_char(STAT_UUID))
        except Exception as e:
            raise BleError(str(e)) from None

    async def close(self):
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
        self.client = None


class _FletBackend:
    """휴대폰 (Android/iOS) - flet_lcdble 확장이 같이 빌드돼 있어야 함"""

    def __init__(self, page):
        from flet_lcdble import LcdBle

        self.svc = LcdBle()
        if self.svc not in page.services:
            page.services.append(self.svc)

    async def scan(self, timeout):
        try:
            r = await self.svc.scan(timeout)
        except Exception as e:
            raise BleError(str(e)) from None
        return [(d["id"], d.get("name") or d["id"]) for d in r]

    async def connect(self, addr):
        try:
            return _parse(await self.svc.connect(addr))
        except Exception as e:
            raise BleError(str(e)) from None

    async def send(self, cmd: dict):
        try:
            return _parse(await self.svc.write(json.dumps(cmd)))
        except Exception as e:
            if cmd.get("c") in ("off", "reboot"):
                return {}
            raise BleError(str(e)) from None

    async def status(self):
        try:
            return _parse(await self.svc.read())
        except Exception as e:
            raise BleError(str(e)) from None

    async def request(self, method, path, body=b"", ctype=None, timeout=60.0):
        # 조각 나누기/모으기는 Flutter 쪽에서 (Python <-> Flutter 왕복을 한 번으로)
        try:
            r = await self.svc.request(method, path, base64.b64encode(body or b"").decode(), ctype or "", timeout)
        except Exception as e:
            raise BleError(str(e)) from None
        return r.get("st", 0), r.get("ct", ""), base64.b64decode(r.get("b64") or "")

    async def close(self):
        try:
            await self.svc.disconnect()
        except Exception:
            pass


class BleLink:
    """앱 전체가 쓰는 블루투스 연결 하나 (보드는 한 번에 하나만 연결됨)"""

    def __init__(self, page):
        self.page = page
        self._b = None
        self._loop = None
        self._lock = None
        self.connected = False
        self.addr = None
        self.name = None
        # 휴대폰: 블루투스 서비스를 앱 시작 때 미리 만들어야 함
        # (나중에 만들면 휴대폰 쪽에 등록되기 전에 명령을 보내서 무시됨 -> '찾기'가 아무 반응 없음)
        try:
            import flet as ft

            if page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS):
                self._b = _FletBackend(page)
        except Exception:
            self._b = None

    def _backend(self):
        if self._b is None:
            import flet as ft

            mobile = self.page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)
            if mobile:
                try:
                    self._b = _FletBackend(self.page)
                except ImportError:
                    raise BleError("이 앱에는 블루투스 기능이 빠져 있어요 (flet_lcdble)") from None
            else:
                self._b = _BleakBackend()
        return self._b

    async def scan(self, timeout=5):
        return await self._backend().scan(timeout)

    async def connect(self, addr, name=None):
        self._loop = asyncio.get_running_loop()
        self._lock = asyncio.Lock()
        s = await self._backend().connect(addr)
        self.connected, self.addr, self.name = True, addr, name or addr
        return s

    async def send(self, cmd):
        async with self._lock:
            return await self._backend().send(cmd)

    async def status(self):
        async with self._lock:
            return await self._backend().status()

    async def request(self, method, path, body=b"", ctype=None, timeout=60.0):
        """보드의 HTTP API를 블루투스로 -> (상태코드, 내용 종류, 내용)"""
        if not self.connected:
            raise BleError("보드에 블루투스로 연결하세요 ('찾기' → '연결')")
        async with self._lock:  # 한 번에 요청 하나
            tries = 2 if method == "GET" else 1  # 읽기는 응답이 없으면 한 번 더 (보내기는 두 번 하면 안 되니 한 번만)
            for n in range(tries):
                try:
                    return await self._backend().request(method, path, body, ctype, timeout if n else min(timeout, 15))
                except BleError:
                    if not await self._alive():
                        self.connected = False
                        raise
                    if n == tries - 1:
                        raise
                    await asyncio.sleep(0.5)

    async def _alive(self):
        b = self._b
        if isinstance(b, _BleakBackend):
            return bool(b.client and b.client.is_connected)
        return True

    def request_sync(self, method, path, body=b"", ctype=None, timeout=60.0):
        """다른 스레드(asyncio.to_thread)에서 부를 때: 앱의 이벤트 루프에서 실행하고 기다림"""
        from device import DeviceError

        if not self._loop:
            raise DeviceError("보드에 블루투스로 연결하세요 ('찾기' → '연결')")
        fut = asyncio.run_coroutine_threadsafe(self.request(method, path, body, ctype, timeout), self._loop)
        try:
            return fut.result(timeout + 10)
        except BleError as e:
            raise DeviceError(f"블루투스: {e}") from None
        except Exception as e:
            fut.cancel()
            raise DeviceError(f"블루투스: {e}") from None

    async def close(self):
        self.connected = False
        if self._b:
            await self._b.close()
