import 'dart:async';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:sahl_remote_mobile/pairing.dart';
import 'package:sahl_remote_mobile/remote_connection.dart';

void main() {
  const qr = String.fromEnvironment('SAHL_INTEROP_QR');
  TestWidgetsFlutterBinding.ensureInitialized();
  HttpOverrides.global = null;
  test('Flutter client talks to the Python host over pinned TLS', () async {
    final client = RemoteConnection();
    Future<void> until(bool Function() condition) async {
      final deadline = DateTime.now().add(const Duration(seconds: 10));
      while (!condition()) {
        if (DateTime.now().isAfter(deadline)) {
          throw TimeoutException(client.message);
        }
        await Future<void>.delayed(const Duration(milliseconds: 20));
      }
    }

    try {
      await client.connect(PairingData.fromQr(qr));
      await until(
          () => client.phase == ConnectionPhase.active && client.frame != null);
      expect(client.controlEnabled, isFalse);
      client.setControl(true);
      client.input({'type': 'move', 'x': .5, 'y': .5});
      client.input({'type': 'key', 'key': 'KeyA', 'down': true});
      client.input({'type': 'key', 'key': 'KeyA', 'down': false});
      client.input({'type': 'text', 'text': 'من Flutter إلى Python 🙂'});
      client.input({'type': 'scroll', 'delta': 3});
      await Future<void>.delayed(const Duration(milliseconds: 120));
      await client.disconnect();
      expect(client.phase, ConnectionPhase.idle);
    } finally {
      await client.disconnect();
      client.dispose();
    }
  },
      skip: qr.isEmpty
          ? 'Pass a synthetic loopback host QR with --dart-define=SAHL_INTEROP_QR=...'
          : false);
}
