"""Capture real HA dialogs using an isolated instance and deterministic QRC data."""

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
import sys
import tempfile

import aiohttp
from playwright.async_api import async_playwright

os.environ.setdefault("PLAYWRIGHT_HOST_PLATFORM_OVERRIDE", "ubuntu24.04-x64")

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "examples/screenshots"
BASE = "http://127.0.0.1:18123"
COMPONENTS = [
    {"Name": "Room Mixer", "Type": "mixer"},
    {"Name": "Room Gain", "Type": "gain"},
    {"Name": "Music Player", "Type": "audio_file_player"},
]
CONTROLS = [
    {
        "Name": "gain",
        "Type": "Float",
        "Direction": "Read/Write",
        "Value": -20.0,
        "String": "-20 dB",
        "Position": 0.6,
        "ValueMin": -80,
        "ValueMax": 0,
        "Step": 1,
        "Units": "dB",
    },
    {
        "Name": "mute",
        "Type": "Boolean",
        "Direction": "Read/Write",
        "Value": False,
        "String": "Unmuted",
        "Position": 0,
    },
]


async def qrc_client(reader, writer):
    """Implement only the read-only QRC calls used by the demo."""
    try:
        while True:
            request = json.loads((await reader.readuntil(b"\0"))[:-1])
            method, params = request["method"], request.get("params", {})
            if method == "StatusGet":
                result = {
                    "DesignName": "Demo Conference Room",
                    "Platform": "Core Nano",
                    "State": "Active",
                    "Status": {"Code": 0, "String": "OK"},
                }
            elif method == "Component.GetComponents":
                result = COMPONENTS
            elif method == "Component.GetControls":
                result = {"Name": params["Name"], "Controls": CONTROLS}
            elif method == "Component.Get":
                names = {item["Name"] for item in params["Controls"]}
                result = {
                    "Name": params["Name"],
                    "Controls": [c for c in CONTROLS if c["Name"] in names],
                }
            elif method == "Control.Get":
                result = [{**CONTROLS[1], "Name": name} for name in params]
            elif method == "ChangeGroup.Poll":
                result = {"Id": params["Id"], "Changes": []}
            elif method in {
                "Logon",
                "NoOp",
                "ChangeGroup.AddComponentControl",
                "ChangeGroup.AddControl",
            }:
                result = True
            else:
                writer.write(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": request["id"],
                            "error": {
                                "code": -32601,
                                "message": "Unsupported demo method",
                            },
                        }
                    ).encode()
                    + b"\0"
                )
                await writer.drain()
                continue
            writer.write(
                json.dumps(
                    {"jsonrpc": "2.0", "id": request["id"], "result": result}
                ).encode()
                + b"\0"
            )
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        writer.close()
        with contextlib.suppress(ConnectionError):
            await writer.wait_closed()


