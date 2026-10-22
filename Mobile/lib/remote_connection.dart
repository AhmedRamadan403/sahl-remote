import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'pairing.dart';

enum ConnectionPhase { idle, connecting, waiting, active, error }

class RemoteConnection extends ChangeNotifier {
  ConnectionPhase phase = ConnectionPhase.idle;
  String message = '', hostName = '';
  ui.Image? frame;
  bool controlEnabled = false;
  WebSocket? _socket;
  HttpClient? _client;
  StreamSubscription<dynamic>? _subscription;
  Timer? _heartbeat;
  Uint8List? _pendingFrame;
  bool _decoding = false, _disposed = false;
  int _generation = 0;
  bool get canControl =>
      phase == ConnectionPhase.active && controlEnabled && frame != null;

  Future<void> connect(PairingData pairing) async {
    await disconnect();
    final generation = ++_generation;
    phase = ConnectionPhase.connecting;
    message = 'بنوصل بالكمبيوتر…';
    notifyListeners();
    final client =
        HttpClient(context: SecurityContext(withTrustedRoots: false));
    // Trust precisely the certificate scanned from the host; never accept all certificates.
    client.badCertificateCallback = (certificate, host, port) =>
        host == pairing.host &&
        port == pairing.port &&
        sha256.convert(certificate.der).toString() == pairing.fingerprint;
    client.connectionTimeout = const Duration(seconds: 10);
    _client = client;
    try {
      final socket = await WebSocket.connect(pairing.socketUrl,
              headers: {'Origin': pairing.origin}, customClient: client)
          .timeout(const Duration(seconds: 12));
      if (_disposed || generation != _generation) {
        await socket.close();
        client.close(force: true);
        return;
      }
      _socket = socket;
      socket.pingInterval = const Duration(seconds: 15);
      _subscription =
          socket.listen((data) => _onData(data, generation), onError: (_) {
        if (generation == _generation) {
          _fail('الاتصال اتقطع. اتأكد إن الجهازين على نفس الشبكة.');
        }
      }, onDone: () {
        if (generation == _generation && phase != ConnectionPhase.error) {
          _fail('الجلسة انتهت. امسح QR جديد أو اكتب رقم الكمبيوتر.');
        }
      });
      socket.add(jsonEncode({
        'type': 'pair',
        'code': pairing.code,
        'name': Platform.isIOS ? 'Sahl / iPhone' : 'Sahl / Android'
      }));
      _heartbeat = Timer.periodic(
          const Duration(seconds: 10), (_) => _send({'type': 'ping'}));
    } catch (_) {
      if (generation == _generation && !_disposed) {
        _fail(
            'تعذّر الاتصال أو شهادة الكمبيوتر لا تطابق QR. اعرض رمزًا جديدًا وحاول تاني.');
      }
    }
  }

  void _onData(dynamic data, int generation) {
    if (_disposed || generation != _generation) return;
    if (data is List<int>) {
      if (phase != ConnectionPhase.active || data.length > 8000000) return;
      _pendingFrame = Uint8List.fromList(data);
      _decodeFrames(generation);
      return;
    }
    if (data is! String || data.length > 8192) return;
    try {
      final event = jsonDecode(data);
      if (event is! Map) return;
      switch (event['type']) {
        case 'waiting':
          phase = ConnectionPhase.waiting;
          message = 'طلبك وصل. اضغط Allow على الكمبيوتر.';
          notifyListeners();
        case 'approved':
          phase = ConnectionPhase.active;
          hostName = event['host']?.toString() ?? 'الكمبيوتر';
          message = 'متصل · عرض فقط';
          controlEnabled = false;
          notifyListeners();
        case 'error':
        case 'ended':
          _fail(event['message']?.toString() ?? 'انتهت الجلسة.');
      }
    } on FormatException {/* Ignore malformed status messages. */}
  }

  Future<void> _decodeFrames(int generation) async {
    if (_decoding) return;
    _decoding = true;
    try {
      while (_pendingFrame != null && !_disposed && generation == _generation) {
        final bytes = _pendingFrame!;
        _pendingFrame = null;
        ui.Codec? codec;
        try {
          codec = await ui.instantiateImageCodec(bytes,
              targetWidth: 1600, allowUpscaling: false);
          final next = (await codec.getNextFrame()).image;
          if (_disposed ||
              generation != _generation ||
              phase != ConnectionPhase.active) {
            next.dispose();
            continue;
          }
          final previous = frame;
          frame = next;
          notifyListeners();
          previous?.dispose();
        } catch (_) {
          /* The next complete JPEG can recover the stream. */
        } finally {
          codec?.dispose();
        }
      }
    } finally {
      _decoding = false;
      if (_pendingFrame != null && !_disposed) _decodeFrames(_generation);
    }
  }

  void _send(Map<String, Object> data) {
    final socket = _socket;
    if (socket != null && socket.readyState == WebSocket.open) {
      socket.add(jsonEncode(data));
    }
  }

  void input(Map<String, Object> data) {
    if (canControl) _send(data);
  }

  void release() {
    _send({'type': 'release'});
  }

  void setControl(bool enabled) {
    release();
    controlEnabled =
        enabled && phase == ConnectionPhase.active && frame != null;
    message = controlEnabled ? 'متصل · التحكم شغّال' : 'متصل · عرض فقط';
    notifyListeners();
  }

  void _fail(String reason) {
    if (_disposed) return;
    release();
    controlEnabled = false;
    phase = ConnectionPhase.error;
    message = reason;
    _heartbeat?.cancel();
    _socket?.close();
    _client?.close(force: true);
    notifyListeners();
  }

  Future<void> disconnect() async {
    ++_generation;
    release();
    controlEnabled = false;
    _heartbeat?.cancel();
    _heartbeat = null;
    await _subscription?.cancel();
    _subscription = null;
    await _socket?.close();
    _socket = null;
    _client?.close(force: true);
    _client = null;
    _pendingFrame = null;
    frame?.dispose();
    frame = null;
    phase = ConnectionPhase.idle;
    message = '';
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    disconnect();
    super.dispose();
  }
}
