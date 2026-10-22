import 'package:flutter_test/flutter_test.dart';
import 'package:sahl_remote_mobile/pairing.dart';

void main() {
  final pin = List.filled(64, 'a').join();
  test('QR parses endpoint, leading-zero code, and strict certificate pin', () {
    final data = PairingData.fromQr(
        'https://192.168.100.8:8443/#v=1&code=00123456&fp=$pin');
    expect(data.host, '192.168.100.8');
    expect(data.code, '00123456');
    expect(data.fingerprint, pin);
    expect(data.socketUrl, 'wss://192.168.100.8:8443/ws');
  });
  test(
      'QR rejects external destinations, downgrade, userinfo, and malformed tokens',
      () {
    for (final url in [
      'http://192.168.1.2:8443/#v=1&code=12345678&fp=$pin',
      'https://evil.example:8443/#v=1&code=12345678&fp=$pin',
      'https://8.8.8.8:8443/#v=1&code=12345678&fp=$pin',
      'https://attacker@192.168.1.2:8443/#v=1&code=12345678&fp=$pin',
      'https://192.168.1.2:8443/path#v=1&code=12345678&fp=$pin',
      'https://192.168.1.2:8443/?code=12345678#v=1&code=12345678&fp=$pin',
      'https://192.168.1.2:8443/#v=1&code=1234567&fp=$pin',
      'https://192.168.1.2:8443/#v=1&code=12345678&fp=invalid',
    ]) {
      expect(() => PairingData.fromQr(url), throwsFormatException, reason: url);
    }
  });
  test('numeric input accepts Arabic and Persian digits', () {
    expect(normalizeCode('٠٠١٢ ٣٤٥٦'), '00123456');
    expect(normalizeCode('۰۰۱۲ ۳۴۵۶'), '00123456');
  });
  test('only explicit RFC1918/loopback addresses are accepted', () {
    expect(isLanHost('192.168.1.9'), isTrue);
    expect(isLanHost('172.16.1.9'), isTrue);
    expect(isLanHost('172.32.1.9'), isFalse);
    expect(isLanHost('10.1.1.1'), isTrue);
    expect(isLanHost('example.com'), isFalse);
    expect(isLanHost('100.64.1.1'), isFalse);
  });
}