async def capture(config):
    async with aiohttp.ClientSession() as session:

        async def api(path, data=None, token=None):
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            async with session.request(
                "POST" if data is not None else "GET",
                BASE + path,
                json=data,
                headers=headers,
            ) as response:
                body = await response.json()
                if response.status >= 400:
                    raise RuntimeError(f"{path}: {response.status}: {body}")
                return body

        for _ in range(120):
            try:
                await api("/api/onboarding")
                break
            except (aiohttp.ClientError, OSError):
                await asyncio.sleep(1)
        else:
            raise RuntimeError(
                f"Home Assistant did not start; see {config}/home-assistant.log"
            )
        user = await api(
            "/api/onboarding/users",
            {
                "client_id": BASE + "/",
                "name": "Documentation Demo",
                "username": "demo",
                "password": "demo-screenshots-only",
                "language": "en",
            },
        )
        async with session.post(
            BASE + "/auth/token",
            data={
                "grant_type": "authorization_code",
                "code": user["auth_code"],
                "client_id": BASE + "/",
            },
        ) as response:
            auth = await response.json()
        token = auth["access_token"]
        await api("/api/onboarding/core_config", {}, token)
        await api("/api/onboarding/analytics", {}, token)
        await api(
            "/api/onboarding/integration",
            {"client_id": BASE + "/", "redirect_uri": BASE + "/"},
            token,
        )
        flow = await api(
            "/api/config/config_entries/flow",
            {"handler": "qsys_qrc", "show_advanced_options": False},
            token,
        )
        flow = await api(
            f"/api/config/config_entries/flow/{flow['flow_id']}",
            {
                "core_name": "DemoCore",
                "host": "127.0.0.1",
                "port": 11710,
                "username": "demo",
                "password": "1234",
            },
            token,
        )
        await api(
            f"/api/config/config_entries/flow/{flow['flow_id']}",
            {"next_step_id": "finish"},
            token,
        )
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            try:
                page = await browser.new_page(
                    viewport={"width": 1280, "height": 1100},
                    device_scale_factor=1,
                    locale="en-US",
                    color_scheme="light",
                    reduced_motion="reduce",
                )
                browser_auth = {
                    **auth,
                    "hassUrl": BASE,
                    "clientId": BASE + "/",
                    "expires": 4102444800000,
                }
                await page.add_init_script(
                    "localStorage.setItem('hassTokens', "
                    + json.dumps(json.dumps(browser_auth))
                    + ");"
                )
                await page.goto(BASE + "/config/integrations/integration/qsys_qrc")
                await page.wait_for_timeout(3000)
                if await page.get_by_role("button", name="Confirm", exact=True).count():
                    await page.get_by_role("button", name="Confirm", exact=True).click()
                await page.get_by_role("button", name="Configure", exact=True).click()
                await page.wait_for_timeout(500)

                async def shot(name, title):
                    await page.get_by_text(title, exact=True).wait_for()
                    await page.wait_for_timeout(350)
                    dialog = page.get_by_role("dialog")
                    box = await dialog.bounding_box()
                    await page.screenshot(
                        path=str(OUTPUT / f"{name}.png"),
                        clip={
                            "x": box["x"] - 16,
                            "y": box["y"] - 16,
                            "width": box["width"] + 32,
                            "height": box["height"] + 32,
                        },
                    )
                    LOGGER.info("Captured %s", name)

                async def submit():
                    await page.get_by_role("button", name="Submit", exact=True).click()

                async def choose(label, option):
                    await page.locator("ha-selector-select").filter(
                        has_text=label
                    ).click()
                    await page.get_by_text(option, exact=True).last.click()

                async def reopen():
                    await page.get_by_role("button", name="Close", exact=True).click()
                    await page.get_by_role(
                        "button", name="Configure", exact=True
                    ).click()
                    await page.get_by_text("Manage entities", exact=True).wait_for()

                await shot("manage-entities", "Manage entities")
                await page.get_by_text("Add entity", exact=True).click()
                await page.get_by_text("Named component", exact=True).click()
                await page.get_by_text("Choose component", exact=True).wait_for()
                await choose("Component", "Room Mixer (mixer)")
                await shot("choose-component", "Choose component")
                await submit()
                await choose("Control", "gain · Float · Read/Write")
                await shot("choose-control", "Choose control")
                await submit()
                await choose("Entity type", "number")
                await submit()
                await page.get_by_role("textbox", name="Name", exact=True).fill(
                    "Room volume"
                )
                await shot("entity-settings", "Entity settings")
                await submit()
                await shot("review-entity", "Review entity")
                await submit()
                await page.get_by_text("Manage entities", exact=True).wait_for()
                await page.get_by_text(
                    "Export portable configuration", exact=True
                ).click()
                await shot("export-portable", "Export portable configuration")
                document = await page.locator("textarea").input_value()
                await reopen()
                await page.get_by_text(
                    "Import from Home Assistant YAML", exact=True
                ).click()
                await page.get_by_text(
                    "Select all Home Assistant YAML mappings", exact=True
                ).click()
                await submit()
                await shot("yaml-migration-review", "Review ownership transfer")
                await page.get_by_text(
                    "Transfer selected mappings to UI ownership", exact=True
                ).click()
                await submit()
                await shot("yaml-cleanup", "YAML cleanup")
                await reopen()
                await page.get_by_text(
                    "Import portable configuration", exact=True
                ).click()
                # Demonstrate importing a new identity from another Core.
                document = document.replace(
                    "core_name: DemoCore", "core_name: SourceCore"
                )
                document = document.replace(
                    "component: Room Mixer", "component: Room Gain"
                )
                document = document.replace(
                    "name: Room volume", "name: Imported room volume"
                )
                await page.locator("textarea").fill(document)
                await shot("import-portable", "Import portable configuration")
                await submit()
                await shot("portable-import-review", "Review portable import")
            except Exception:
                LOGGER.error(
                    "Browser state:\n%s", await page.locator("body").aria_snapshot()
                )
                raise
            finally:
                await browser.close()


async def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    server = await asyncio.start_server(qrc_client, "127.0.0.1", 11710)
    with tempfile.TemporaryDirectory(prefix="qsys-readme-") as directory:
        config = Path(directory)
        (config / "custom_components").symlink_to(
            ROOT / "custom_components", target_is_directory=True
        )
        (config / "configuration.yaml").write_text("""
homeassistant:
  name: Documentation Demo
  latitude: 0
  longitude: 0
  elevation: 0
  unit_system: metric
  time_zone: UTC
http:
  server_host: 127.0.0.1
  server_port: 18123
frontend:
config:
qsys_qrc:
  cores:
    DemoCore:
      platforms:
        binary_sensor:
          - component: Room Mixer
            control: mute
            name: Room muted
""")
        with (config / "process.log").open("w") as log:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "homeassistant",
                "--config",
                str(config),
                stdout=log,
                stderr=log,
                env={**os.environ, "PYTHONASYNCIODEBUG": "0"},
            )
            try:
                await capture(config)
            except Exception:
                LOGGER.error("Home Assistant log (%s):", log.name)
                LOGGER.error("%s", (config / "process.log").read_text()[-5000:])
                raise
            finally:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 20)
                except TimeoutError:
                    process.kill()
                    await process.wait()
                server.close()
                await server.wait_closed()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(main())
