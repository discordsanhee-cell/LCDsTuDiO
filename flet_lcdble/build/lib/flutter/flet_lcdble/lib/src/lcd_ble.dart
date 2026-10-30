// LCD Studio 블루투스: Python(LcdBle 서비스)이 부르는 메서드를 flutter_blue_plus로 처리
import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flet/flet.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';

final Guid svcUuid = Guid("a7c00001-1d3a-4d2b-9c8e-6c6364706e6c");
final Guid cmdUuid = Guid("a7c00002-1d3a-4d2b-9c8e-6c6364706e6c");
final Guid statUuid = Guid("a7c00003-1d3a-4d2b-9c8e-6c6364706e6c");
final Guid rpcInUuid = Guid("a7c00004-1d3a-4d2b-9c8e-6c6364706e6c"); // 쓰기: HTTP 요청 조각
final Guid rpcOutUuid = Guid("a7c00005-1d3a-4d2b-9c8e-6c6364706e6c"); // 알림: HTTP 응답 조각

class LcdBleService extends FletService {
  LcdBleService({required super.control});

  final Map<String, BluetoothDevice> _seen = {};
  BluetoothDevice? _dev;
  BluetoothCharacteristic? _cmd;
  BluetoothCharacteristic? _stat;
  BluetoothCharacteristic? _rpcIn;
  BluetoothCharacteristic? _rpcOut;
  StreamSubscription<List<int>>? _rpcSub;
  StreamController<List<int>>? _rpcFrames;
  int _mtu = 23;

  @override
  void init() {
    super.init();
    control.addInvokeMethodListener(_invokeMethod);
  }

  @override
  void dispose() {
    control.removeInvokeMethodListener(_invokeMethod);
    _dev?.disconnect();
    super.dispose();
  }

  Future<dynamic> _invokeMethod(String name, dynamic args) async {
    switch (name) {
      case "scan":
        return _scan(((args?["timeout"] ?? 5) as num).toDouble());
      case "connect":
        return _connect(args["id"] as String);
      case "write":
        return _write(args["data"] as String);
      case "read":
        return _read();
      case "request":
        return _request(args["m"] as String, args["p"] as String, args["b64"] as String? ?? "",
            args["ct"] as String? ?? "", ((args["timeout"] ?? 60) as num).toDouble());
      case "disconnect":
        await _rpcSub?.cancel();
        _rpcSub = null;
        await _dev?.disconnect();
        _dev = null;
        _cmd = null;
        _stat = null;
        _rpcIn = null;
        _rpcOut = null;
        return null;
      default:
        throw Exception("Unknown LcdBle method: $name");
    }
  }

  Future<void> _ensureOn() async {
    if (await FlutterBluePlus.isSupported == false) {
      throw Exception("이 기기는 블루투스를 지원하지 않아요");
    }
    // 앱이 막 켜졌을 땐 상태가 "unknown" -> 실제 상태가 올 때까지 잠깐 기다림
    var state = FlutterBluePlus.adapterStateNow;
    if (state == BluetoothAdapterState.unknown) {
      try {
        state = await FlutterBluePlus.adapterState
            .where((s) => s != BluetoothAdapterState.unknown)
            .first
            .timeout(const Duration(seconds: 3));
      } catch (_) {}
    }
    if (state != BluetoothAdapterState.on) {
      try {
        await FlutterBluePlus.turnOn(); // 안드로이드: 블루투스 켜기 요청 창
      } catch (_) {}
      await FlutterBluePlus.adapterState
          .where((s) => s == BluetoothAdapterState.on)
          .first
          .timeout(const Duration(seconds: 10),
              onTimeout: () => throw Exception("블루투스를 켜 주세요"));
    }
  }

  Future<List<Map<String, String>>> _scan(double timeout) async {
    await _ensureOn();
    final found = <String, Map<String, String>>{};
    final sub = FlutterBluePlus.onScanResults.listen((results) {
      for (final r in results) {
        final name = r.advertisementData.advName.isNotEmpty
            ? r.advertisementData.advName
            : r.device.platformName;
        final hasSvc = r.advertisementData.serviceUuids.contains(svcUuid);
        if (name.startsWith("LCD-") || hasSvc) {
          final id = r.device.remoteId.str;
          _seen[id] = r.device;
          found[id] = {"id": id, "name": name.isEmpty ? id : name};
        }
      }
    });
    try {
      // 위치 권한도 같이 요청: 안드로이드는 스캔 권한에 "위치에 안 씀" 표시가 없으면 위치 권한이 있어야 결과를 줌
      await FlutterBluePlus.startScan(
          timeout: Duration(milliseconds: (timeout * 1000).round()),
          androidUsesFineLocation: true);
      await FlutterBluePlus.isScanning.where((s) => s == false).first;
    } finally {
      await sub.cancel();
    }
    return found.values.toList();
  }

