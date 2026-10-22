// Test certificate/key are public fixtures for loopback tests, never production credentials.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sahl_remote_mobile/pairing.dart';
import 'package:sahl_remote_mobile/remote_connection.dart';

Future<void> until(bool Function() condition) async {
  final deadline = DateTime.now().add(const Duration(seconds: 8));
  while (!condition()) {
    if (DateTime.now().isAfter(deadline)) {
      throw TimeoutException('Condition timed out');
    }
    await Future<void>.delayed(const Duration(milliseconds: 15));
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  HttpOverrides.global =
      null; // Real IO, limited to the loopback test server below.
  late HttpServer server;
  late String pin;
  late RemoteConnection client;
  final sockets = <WebSocket>[];
  final received = <Map<String, dynamic>>[];
  setUp(() async {
    sockets.clear();
    received.clear();
    final tls = SecurityContext()
      ..useCertificateChain('test/fixtures/certificate.pem')
      ..usePrivateKey('test/fixtures/private-key.pem');
    final der = base64Decode(File('test/fixtures/certificate.pem')
        .readAsStringSync()
        .replaceAll(RegExp(r'-----[^-]+-----|\s'), ''));
    pin = sha256.convert(der).toString();
    server = await HttpServer.bindSecure(InternetAddress.loopbackIPv4, 0, tls);
    server.listen((request) async {
      final socket = await WebSocketTransformer.upgrade(request);
      sockets.add(socket);
      socket.listen((raw) {
        final message = jsonDecode(raw as String) as Map<String, dynamic>;
        received.add(message);
        if (message['type'] == 'pair') {
          socket.add(jsonEncode({'type': 'waiting'}));
        }
      }, onError: (_) {});
    }, onError: (_) {});
    client = RemoteConnection();
  });
  tearDown(() async {
    await client.disconnect();
    client.dispose();
    for (final socket in sockets) {
      await socket.close();
    }
    await server.close(force: true);
  });
  PairingData pairing(String fingerprint) => PairingData(
      host: '127.0.0.1',
      port: server.port,
      code: '00123456',
      fingerprint: fingerprint);

  test('native TLS pin + pairing + consent + JPEG + control + disconnect',
      () async {
    await client.connect(pairing(pin));
    await until(() => client.phase == ConnectionPhase.waiting);
    expect(received.single['code'], '00123456');
    expect(client.frame, isNull);
    client.input({'type': 'move', 'x': .5, 'y': .5});
    expect(received.length, 1);
    sockets.single.add(jsonEncode({
      'type': 'approved',
      'host': 'Synthetic host',
      'width': 64,
      'height': 36
    }));
    sockets.single.add(File('test/fixtures/synthetic.jpg').readAsBytesSync());
    await until(() => client.frame != null);
    expect(client.frame!.width, 64);
    expect(client.controlEnabled, isFalse);
    client.setControl(true);
    client.input({'type': 'move', 'x': .5, 'y': .5});
    client.input({'type': 'text', 'text': 'أهلًا من Flutter 🙂'});
    await until(() => received.any((m) => m['type'] == 'text'));
    expect(received.where((m) => m['type'] == 'text').single['text'],
        'أهلًا من Flutter 🙂');
    client.setControl(false);
    final before = received.where((m) => m['type'] == 'move').length;
    client.input({'type': 'move', 'x': .9, 'y': .9});
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(received.where((m) => m['type'] == 'move').length, before);
    await client.disconnect();
    expect(client.phase, ConnectionPhase.idle);
    expect(client.frame, isNull);
    expect(received.where((m) => m['type'] == 'release').isNotEmpty, isTrue);
  });
  test('mismatched certificate is rejected before pairing credentials are sent',
      () async {
    await client.connect(pairing(List.filled(64, '0').join()));
    await until(() => client.phase == ConnectionPhase.error);
    expect(received, isEmpty);
    expect(client.controlEnabled, isFalse);
  });
}
