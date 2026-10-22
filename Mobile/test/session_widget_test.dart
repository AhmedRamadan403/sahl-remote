import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sahl_remote_mobile/main.dart';
import 'package:sahl_remote_mobile/remote_connection.dart';

class SyntheticConnection extends RemoteConnection {
  final inputs = <Map<String, Object>>[];
  @override
  void input(Map<String, Object> data) {
    if (canControl) inputs.add(Map.of(data));
  }
}

void main() {
  for (final size in [const Size(390, 1000), const Size(900, 650)]) {
    testWidgets('Synthetic session fits $size and maps the center correctly',
        (tester) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final image = await tester.runAsync(() async {
        final codec = await ui.instantiateImageCodec(
            File('test/fixtures/synthetic.jpg').readAsBytesSync());
        final image = (await codec.getNextFrame()).image;
        codec.dispose();
        return image;
      });
      final client = SyntheticConnection()
        ..phase = ConnectionPhase.active
        ..hostName = 'Synthetic PC'
        ..frame = image;
      await tester.pumpWidget(SahlApp(connection: client));
      await tester.pumpAndSettle();
      expect(client.controlEnabled, isFalse);
      expect(tester.takeException(), isNull);
      await tester.ensureVisible(find.byType(Switch));
      await tester.tap(find.byType(Switch));
      await tester.pumpAndSettle();
      expect(client.controlEnabled, isTrue);
      await tester.ensureVisible(find.byType(RawImage));
      await tester.tapAt(tester.getCenter(find.byType(RawImage)));
      await tester.pump();
      final move = client.inputs.firstWhere((m) => m['type'] == 'move');
      expect(move['x'], closeTo(.5, .01));
      expect(move['y'], closeTo(.5, .01));
      expect(client.inputs.where((m) => m['type'] == 'button').length, 2);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      await client.disconnect();
      client.dispose();
    });
  }
}
