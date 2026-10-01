"""Dashboard screenshots via the Chrome DevTools protocol, waiting (in real time) until every map tile has loaded.
More reliable than shoot.sh, whose --screenshot mode can capture blurry, half-loaded basemap tiles.

    ../../.venv/bin/python shoot_cdp.py name "query-string" [name "query-string" ...]
    e.g. ../../.venv/bin/python shoot_cdp.py ui_overview "run=20260314_pace&shot=1"

Needs the app on http://localhost:8000 (or PORT) and Google Chrome.
"""
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HERE = Path(__file__).resolve().parent
DEBUG_PORT = 9333
TILES_DONE = ("document.querySelectorAll('.leaflet-tile').length > 0 && "
              "document.querySelectorAll('.leaflet-tile:not(.leaflet-tile-loaded)').length === 0")


async def shoot(ws_url: str, shots: list[tuple[str, str]], port: str):
    async with websockets.connect(ws_url, max_size=2 ** 28) as ws:
        n = 0

        async def call(method, **params):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": method, "params": params}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == n:
                    return msg.get("result", {})

        await call("Emulation.setDeviceMetricsOverride", width=1600, height=900, deviceScaleFactor=1.5, mobile=False)
        for name, query in shots:
            await call("Page.navigate", url=f"http://localhost:{port}/?{query}")
            await asyncio.sleep(3)
            t0 = time.time()
            while time.time() - t0 < 40:  # wait for the basemap tiles at the final zoom
                r = await call("Runtime.evaluate", expression=TILES_DONE, returnByValue=True)
                if r.get("result", {}).get("value"):
                    break
                await asyncio.sleep(0.5)
            await asyncio.sleep(2)  # let canvas layers draw a few frames
            png = await call("Page.captureScreenshot", format="png")
            (HERE / f"{name}.png").write_bytes(base64.b64decode(png["data"]))
            print(f"{name}.png  ({time.time() - t0:.0f} s)")


def main():
    args = sys.argv[1:]
    if not args or len(args) % 2:
        sys.exit(__doc__)
    shots = list(zip(args[::2], args[1::2]))
    port = os.environ.get("PORT", "8000")
    profile = tempfile.mkdtemp()
    chrome = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1600,900",
                               f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json"))
                ws_url = next(p["webSocketDebuggerUrl"] for p in pages if p.get("type") == "page")
                break
            except Exception:
                time.sleep(0.2)
        else:
            sys.exit("Chrome did not start")
        asyncio.run(shoot(ws_url, shots, port))
    finally:
        chrome.terminate()


if __name__ == "__main__":
    main()
