"""Record a replay HTML (from f1env.render) to MP4, frame by frame.

  python record_video.py out/replay.html out/replay.mp4 [--speed 4] [--fps 30]

The page's clock is stepped explicitly and screenshotted each frame, so the video is
smooth regardless of machine speed. Uses headless Chromium (Playwright) + ffmpeg.
"""

import argparse
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

# Video layout: map + onboard/runs on top, the four corner close-ups in one row below.
VIDEO_CSS = """
body{overflow:hidden}
#wrap{grid-template-columns:1180px 1fr !important;padding:10px 14px !important;gap:10px !important}
#corners{grid-template-columns:repeat(4,1fr) !important;gap:8px !important}
.corner .cl{padding:5px 10px !important;font-size:12px}
.corner .ct{font-size:10.5px !important;padding:4px 8px 6px !important;gap:1px !important}
#controls{display:none !important}
.codebtn{display:none !important}
.run{padding:7px 12px !important}
.run .stats:not([id]){display:none !important}
.run > div[style*="pre-wrap"]{display:none !important}
#wrap{align-items:start !important}
.run .stats[id]{grid-template-columns:repeat(6,1fr) !important;margin-top:4px !important}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("mp4")
    ap.add_argument("--speed", type=float, default=4.0, help="sim seconds per video second")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--tail", type=float, default=2.0, help="seconds to hold the final frame")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": args.height}, device_scale_factor=1)
        page.goto(Path(args.html).resolve().as_uri())
        page.add_style_tag(content=VIDEO_CSS)
        page.evaluate("window.FOLLOW_ASPECT=0.62; window.CAR_PX=1.6")
        page.wait_for_timeout(300)
        tmax = page.evaluate("playing=false; tmax")
        dt = args.speed / args.fps
        n = int(tmax / dt) + 1 + int(args.tail * args.fps)
        for i in range(n):
            t = min(tmax, i * dt)
            page.evaluate(f"t={t}; draw()")
            page.screenshot(path=f"{tmp}/f{i:05d}.png")
            if i % 150 == 0:
                print(f"frame {i}/{n}", flush=True)
        browser.close()
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(args.fps), "-i", f"{tmp}/f%05d.png",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium",
             "-movflags", "+faststart", args.mp4],
            check=True,
        )
    print(args.mp4)


if __name__ == "__main__":
    main()
