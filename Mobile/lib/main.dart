import 'dart:async';
import 'dart:math' as math;
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'pairing.dart';
import 'remote_connection.dart';

const background = Color(0xff101416);
const surface = Color(0xff1a2224);
const accent = Color(0xffcdfc6c);
const muted = Color(0xffa2b1b4);

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const SahlApp());
}

class SahlApp extends StatelessWidget {
  final RemoteConnection? connection;
  const SahlApp({super.key, this.connection});
  @override
  Widget build(BuildContext context) => MaterialApp(
      title: 'سهل ريموت',
      debugShowCheckedModeBanner: false,
      locale: const Locale('ar'),
      supportedLocales: const [Locale('ar'), Locale('en')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      theme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        scaffoldBackgroundColor: background,
        colorScheme: ColorScheme.fromSeed(
            seedColor: accent,
            brightness: Brightness.dark,
            primary: accent,
            surface: surface),
        inputDecorationTheme: InputDecorationTheme(
            filled: true,
            fillColor: background,
            border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(16),
                borderSide: const BorderSide(color: Color(0xff3b484b)))),
        filledButtonTheme: FilledButtonThemeData(
            style: FilledButton.styleFrom(
                minimumSize: const Size(0, 56),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16)),
                textStyle: const TextStyle(
                    fontFamily: 'Roboto',
                    fontSize: 16,
                    fontWeight: FontWeight.w700))),
      ),
      home: HomePage(connection: connection));
}

