import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sahl_remote_mobile/main.dart';

void main() {
  for (final width in [320.0, 390.0, 800.0]) {
    testWidgets('Arabic pairing home fits ${width.toInt()}px without overflow',
        (tester) async {
      tester.view.physicalSize = Size(width, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(const SahlApp());
      await tester.pumpAndSettle();
      expect(find.text('سهل ريموت'), findsOneWidget);
      expect(find.text('امسح QR الكمبيوتر'), findsOneWidget);
      expect(find.text('اتصال بالرقم'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
}
