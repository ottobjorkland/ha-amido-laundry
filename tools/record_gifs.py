#!/usr/bin/env python3
"""Record the demo GIFs in docs/img from docs/demo/index.html (fake data) using Chrome's DevTools protocol.

Needs: pip install pillow websockets; a Chrome started with --remote-debugging-port=9222 (override with CDP=...),
and the repo served on http://127.0.0.1:8099 (python3 -m http.server 8099 --bind 127.0.0.1).
"""
import asyncio
import base64
import io
import json
import os
import time
import urllib.request

import websockets
from PIL import Image, ImageChops, ImageDraw, ImageFont

CDP = os.environ.get("CDP", "http://127.0.0.1:9222")
BASE = os.environ.get("DEMO", "http://127.0.0.1:8099/docs/demo/index.html?lang=en")
OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "img")


class Tab:
    def __init__(self, ws):
        self.ws, self.n, self.frames, self.caption = ws, 0, [], ""

    async def call(self, method, **params):
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == self.n:
                return msg.get("result", {})

    async def js(self, expr):
        r = await self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        return r.get("result", {}).get("value")

    async def shot(self):
        r = await self.call("Page.captureScreenshot", format="png")
        return Image.open(io.BytesIO(base64.b64decode(r["data"]))).convert("RGB")

    async def record(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.frames.append((time.time(), await self.shot(), self.caption))
            await asyncio.sleep(0.03)

    def say(self, text):
        self.caption = text

    async def tap(self, sel, n=0, text=None, hold=0.9):
        await self.js(f"window.demoTap({json.dumps(sel)}, {n}, {json.dumps(text)})")
        await self.record(hold)

    @staticmethod
    def _label(im, text):
        if not text:
            return im
        im = im.copy()
        d = ImageDraw.Draw(im, "RGBA")
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 17)
        w = d.textlength(text, font=font)
        x0, y1 = (im.width - w) / 2 - 16, im.height - 26
        d.rounded_rectangle((x0, y1 - 38, x0 + w + 32, y1), radius=19, fill=(3, 169, 244, 235))
        d.text((x0 + 16, y1 - 29), text, font=font, fill=(255, 255, 255, 255))
        return im

    def save(self, name, max_ms=900, colors=96):
        frames, out, times = self.frames, [], []
        for i, (t, im, cap) in enumerate(frames):
            im = self._label(im, cap)
            dur = (frames[i + 1][0] - t) if i + 1 < len(frames) else 1.0
            if out and ImageChops.difference(out[-1], im).getbbox() is None:
                times[-1] += dur  # identical frame: just extend the previous one
            else:
                out.append(im); times.append(dur)
        pal = [im.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for im in out]
        ms = [max(40, min(max_ms, int(d * 1000))) for d in times]
        ms[-1] = 1800  # linger on the last frame
        path = os.path.join(OUT, name)
        pal[0].save(path, save_all=True, append_images=pal[1:], duration=ms, loop=0, optimize=True, disposal=1)
        print(f"{name}: {len(out)} frames, {os.path.getsize(path)/1e6:.2f} MB")
        self.frames = []


async def open_tab(width, height, url):
    req = urllib.request.Request(f"{CDP}/json/new?about:blank", method="PUT")
    target = json.load(urllib.request.urlopen(req))
    ws = await websockets.connect(target["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024)
    tab = Tab(ws)
    await tab.call("Page.enable")
    await tab.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)
    await tab.call("Page.navigate", url=url)
    await asyncio.sleep(2.5)
    return tab, target["id"]


async def close_tab(tab, tid):
    await tab.ws.close()
    urllib.request.urlopen(f"{CDP}/json/close/{tid}")


async def gif_book_cancel():
    tab, tid = await open_tab(390, 720, BASE)
    tab.say("Every free time is one tap away")
    await tab.record(1.8)
    tab.say("1 · Tap a free time")
    await tab.tap('button.slot.free', n=2, hold=1.2)
    tab.say("2 · Confirm")
    await tab.tap('.btn.go', hold=0.9)
    tab.say("3 · Booked – shown instantly")
    await tab.record(3.6)
    await tab.js("window.scrollTo(0,0)")
    tab.say("Tap your own time to cancel")
    await tab.tap('button.slot.mine', n=0, hold=1.3)
    tab.say("Cancelled – just as fast")
    await tab.tap('.btn.del', hold=3.4)
    tab.save("demo-book-cancel.gif")
    await close_tab(tab, tid)


async def gif_map():
    tab, tid = await open_tab(390, 720, BASE)
    tab.say("See where each building is")
    await tab.record(1.4)
    await tab.tap('.mapbtn', hold=3.4)
    tab.say("Tap a building number…")
    await tab.tap('.pin', n=0, text='3', hold=2.6)
    tab.say("…directions on demand")
    await tab.record(1.6)
    tab.say("Tap another one – the times follow")
    await tab.tap('.pin', n=0, text='2', hold=2.6)
    tab.save("demo-map.gif")
    await close_tab(tab, tid)


async def gif_filter():
    tab, tid = await open_tab(390, 720, BASE)
    tab.say("Laundry · Sauna · Heavy laundry")
    await tab.record(1.4)
    await tab.tap('.chip[data-type="bastu"]', hold=2.0)
    tab.say("Closest building first")
    await tab.tap('.chip[data-act="building"]', n=1, hold=2.0)
    tab.say("Switch type in one tap")
    await tab.tap('.chip[data-type="grov"]', hold=2.0)
    await tab.tap('.chip[data-type="tvatt"]', hold=2.0)
    tab.save("demo-filter.gif")
    await close_tab(tab, tid)


async def main():
    await gif_book_cancel()
    await gif_map()
    await gif_filter()


if __name__ == "__main__":
    asyncio.run(main())