class HomePage extends StatefulWidget {
  final RemoteConnection? connection;
  const HomePage({super.key, this.connection});
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> with WidgetsBindingObserver {
  late final RemoteConnection connection;
  final code = TextEditingController();
  final text = TextEditingController();
  final modifiers = <String>{};
  bool searching = false, drag = false;
  String localError = '';

  @override
  void initState() {
    super.initState();
    connection = widget.connection ?? RemoteConnection();
    WidgetsBinding.instance.addObserver(this);
    connection.addListener(changed);
  }

  void changed() {
    if (mounted) {
      setState(() {
        if (!connection.canControl) modifiers.clear();
      });
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed && connection.controlEnabled) {
      connection.setControl(false);
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    connection.removeListener(changed);
    if (widget.connection == null) connection.dispose();
    code.dispose();
    text.dispose();
    super.dispose();
  }

  Future<void> scan() async {
    setState(() => localError = '');
    final pairing = await Navigator.of(context)
        .push<PairingData>(MaterialPageRoute(builder: (_) => const ScanPage()));
    if (pairing != null && mounted) await connection.connect(pairing);
  }

  Future<void> connectNumber() async {
    setState(() {
      searching = true;
      localError = '';
    });
    try {
      final pairing = await discoverByCode(code.text);
      if (mounted) await connection.connect(pairing);
    } on FormatException catch (error) {
      if (mounted) setState(() => localError = error.message);
    } catch (_) {
      if (mounted) {
        setState(() => localError =
            'ملقيناش الكمبيوتر. شغّل المشاركة عليه واتأكد إنكم على نفس الواي فاي، أو استخدم QR.');
      }
    } finally {
      if (mounted) setState(() => searching = false);
    }
  }

  void keyTap(String key) {
    connection.input({'type': 'key', 'key': key, 'down': true});
    connection.input({'type': 'key', 'key': key, 'down': false});
  }

  void click(String button) {
    connection.input({'type': 'button', 'button': button, 'down': true});
    connection.input({'type': 'button', 'button': button, 'down': false});
  }

  void modifier(String key) {
    if (!connection.canControl) return;
    final down = !modifiers.contains(key);
    connection.input({'type': 'key', 'key': key, 'down': down});
    setState(() {
      down ? modifiers.add(key) : modifiers.remove(key);
    });
  }

  @override
  Widget build(BuildContext context) {
    final active = connection.phase == ConnectionPhase.active;
    final waiting = connection.phase == ConnectionPhase.connecting ||
        connection.phase == ConnectionPhase.waiting;
    return Scaffold(
        body: SafeArea(child: LayoutBuilder(builder: (context, constraints) {
      final landscape = constraints.maxWidth > 700 && active;
      if (landscape) return _landscape();
      return SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(22, 18, 22, 24),
          child: Center(
              child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 660),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _brand(),
                        const SizedBox(height: 28),
                        if (active) ...[
                          _sessionHeader(),
                          const SizedBox(height: 16),
                          RemoteScreen(connection: connection, drag: drag),
                          const SizedBox(height: 16),
                          _controls()
                        ] else if (waiting)
                          _waiting()
                        else ...[
                          _hero(),
                          const SizedBox(height: 24),
                          _connectCard()
                        ],
                        const SizedBox(height: 24),
                        const Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(Icons.shield_outlined,
                                  color: muted, size: 16),
                              SizedBox(width: 7),
                              Flexible(
                                  child: Text('مشفّر · على شبكتك · بموافقتك',
                                      textAlign: TextAlign.center,
                                      style: TextStyle(
                                          color: muted, fontSize: 12)))
                            ]),
                      ]))));
    })));
  }

  Widget _brand() => Row(children: [
        Container(
            width: 46,
            height: 46,
            decoration: BoxDecoration(
                color: accent, borderRadius: BorderRadius.circular(14)),
            child: const Icon(Icons.north_east_rounded,
                color: background, size: 28)),
        const SizedBox(width: 12),
        const Expanded(
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('سهل ريموت',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 23, fontWeight: FontWeight.w800)),
          Text('SAHL / REMOTE',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(letterSpacing: 2, fontSize: 9, color: muted))
        ])),
        const SizedBox(width: 8),
        Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
            decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(20),
                border: Border.all(color: const Color(0xff344245))),
            child: const Row(children: [
              Icon(Icons.wifi_rounded, color: accent, size: 15),
              SizedBox(width: 5),
              Text('محلي', style: TextStyle(fontSize: 11))
            ]))
      ]);

  Widget _hero() =>
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('جهازك، أقرب لك.',
            style: TextStyle(color: accent, fontSize: 13)),
        const SizedBox(height: 12),
        const Text('شاشتك الكبيرة.\nبين إيديك.',
            style: TextStyle(
                fontSize: 38, fontWeight: FontWeight.w800, height: 1.35)),
        const SizedBox(height: 14),
        const Text(
            'وصّل بالموبايل في لحظات. امسح الكود من الكمبيوتر، وخلّي مساحة شغلك معاك.',
            style: TextStyle(color: muted, fontSize: 15, height: 1.7)),
        const SizedBox(height: 24),
        Container(
            height: 164,
            alignment: Alignment.center,
            decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(26),
                gradient: const LinearGradient(
                    colors: [Color(0xff24342c), Color(0xff172222)]),
                border: Border.all(color: const Color(0xff3d5143))),
            child: Stack(alignment: Alignment.center, children: [
              Container(
                  width: 114,
                  height: 114,
                  decoration: BoxDecoration(
                      border: Border.all(color: accent.withValues(alpha: .3)),
                      borderRadius: BorderRadius.circular(26))),
              const Icon(Icons.qr_code_2_rounded, color: accent, size: 84)
            ])),
      ]);

  Widget _connectCard() =>
      _card(Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        const Text('اتصال أسهل، بلمسة.',
            style: TextStyle(fontSize: 21, fontWeight: FontWeight.w700)),
        const SizedBox(height: 7),
        const Text('اضغط Start sharing على الكمبيوتر، وبعدها امسح QR.',
            style: TextStyle(color: muted, height: 1.6)),
        const SizedBox(height: 20),
        FilledButton.icon(
            onPressed: searching ? null : scan,
            icon: const Icon(Icons.qr_code_scanner_rounded),
            label: const Text('امسح QR الكمبيوتر')),
        const Padding(
            padding: EdgeInsets.symmetric(vertical: 19),
            child: Row(children: [
              Expanded(child: Divider()),
              Padding(
                  padding: EdgeInsets.symmetric(horizontal: 12),
                  child: Text('أو اكتب رقمه',
                      style: TextStyle(color: muted, fontSize: 12))),
              Expanded(child: Divider())
            ])),
        TextField(
            controller: code,
            keyboardType: TextInputType.number,
            textDirection: TextDirection.ltr,
            textAlign: TextAlign.center,
            maxLength: 8,
            style: const TextStyle(
                fontSize: 27, letterSpacing: 5, fontWeight: FontWeight.w700),
            decoration: const InputDecoration(
                hintText: '0000 0000',
                counterText: '',
                labelText: 'رقم الاتصال · 8 أرقام'),
            onSubmitted: (_) {
              if (!searching) connectNumber();
            }),
        const SizedBox(height: 12),
        OutlinedButton(
            onPressed: searching ? null : connectNumber,
            style: OutlinedButton.styleFrom(
                minimumSize: const Size(0, 52),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16))),
            child: Text(searching ? 'بندور على الكمبيوتر…' : 'اتصال بالرقم')),
        if (localError.isNotEmpty || connection.phase == ConnectionPhase.error)
          Padding(
              padding: const EdgeInsets.only(top: 14),
              child: Text(
                  localError.isNotEmpty ? localError : connection.message,
                  style:
                      const TextStyle(color: Color(0xffffab96), height: 1.6))),
        const SizedBox(height: 15),
        const Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(Icons.info_outline_rounded, size: 16, color: muted),
          SizedBox(width: 8),
          Expanded(
              child: Text(
                  'الجهازين على نفس الواي فاي. الكمبيوتر هيطلب موافقتك قبل عرض الشاشة.',
                  style: TextStyle(color: muted, fontSize: 12, height: 1.6)))
        ]),
      ]));

  Widget _waiting() => _card(Column(children: [
        const SizedBox(height: 22),
        const CircularProgressIndicator(color: accent),
        const SizedBox(height: 28),
        Text(connection.message,
            textAlign: TextAlign.center,
            style: const TextStyle(
                fontSize: 20, height: 1.6, fontWeight: FontWeight.w600)),
        const SizedBox(height: 14),
        const Text('المشاركة بتبدأ بعد موافقة صاحب الكمبيوتر.',
            style: TextStyle(color: muted)),
        const SizedBox(height: 24),
        OutlinedButton(
            onPressed: connection.disconnect,
            child: const Text('إلغاء الاتصال')),
        const SizedBox(height: 12)
      ]));

  Widget _sessionHeader() => Row(children: [
        const Icon(Icons.circle, size: 9, color: accent),
        const SizedBox(width: 9),
        Expanded(
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(connection.hostName,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style:
                  const TextStyle(fontWeight: FontWeight.w700, fontSize: 20)),
          Text(connection.message,
              style: const TextStyle(color: muted, fontSize: 12))
        ])),
        IconButton(
            onPressed: connection.disconnect,
            tooltip: 'إنهاء الجلسة',
            icon: const Icon(Icons.power_settings_new_rounded,
                color: Color(0xffffab96)))
      ]);

  Widget _controls() =>
      _card(Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        SwitchListTile(
            contentPadding: EdgeInsets.zero,
            value: connection.controlEnabled,
            onChanged: connection.frame == null ? null : connection.setControl,
            title: const Text('التحكم في الجهاز',
                style: TextStyle(fontWeight: FontWeight.w700)),
            subtitle: Text(
                connection.controlEnabled
                    ? 'الماوس والكيبورد شغّالين'
                    : 'عرض الشاشة فقط',
                style: const TextStyle(color: muted, fontSize: 12))),
        const Divider(height: 28),
        Opacity(
            opacity: connection.canControl ? 1 : .4,
            child: IgnorePointer(
                ignoring: !connection.canControl,
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(children: [
                        Expanded(
                            child: _tool('كليك شمال', Icons.mouse_outlined,
                                () => click('left'))),
                        const SizedBox(width: 8),
                        Expanded(
                            child: _tool('كليك يمين', Icons.ads_click_rounded,
                                () => click('right')))
                      ]),
                      const SizedBox(height: 8),
                      Row(children: [
                        Expanded(
                            child: FilterChip(
                                selected: drag,
                                onSelected: (value) {
                                  connection.release();
                                  setState(() => drag = value);
                                },
                                label: const Text('سحب باللمس'),
                                avatar: const Icon(Icons.open_with_rounded,
                                    size: 18))),
                        IconButton(
                            onPressed: () => connection
                                .input({'type': 'scroll', 'delta': 3}),
                            icon: const Icon(Icons.keyboard_arrow_up_rounded)),
                        IconButton(
                            onPressed: () => connection
                                .input({'type': 'scroll', 'delta': -3}),
                            icon: const Icon(Icons.keyboard_arrow_down_rounded))
                      ]),
                      const Divider(height: 28),
                      Wrap(spacing: 7, runSpacing: 7, children: [
                        for (final item in [
                          ('Ctrl', 'ControlLeft'),
                          ('Alt', 'AltLeft'),
                          ('Shift', 'ShiftLeft')
                        ])
                          FilterChip(
                              label: Text(item.$1),
                              selected: modifiers.contains(item.$2),
                              onSelected: (_) => modifier(item.$2)),
                        for (final item in [
                          ('Esc', 'Escape'),
                          ('Tab', 'Tab'),
                          ('⌫', 'Backspace'),
                          ('Enter ↵', 'Enter')
                        ])
                          ActionChip(
                              label: Text(item.$1),
                              onPressed: () => keyTap(item.$2))
                      ]),
                      const SizedBox(height: 16),
                      TextField(
                          controller: text,
                          minLines: 1,
                          maxLines: 3,
                          maxLength: 500,
                          decoration: InputDecoration(
                              labelText: 'اكتب من موبايلك',
                              hintText: 'عربي، إنجليزي أو Emoji…',
                              suffixIcon: IconButton(
                                  tooltip: 'إرسال النص',
                                  onPressed: () {
                                    if (text.text.isNotEmpty) {
                                      connection.input({
                                        'type': 'text',
                                        'text': String.fromCharCodes(
                                            text.text.runes.take(500))
                                      });
                                      text.clear();
                                    }
                                  },
                                  icon: const Icon(Icons.send_rounded,
                                      color: accent)))),
                    ]))),
        const SizedBox(height: 8),
        const Text('المس الشاشة للكليك. فعّل السحب لتحريك نافذة أو تحديد نص.',
            style: TextStyle(color: muted, fontSize: 11, height: 1.6)),
      ]));
  Widget _tool(String label, IconData icon, VoidCallback onTap) =>
      OutlinedButton.icon(
          onPressed: onTap,
          icon: Icon(icon, size: 17),
          label: Text(label, style: const TextStyle(fontSize: 12)),
          style: OutlinedButton.styleFrom(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 14),
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12))));
  Widget _card(Widget child) => Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
          color: surface,
          borderRadius: BorderRadius.circular(24),
          border: Border.all(color: const Color(0xff303d40))),
      child: child);
  Widget _landscape() => Padding(
      padding: const EdgeInsets.all(14),
      child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Expanded(
            flex: 3,
            child: Column(children: [
              _sessionHeader(),
              const SizedBox(height: 8),
              Expanded(
                  child: RemoteScreen(
                      connection: connection, drag: drag, expanded: true))
            ])),
        const SizedBox(width: 14),
        SizedBox(width: 300, child: SingleChildScrollView(child: _controls()))
      ]));
}