  Future<String> _connect(String id) async {
    await _ensureOn();
    final dev = _seen[id] ?? BluetoothDevice.fromId(id);
    if (_dev != null && _dev!.remoteId != dev.remoteId) {
      await _dev!.disconnect();
    }
    await dev.connect(timeout: const Duration(seconds: 15));
    try {
      _mtu = await dev.requestMtu(247);
    } catch (_) {
      _mtu = dev.mtuNow;
    }
    final services = await dev.discoverServices();
    BluetoothCharacteristic? cmd, stat, rin, rout;
    for (final s in services) {
      if (s.uuid != svcUuid) continue;
      for (final c in s.characteristics) {
        if (c.uuid == cmdUuid) cmd = c;
        if (c.uuid == statUuid) stat = c;
        if (c.uuid == rpcInUuid) rin = c;
        if (c.uuid == rpcOutUuid) rout = c;
      }
    }
    if (cmd == null || stat == null || rin == null || rout == null) {
      await dev.disconnect();
      throw Exception("LCD 보드가 아니거나 펌웨어가 옛날 버전이에요 (v2.1 이상 필요)");
    }
    _dev = dev;
    _cmd = cmd;
    _stat = stat;
    _rpcIn = rin;
    _rpcOut = rout;
    // 응답 조각 알림 받기
    await _rpcSub?.cancel();
    _rpcSub = rout.onValueReceived.listen((v) => _rpcFrames?.add(v));
    dev.cancelWhenDisconnected(_rpcSub!);
    await rout.setNotifyValue(true);
    return _read();
  }

  Future<String> _write(String data) async {
    final cmd = _cmd;
    if (cmd == null || _dev == null || !_dev!.isConnected) {
      throw Exception("연결이 끊겼어요. 다시 '찾기'를 누르세요");
    }
    final c = (jsonDecode(data) as Map)["c"];
    try {
      await cmd.write(utf8.encode(data), withoutResponse: false);
    } catch (e) {
      if (c == "off" || c == "reboot") return "{}"; // 보드가 바로 꺼져서 응답이 없을 수 있음
      rethrow;
    }
    if (c == "off" || c == "reboot") return "{}";
    await Future.delayed(const Duration(milliseconds: 250)); // 보드가 loop에서 처리할 시간
    return _read();
  }

  // 보드 HTTP API를 블루투스로: 머리('H' JSON+줄바꿈) -> 몸통('D') 조각으로 쓰고, 응답 조각을 'E'까지 모음
  Future<Map<String, dynamic>> _request(
      String method, String path, String b64, String ctype, double timeout) async {
    final rin = _rpcIn;
    if (rin == null || _dev == null || !_dev!.isConnected) {
      throw Exception("연결이 끊겼어요. 다시 '찾기'를 누르세요");
    }
    final body = b64.isEmpty ? <int>[] : base64Decode(b64);
    final ch = (_mtu - 4).clamp(16, 240);
    final frames = StreamController<List<int>>();
    _rpcFrames = frames;
    final head = utf8.encode(
        "${jsonEncode({"m": method, "p": path, "ct": ctype, "len": body.length})}\n");
    try {
      for (var o = 0; o < head.length; o += ch) {
        await rin.write([72] + head.sublist(o, (o + ch).clamp(0, head.length)),
            withoutResponse: false); // 'H'
      }
      // 몸통은 응답 없이 연달아 (속도), 마지막 조각만 응답 받아서 다 들어갔는지 확인
      for (var o = 0; o < body.length; o += ch) {
        final last = o + ch >= body.length;
        await rin.write([68] + body.sublist(o, (o + ch).clamp(0, body.length)),
            withoutResponse: !last); // 'D'
      }
      final rhead = <int>[];
      final data = BytesBuilder(copy: false);
      await for (final f in frames.stream.timeout(
          Duration(milliseconds: (timeout * 1000).round()),
          onTimeout: (s) => s.addError(Exception("보드 응답이 없어요 (블루투스)")))) {
        if (f.isEmpty) continue;
        if (f[0] == 72) {
          rhead.addAll(f.sublist(1));
        } else if (f[0] == 68) {
          data.add(f.sublist(1));
        } else if (f[0] == 69) {
          break; // 'E'
        }
      }
      final hs = utf8.decode(rhead, allowMalformed: true).split("\n").first;
      final h = hs.isEmpty ? <String, dynamic>{} : jsonDecode(hs) as Map<String, dynamic>;
      return {"st": h["st"] ?? 0, "ct": h["ct"] ?? "", "b64": base64Encode(data.takeBytes())};
    } finally {
      _rpcFrames = null;
      await frames.close();
    }
  }

  Future<String> _read() async {
    final stat = _stat;
    if (stat == null) throw Exception("연결 안 됨");
    final v = await stat.read();
    return utf8.decode(v, allowMalformed: true);
  }
}
