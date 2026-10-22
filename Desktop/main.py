"""Sahl Remote Windows entry point."""
import json
from pathlib import Path
import sys


def self_check(destination):
    import aiohttp
    import cryptography
    import ctypes
    import io
    import PIL
    from PIL import Image
    import tempfile
    import tkinter
    import windows_platform
    from host import resource_directory
    from server import make_tls_context
    web = resource_directory()
    report = {
        "application": "Sahl Remote", "version": "0.3.1", "python": sys.version.split()[0],
        "aiohttp": aiohttp.__version__, "Pillow": PIL.__version__,
        "cryptography": cryptography.__version__,
        "tcl": tkinter.Tcl().eval("info patchlevel"),
        "web_assets_present": all((web / name).is_file() for name in ("index.html", "app.js", "styles.css")),
        "download_assets_present": all((web / "downloads" / name).is_file() for name in ("index.html", "app.js", "style.css")),
        "real_screen_capture": False, "real_input_injection": False,
        "input_structure_bytes": ctypes.sizeof(windows_platform.INPUT),
    }
    with tempfile.TemporaryDirectory(prefix="sahl-selfcheck-") as directory:
        context, fingerprint = make_tls_context(Path(directory), ["127.0.0.1"])
        report["tls_certificate_created"] = len(fingerprint) == 95
    with Image.new("RGB", (64, 36), "#1b2432") as frame:
        output = io.BytesIO()
        frame.save(output, format="JPEG")
        report["synthetic_jpeg_encoded"] = output.getvalue().startswith(b"\xff\xd8")
    import qrcode
    from pairing import pairing_url
    qr = qrcode.make(pairing_url('127.0.0.1', 8443, '00123456', 'a'*64))
    report['qr_generated'] = qr.size[0] > 100
    Path(destination).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["web_assets_present"] and report["download_assets_present"] else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--self-check":
        try:
            result = self_check(sys.argv[2])
        except Exception:
            import traceback
            Path(sys.argv[2]).write_text(json.dumps({"application": "Sahl Remote", "self_check_error": traceback.format_exc()}, indent=2), encoding="utf-8")
            result = 1
        raise SystemExit(result)
    from host import main
    main(start_downloads="--downloads" in sys.argv)