class ScanPage extends StatefulWidget {
  const ScanPage({super.key});
  @override
  State<ScanPage> createState() => _ScanPageState();
}

class _ScanPageState extends State<ScanPage> with WidgetsBindingObserver {
  final scanner = MobileScannerController(
      formats: [BarcodeFormat.qrCode],
      detectionSpeed: DetectionSpeed.noDuplicates);
  bool completed = false;
  String instruction = 'وجّه الكاميرا لرمز QR في برنامج الكمبيوتر';
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (completed) return;
    if (state == AppLifecycleState.resumed) {
      scanner.start().catchError((_) {});
    } else {
      scanner.stop().catchError((_) {});
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    scanner.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
      appBar: AppBar(title: const Text('امسح رمز الكمبيوتر'), actions: [
        IconButton(
            onPressed: () => scanner.toggleTorch().catchError((_) {}),
            icon: const Icon(Icons.flash_on_rounded))
      ]),
      body: Stack(children: [
        MobileScanner(
            controller: scanner,
            errorBuilder: (context, error, child) => const Center(
                child: Padding(
                    padding: EdgeInsets.all(30),
                    child: Text(
                        'اسمح باستخدام الكاميرا لمسح QR، أو ارجع واتصل برقم الكمبيوتر.',
                        textAlign: TextAlign.center))),
            onDetect: (capture) {
              if (completed) return;
              for (final barcode in capture.barcodes) {
                if (barcode.rawValue == null) continue;
                try {
                  final pairing = PairingData.fromQr(barcode.rawValue!);
                  completed = true;
                  scanner.stop();
                  Navigator.of(context).pop(pairing);
                  return;
                } on FormatException catch (error) {
                  setState(() => instruction = error.message);
                }
              }
            }),
        IgnorePointer(
            child: Center(
                child: Container(
                    width: 256,
                    height: 256,
                    decoration: BoxDecoration(
                        border: Border.all(color: accent, width: 3),
                        borderRadius: BorderRadius.circular(28))))),
        Positioned(
            left: 24,
            right: 24,
            bottom: 40,
            child: Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                    color: background.withValues(alpha: .92),
                    borderRadius: BorderRadius.circular(20)),
                child: Text(instruction,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 16, height: 1.6)))),
      ]));
}

