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
            page.on("console", lambda message: errors.append(message.text)
                    if message.type == "error" else None)
            page.on("response", lambda response: errors.append(response.url)
                    if response.status >= 400 else None)
            page.goto(url)
            page.wait_for_function("window.replay3d", timeout=60000)
            scenery = page.evaluate('replay3d.state.scenery')
            assert scenery['grandstands'] >= 100 and scenery['spectators'] >= 50000
            assert scenery['standingFans'] > 1000 and scenery['cheeringArms'] > 100000
            assert scenery['pitCrew'] >= 80
            assert scenery['trees'] >= 1000 and scenery['parkedCars'] > 50
            assert "Trained Qwen" in page.locator("#drivers").inner_text()
            assert "GPT-6 Astra" in page.locator("#drivers").inner_text()
            assert page.locator("#drivers .lap").count() == 3
            for time in [5, 5.03, 5.06, 8, 12]:
                page.evaluate('t => replay3d.render(t)', time)
                state = page.evaluate('replay3d.state')
                assert all(state['visibleCars'])
                assert state['carOpacity'][:2] == [.6, .6]
                assert .6 <= state['carOpacity'][2] <= 1
                assert state['visibleCars'][state['selected']]
                assert page.locator('#hint, #gap').count() == 0
            page.evaluate('replay3d.render(17)')
            assert all(page.evaluate('replay3d.state.visibleCars'))
            assert page.evaluate('replay3d.state.carOpacity')[:2] == [1, 1]
            shots = page.evaluate("replay3d.state.broadcastShots")
            assert {"drone", "front", "trackside", "cockpit", "chase", "finish"} <= {
                shot["kind"] for shot in shots
            }
            assert all(b["start"] - a["start"] >= 5
                       for a, b in zip(shots, shots[1:]) if b["kind"] != "finish")
            assert {s["driver"] for s in shots} == {0, 1, 2}
            assert shots[-1]["driver"] == 2
            for shot in shots:
                page.evaluate("t => replay3d.render(t)", shot["start"] + .1)
                state = page.evaluate("replay3d.state")
                assert state["broadcastShot"] == shot
                assert all(math.isfinite(v) for v in state["cameraPosition"])
            page.evaluate("replay3d.render(12)")
            assert page.locator("#drivers .lap").all_text_contents() == ["12.000"] * 3
            before = page.evaluate("replay3d.state")
            page.evaluate("replay3d.render(60); replay3d.render(12)")
            after = page.evaluate("replay3d.state")
            assert before == after, {key: [before[key], after[key]] for key in before if before[key] != after[key]}
            assert page.locator('#cinematic').get_attribute('aria-pressed') == 'true'
            page.locator('#cinematic').click()
            assert page.locator('#cinematic').get_attribute('aria-pressed') == 'false'
            assert before['positions'] == page.evaluate('replay3d.state.positions')
            page.locator('#cinematic').click()
            page.locator('[data-driver="2"]').click()
            assert page.evaluate('replay3d.state.selected') == 2
            assert page.evaluate("replay3d.state.mode") == "chase"
            page.locator('[data-camera="f1"]').click()
            page.evaluate("replay3d.render(0)")
            assert all(abs(pos[0]) < 1e-8 for pos in page.evaluate("replay3d.state.positions"))
            assert page.locator("#drivers .lap").all_text_contents() == ["0.000"] * 3
            laps = page.evaluate("replay3d.state.laps")
            for i, lap in enumerate(laps):
                page.evaluate("t => replay3d.render(t)", lap - .001)
                assert page.evaluate("replay3d.state.positions")[i][0] < 0
                page.evaluate("t => replay3d.render(t)", lap)
                assert abs(page.evaluate("replay3d.state.positions")[i][0]) < 1e-8
                assert page.locator("#drivers .lap").all_text_contents() == [f"{min(lap, end):.3f}" for end in laps]
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
            third = synthetic['comparisons']['champions']['runs'][2]
            third['lap'] = 20
            third['trace'] = [[t/4, 40*t/4-200, 0, 0, 40, 0, 1, 0, 0, 40*t/4-200] for t in range(125)]
            page.route("**/data.json", lambda route: route.fulfill(json=synthetic))
            page.reload()
            page.wait_for_function("window.replay3d", timeout=60000)
            passes = page.evaluate('replay3d.state.broadcastShots.filter(s => s.reason === "Lead change")')
            assert len(passes) == 1 and passes[0]["driver"] == 0
            assert passes[0]["kind"] == "cockpit" and passes[0]["start"] > 10
            page.evaluate('replay3d.render(10)')
            assert all(page.evaluate('replay3d.state.visibleCars'))
            assert page.evaluate('replay3d.state.carOpacity') == [.6, .6, 1]
            assert page.evaluate('replay3d.state.broadcastShots.at(-1).driver') == 2
            # Close side-by-side cars should both remain visible.
            for sample in synthetic['comparisons']['champions']['runs'][1]['trace']:
                sample[2] = 3
            page.reload()
            page.wait_for_function('window.replay3d', timeout=60000)
            page.evaluate('replay3d.render(10)')
            assert all(page.evaluate('replay3d.state.visibleCars'))
            # An overlap involving only the third car must not fade the second.
            for a, b, c in zip(synthetic['comparisons']['champions']['runs'][0]['trace'], synthetic['comparisons']['champions']['runs'][1]['trace'], third['trace']):
                b[2] = 10
                c[1] = a[1] + .1
                c[9] = a[9] + .1
            page.reload()
            page.wait_for_function('window.replay3d', timeout=60000)
            page.evaluate('replay3d.render(10)')
            assert page.evaluate('replay3d.state.carOpacity') == [.6, 1, .6]
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print("Standalone replay checks passed.")


if __name__ == "__main__":
    main()
