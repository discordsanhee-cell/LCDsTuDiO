"""
LCD Studio 블루투스 서비스 (휴대폰용)

Python에서 부르면 Flutter 쪽(src/flutter/flet_lcdble, flutter_blue_plus)이 실제 블루투스를 다룸.
보드 규칙은 lcdpanel.ino 의 BLE_* 와 같음 (서비스 a7c00001-.., 명령 a7c00002-.., 상태 a7c00003-..)
"""
import flet as ft

__all__ = ["LcdBle"]


@ft.control("LcdBle")
class LcdBle(ft.Service):
    async def scan(self, timeout: float = 5) -> list:
        """이름이 LCD- 로 시작하거나 보드 서비스를 광고하는 기기 -> [{"id": .., "name": ..}, ...]"""
        return await self._invoke_method("scan", {"timeout": timeout}, timeout=timeout + 15)

    async def connect(self, id: str) -> str:
        """연결하고 상태 JSON 문자열을 돌려줌"""
        return await self._invoke_method("connect", {"id": id}, timeout=40)

    async def write(self, data: str) -> str:
        """명령 JSON을 보내고 처리 후 상태 JSON 문자열을 돌려줌"""
        return await self._invoke_method("write", {"data": data}, timeout=20)

    async def request(self, method: str, path: str, body_b64: str, ctype: str = "", timeout: float = 60) -> dict:
        """보드 HTTP API를 블루투스로 (펌웨어 v2.0+) -> {"st": 200, "ct": "...", "b64": "..."}"""
        return await self._invoke_method(
            "request", {"m": method, "p": path, "b64": body_b64, "ct": ctype, "timeout": timeout}, timeout=timeout + 30
        )

    async def read(self) -> str:
        return await self._invoke_method("read", {}, timeout=15)

    async def disconnect(self):
        return await self._invoke_method("disconnect", {}, timeout=10)