class RemoteScreen extends StatefulWidget {
  final RemoteConnection connection;
  final bool drag, expanded;
  const RemoteScreen(
      {super.key,
      required this.connection,
      required this.drag,
      this.expanded = false});
  @override
  State<RemoteScreen> createState() => _RemoteScreenState();
}

class _RemoteScreenState extends State<RemoteScreen> {
  final focus = FocusNode();
  int? pointer;
  bool pressed = false, moved = false;
  String button = 'left';
  Offset start = Offset.zero;
  int lastMove = 0;
  @override
  void dispose() {
    focus.dispose();
    super.dispose();
  }

  Offset? point(Offset local, Size size, {bool clamp = false}) {
    final image = widget.connection.frame;
    if (image == null) return null;
    final scale =
        math.min(size.width / image.width, size.height / image.height);
    final width = image.width * scale, height = image.height * scale;
    final x = (local.dx - (size.width - width) / 2) / width,
        y = (local.dy - (size.height - height) / 2) / height;
    if (!clamp && (x < 0 || x > 1 || y < 0 || y > 1)) return null;
    return Offset(x.clamp(0, 1).toDouble(), y.clamp(0, 1).toDouble());
  }

  void move(Offset? position, {bool force = false}) {
    if (position == null) return;
    final now = DateTime.now().millisecondsSinceEpoch;
    if (!force && now - lastMove < 33) return;
    lastMove = now;
    widget.connection
        .input({'type': 'move', 'x': position.dx, 'y': position.dy});
  }

