# Verification — 22 October 2026

## Version 0.3.1 — exit and protected-desktop recovery

- The final v0.3.1 executable passed its bundled imports, TLS creation, QR, JPEG and web/download-asset self-check. The runtime's required companion CA policy file is included by the build script. Both existing EXE filenames were replaced and match the versioned delivery's SHA-256. Interactive Exit-button and real-UAC checks remain manual; Computer Use testing was interrupted.

- 55 Python tests passed. New cases cover bounded window shutdown without the event poll, both workers stopping, failed input release and a stuck capture thread; protected desktop detection closes Win32 handles and prevents capture/input.
- A synthetic protected desktop paused an already-approved HTTPS/WSS session, rejected input while paused, responded to pings, resumed JPEGs and accepted input on the same connection with the same pairing code. A simulated UIPI input failure returned a nonfatal notice and recovered on the same session. Stop also worked during a protected-desktop pause.
- A read-only Win32 desktop availability probe returned true on this computer, without screen capture or input injection. Actual UAC prompts, elevated applications and a physical phone still require manual acceptance testing.
- Added explicit Arabic Exit controls and Ctrl+Q, and a shutdown callback independent of UI event polling. If a worker is still unresponsive after five seconds, the process terminates after a best-effort input release instead of leaving a hidden listener.

## Version 0.3 — LAN web downloads

- 46 Python tests passed, including 8 new download-server integration tests. APK/EXE responses match the release bytes, use attachment filenames and correct MIME types, and support HEAD and byte ranges for resuming.
- The download QR was decoded with an independent ZXing decoder and matches the current page URL. Missing releases have disabled links; file listings, traversal, control endpoints and unrecognized Host headers are rejected.
- The download server is separate from the TLS screen-sharing listener. Opening downloads does not construct a desktop adapter or start capture/input. Its worker belongs to the desktop window and stops on app close.
- Both complete release files were streamed from the packaged application's LAN HTTP listener and their SHA-256 hashes matched the source APK and EXE. A resumed byte-range request also matched each source file.
- The page was inspected in the in-app browser: both enabled download links, versions, sizes, installation steps and the QR are present, with no horizontal overflow in its 699px viewport. The browser automation download helper timed out; complete transfers were verified with an HTTP client instead. A physical phone download/install is still a manual check.
- The v0.3 packaged EXE passed its bundled dependency, TLS, QR, synthetic JPEG and all download-page asset checks. The running download-only instance listens on port 8088; the remote-control listener was confirmed closed.
- Install test-only `zxing-cpp` to run the QR decoder check. The production executable does not need it.

## Version 0.2

- 38 Windows/backend tests passed: the previous 31 plus 7 QR and local discovery tests. Discovery was exercised on loopback with valid, invalid and unavailable hosts. Arabic/Persian digits and leading zeros are retained.
- QR output decoded successfully with an independent ZXing decoder at the size shown in the host UI.
- 11 Flutter tests passed: QR parsing and local address restrictions, native pinned TLS and mismatch rejection before credentials, consent/frame/control states, Arabic/emoji input, home layout at 320/390/800px, and synthetic remote-control layouts at 390px portrait and 900px landscape with correct center pointer mapping.
- A real Flutter client connected to the production Python RemoteServer over loopback TLS, using a synthetic desktop only. The Python host received pointer, key, Arabic/emoji text and wheel commands; the connection and listener closed cleanly.
- Browser handoff from the QR URL passed an actual HTTPS/WSS integration check. The code fragment was removed from the address bar, pairing began automatically, host approval remained required, and the viewer began in view-only mode.
- The new desktop executable passed its bundled TLS/JPEG/QR/assets self-check. Its UI sizes were checked with synthetic request and stopped states, including DPI scaling.
- The Android release APK built successfully. Camera permission and scanning on a physical phone, real desktop input, cross-device Wi-Fi, and iOS remain manual checks; no real screen/input/camera was used by automated tests.

## Original version baseline

- 19 loopback HTTPS/WebSocket tests passed: code validation/expiry/rotation, local consent before any frame/input, single-controller limits, Origin/Host checks, pairing rate limits, input bounds, malformed pending JSON, release on blur/disconnect/host stop, and browser/upgrade security headers.
- 12 Windows adapter tests passed with a fake user32 API and generated images: x64 INPUT ABI, pointer mapping, wheel/key events, Arabic/emoji UTF-16 encoding, failed SendInput handling and release tracking.
- Real browser ↔ production RemoteServer HTTPS/WSS integration passed on loopback with a synthetic desktop: JPEG rendering, explicit control opt-in, pointer and keyboard, Arabic text, signed integer wheel events, disconnect cleanup. Zero browser script errors. The test listener was closed afterwards.
- Browser layouts checked at widths 320, 390, 820 and 1365 px with synthetic content. No horizontal overflow was found.
- Host UI layout checked with synthetic connection requests: all requested content fits within a 650px-tall client area; approval replaces the pairing card so the Stop control stays accessible.
- The packaged x64 executable passed its own import, Tcl, asset, TLS-certificate creation and synthetic JPEG encoder checks. It bundles Python and requires no Python/Node installation on the target PC.

Tests used synthetic frames and inert input APIs. **Real desktop capture/injection and an actual phone-to-PC LAN connection have not been exercised in this session.** Performance is a target, not a benchmark. The manual acceptance check is to run the executable, pair a phone on the same Wi-Fi, approve it locally and try the screen, click, text and Stop functions.

Run the portable source tests from this folder after installing requirements:

```powershell
python -m unittest discover -s tests -v
```
