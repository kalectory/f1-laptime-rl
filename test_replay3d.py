"""Check the standalone replay: python test_replay3d.py (requires Playwright)."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def main():
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(QuietHandler, directory=str(ROOT))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/replay3d/?capture&comparison=champions&camera=f1"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                executable_path=os.environ.get("CHROMIUM_EXECUTABLE"),
                args=["--enable-webgl", "--use-gl=angle", "--use-angle=swiftshader",
                      "--enable-unsafe-swiftshader"],
            )
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("response", lambda response: errors.append(response.url)
                    if response.status >= 400 else None)
            page.goto(url)
            page.wait_for_function("window.replay3d", timeout=60000)
            assert "Trained Qwen" in page.locator("#drivers").inner_text()
            shots = page.evaluate("replay3d.state.broadcastShots")
            assert {"drone", "front", "trackside", "cockpit", "chase", "finish"} <= {
                shot["kind"] for shot in shots
            }
            assert all(b["start"] - a["start"] >= 2.5
                       for a, b in zip(shots, shots[1:]) if b["kind"] != "finish")
            for shot in shots:
                page.evaluate("t => replay3d.render(t)", shot["start"] + .1)
                state = page.evaluate("replay3d.state")
                assert state["broadcastShot"] == shot
                assert all(math.isfinite(v) for v in state["cameraPosition"])
            page.evaluate("replay3d.render(12)")
            before = page.evaluate("replay3d.state")
            page.evaluate("replay3d.render(60); replay3d.render(12)")
            assert before == page.evaluate("replay3d.state"), "Scrubbing changed camera"
            page.locator('[data-driver="1"]').click()
            assert page.evaluate("replay3d.state.mode") == "chase"
            page.locator('[data-camera="f1"]').click()
            page.evaluate("replay3d.render(0)")
            assert all(abs(pos[0]) < 1e-8 for pos in page.evaluate("replay3d.state.positions"))
            for i, lap in enumerate(page.evaluate("replay3d.state.laps")):
                page.evaluate("t => replay3d.render(t)", lap - .001)
                assert page.evaluate("replay3d.state.positions")[i][0] < 0
                page.evaluate("t => replay3d.render(t)", lap)
                assert abs(page.evaluate("replay3d.state.positions")[i][0]) < 1e-8
            page.set_viewport_size({"width": 390, "height": 844})
            page.evaluate("replay3d.render(12)")
            assert page.locator('[data-camera="f1"]').is_visible()

            # A synthetic overtake checks that the director reacts to a lead change,
            # including a pass occurring during the minimum shot duration.
            synthetic = json.loads((ROOT / "replay3d/data.json").read_text())
            for i, run in enumerate(synthetic["comparisons"]["champions"]["runs"]):
                run["lap"] = 30 + i
                run["trace"] = [[t / 4, (50 + 2*i)*t/4 - 20*i, 0, 0, 50 + 2*i,
                                 0, 1, 0, 0, (50 + 2*i)*t/4 - 20*i] for t in range(125)]
            page.route("**/data.json", lambda route: route.fulfill(json=synthetic))
            page.reload()
            page.wait_for_function("window.replay3d", timeout=60000)
            passes = page.evaluate('replay3d.state.broadcastShots.filter(s => s.reason === "Lead change")')
            assert len(passes) == 1 and passes[0]["driver"] == 0
            assert passes[0]["kind"] == "cockpit" and passes[0]["start"] > 10
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print("Standalone replay checks passed.")


if __name__ == "__main__":
    main()