  @override
  Widget build(BuildContext context) {
    final image = widget.connection.frame;
    Widget screen = LayoutBuilder(builder: (context, constraints) {
      final size = Size(constraints.maxWidth, constraints.maxHeight);
      return Focus(
          focusNode: focus,
          onFocusChange: (hasFocus) {
            if (!hasFocus) widget.connection.release();
          },
          onKeyEvent: (_, event) {
            if (!widget.connection.canControl) return KeyEventResult.ignored;
            final key = browserKey(event.physicalKey);
            if (key == null) return KeyEventResult.ignored;
            widget.connection.input(
                {'type': 'key', 'key': key, 'down': event is! KeyUpEvent});
            return KeyEventResult.handled;
          },
          child: Listener(
            onPointerDown: (event) {
              if (!widget.connection.canControl || pointer != null) return;
              final position = point(event.localPosition, size);
              if (position == null) return;
              focus.requestFocus();
              pointer = event.pointer;
              start = event.localPosition;
              moved = false;
              button =
                  event.buttons & kSecondaryMouseButton != 0 ? 'right' : 'left';
              move(position, force: true);
              pressed = event.kind == PointerDeviceKind.mouse || widget.drag;
              if (pressed) {
                widget.connection
                    .input({'type': 'button', 'button': button, 'down': true});
              }
            },
            onPointerMove: (event) {
              if (pointer != event.pointer) return;
              if ((event.localPosition - start).distance > 9) moved = true;
              move(point(event.localPosition, size, clamp: true));
            },
            onPointerUp: (event) {
              if (pointer != event.pointer) return;
              move(point(event.localPosition, size, clamp: true), force: true);
              if (pressed) {
                widget.connection
                    .input({'type': 'button', 'button': button, 'down': false});
              } else if (!moved) {
                widget.connection
                    .input({'type': 'button', 'button': 'left', 'down': true});
                widget.connection
                    .input({'type': 'button', 'button': 'left', 'down': false});
              }
              pointer = null;
              pressed = false;
            },
            onPointerCancel: (_) {
              widget.connection.release();
              pointer = null;
              pressed = false;
            },
            onPointerHover: (event) => move(point(event.localPosition, size)),
            onPointerSignal: (event) {
              if (event is PointerScrollEvent && event.scrollDelta.dy != 0) {
                final delta = (-event.scrollDelta.dy / 100).round();
                widget.connection.input({
                  'type': 'scroll',
                  'delta':
                      (delta == 0 ? (event.scrollDelta.dy > 0 ? -1 : 1) : delta)
                          .clamp(-10, 10)
                });
              }
            },
            child: Container(
                color: Colors.black,
                alignment: Alignment.center,
                child: image == null
                    ? const CircularProgressIndicator(color: accent)
                    : RawImage(image: image, fit: BoxFit.contain)),
          ));
    });
    if (!widget.expanded) {
      screen = AspectRatio(
          aspectRatio: image == null ? 16 / 9 : image.width / image.height,
          child: screen);
    }
    return ClipRRect(borderRadius: BorderRadius.circular(20), child: screen);
  }
}

String? browserKey(PhysicalKeyboardKey key) {
  final usage = key.usbHidUsage;
  if (usage >= 0x70004 && usage <= 0x7001d) {
    return 'Key${String.fromCharCode(65 + usage - 0x70004)}';
  }
  if (usage >= 0x7001e && usage <= 0x70026) {
    return 'Digit${usage - 0x7001e + 1}';
  }
  if (usage >= 0x7003a && usage <= 0x70045) return 'F${usage - 0x7003a + 1}';
  return {
    0x70027: 'Digit0',
    0x70028: 'Enter',
    0x70029: 'Escape',
    0x7002a: 'Backspace',
    0x7002b: 'Tab',
    0x7002c: 'Space',
    0x7004f: 'ArrowRight',
    0x70050: 'ArrowLeft',
    0x70051: 'ArrowDown',
    0x70052: 'ArrowUp',
    0x700e0: 'ControlLeft',
    0x700e1: 'ShiftLeft',
    0x700e2: 'AltLeft',
    0x700e4: 'ControlRight',
    0x700e5: 'ShiftRight',
    0x700e6: 'AltRight'
  }[usage];
}
