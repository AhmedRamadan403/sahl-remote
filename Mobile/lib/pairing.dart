import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'package:crypto/crypto.dart';

String normalizeCode(String input) {
  const arabic = '٠١٢٣٤٥٦٧٨٩';
  const persian = '۰۱۲۳۴۵۶۷۸۹';
  final result = StringBuffer();
  for (final char in input.split('')) {
    final a = arabic.indexOf(char), p = persian.indexOf(char);
    if (a >= 0) {
      result.write(a);
    } else if (p >= 0) {
      result.write(p);
    } else if (RegExp(r'^[0-9]$').hasMatch(char)) {
      result.write(char);
    }
  }
  return result.toString();
}

bool isLanHost(String value) {
  final address = InternetAddress.tryParse(value);
  if (address == null || address.type != InternetAddressType.IPv4) return false;
  final p = address.rawAddress;
  return p[0] == 10 ||
      p[0] == 127 ||
      (p[0] == 192 && p[1] == 168) ||
      (p[0] == 172 && p[1] >= 16 && p[1] <= 31);
}

class PairingData {
  final String host, code, fingerprint;
  final int port;
  const PairingData(
      {required this.host,
      required this.port,
      required this.code,
      required this.fingerprint});
  String get origin => 'https://$host:$port';
  String get socketUrl => 'wss://$host:$port/ws';

  factory PairingData.fromQr(String raw) {
    if (raw.length > 1024) throw const FormatException('رمز QR غير صالح.');
    final uri = Uri.tryParse(raw);
    if (uri == null ||
        uri.scheme != 'https' ||
        !isLanHost(uri.host) ||
        uri.userInfo.isNotEmpty ||
        (uri.path != '/' && uri.path.isNotEmpty) ||
        uri.hasQuery) {
      throw const FormatException('امسح رمز سهل ريموت الظاهر على الكمبيوتر.');
    }
    final fields = Uri.splitQueryString(uri.fragment);
    final code = fields['code'] ?? '';
    final pin = (fields['fp'] ?? '').toLowerCase();
    if (fields['v'] != '1' ||
        uri.port < 1024 ||
        uri.port > 65535 ||
        !RegExp(r'^[0-9]{8}$').hasMatch(code) ||
        !RegExp(r'^[0-9a-f]{64}$').hasMatch(pin)) {
      throw const FormatException(
          'رمز الاتصال غير مكتمل. اعرض QR جديدًا من الكمبيوتر.');
    }
    return PairingData(
        host: uri.host, port: uri.port, code: code, fingerprint: pin);
  }
}

String makeProof(String code, String nonce, int port, String fingerprint) =>
    Hmac(sha256, ascii.encode(code))
        .convert(ascii.encode('$nonce|$port|$fingerprint'))
        .toString();

Future<PairingData> discoverByCode(String input) async {
  final code = normalizeCode(input);
  if (!RegExp(r'^[0-9]{8}$').hasMatch(code)) {
    throw const FormatException('اكتب رقم الكمبيوتر كاملًا: 8 أرقام.');
  }
  final random = Random.secure();
  final nonce = List.generate(
      16, (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
  final socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);
  socket.broadcastEnabled = true;
  final query = utf8
      .encode(jsonEncode({'service': 'sahl-remote', 'v': 1, 'nonce': nonce}));
  void broadcast() {
    for (final host in ['255.255.255.255', '127.0.0.1']) {
      try {
        socket.send(query, InternetAddress(host), 38443);
      } on SocketException {/* Try the other endpoint. */}
    }
  }

  broadcast();
  final timer = Timer.periodic(const Duration(seconds: 1), (_) => broadcast());
  try {
    return await socket
        .where((e) => e == RawSocketEvent.read)
        .asyncMap((_) async {
          final packet = socket.receive();
          if (packet == null ||
              packet.data.length > 2048 ||
              !isLanHost(packet.address.address)) {
            return null;
          }
          try {
            final row = jsonDecode(utf8.decode(packet.data));
            if (row is! Map ||
                row['service'] != 'sahl-remote' ||
                row['v'] != 1 ||
                row['nonce'] != nonce) {
              return null;
            }
            final port = row['port'], pin = row['fp'];
            if (port is! int ||
                port < 1024 ||
                port > 65535 ||
                pin is! String ||
                !RegExp(r'^[0-9a-f]{64}$').hasMatch(pin) ||
                row['proof'] != makeProof(code, nonce, port, pin)) {
              return null;
            }
            return PairingData(
                host: packet.address.address,
                port: port,
                code: code,
                fingerprint: pin);
          } on FormatException {
            return null;
          }
        })
        .where((result) => result != null)
        .cast<PairingData>()
        .first
        .timeout(const Duration(seconds: 5));
  } finally {
    timer.cancel();
    socket.close();
  }
}
