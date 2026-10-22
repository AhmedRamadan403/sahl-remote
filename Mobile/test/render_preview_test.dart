// Optional artifact rendering of our widgets; no camera or real desktop access.
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sahl_remote_mobile/main.dart';

void main() {
  const destination = String.fromEnvironment('SAHL_RENDER_PATH');
  testWidgets('Render mobile interface preview', (tester) async {
    tester.view.physicalSize = const Size(390, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.runAsync(() async {
      final body = FontLoader('Roboto')
        ..addFont(Future.value(ByteData.sublistView(
            File('C:/Windows/Fonts/segoeui.ttf').readAsBytesSync())));
      final icons = FontLoader('MaterialIcons')
        ..addFont(Future.value(ByteData.sublistView(File(
                'C:/dev/flutter/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf')
            .readAsBytesSync())));
      await body.load();
      await icons.load();
    });
    final key = GlobalKey();
    await tester.pumpWidget(RepaintBoundary(key: key, child: const SahlApp()));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final boundary =
        key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
    await tester.runAsync(() async {
      final image = await boundary.toImage(pixelRatio: 2);
      final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
      File(destination).writeAsBytesSync(bytes!.buffer.asUint8List());
      image.dispose();
    });
  }, skip: destination.isEmpty);
}
