"""Exercise and capture the Q-SYS panel against an isolated HA and QRC simulator."""

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
import sys
import tempfile

import aiohttp
from playwright.async_api import async_playwright, expect

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
    except asyncio.IncompleteReadError, ConnectionError:
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
            except aiohttp.ClientError, OSError:
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
                errors = []
                page.on("pageerror", lambda err: errors.append(str(err)))
                await page.goto(BASE + "/config/connectivity")
                await page.get_by_role("button", name="Confirm", exact=True).click()
                await page.get_by_role("link", name="Q-SYS", exact=False).click()
                panel = page.locator("qsys-qrc-panel")

                async def screenshot(filename, *, full_page=True):
                    await page.mouse.move(5, 5)
                    await panel.evaluate(
                        "element => {element.scrollTop=0;element.shadowRoot.activeElement?.blur();}"
                    )
                    await page.evaluate("""() => {
                        const visit=root=>{for(const element of root.querySelectorAll('*')){
                            if(element.localName==='ha-toast'||element.matches('qsys-qrc-panel .message')||element.classList.contains('message')&&root.host?.localName==='qsys-qrc-panel'){
                                element.dataset.screenshotStyle=element.getAttribute('style')||'';
                                element.style.setProperty('display','none','important');
                            }
                            if(element.shadowRoot)visit(element.shadowRoot);
                        }};visit(document);
                    }""")
                    try:
                        await page.screenshot(
                            path=str(OUTPUT / filename), full_page=full_page
                        )
                    finally:
                        await page.evaluate("""() => {
                            const visit=root=>{for(const element of root.querySelectorAll('*')){
                                if(element.hasAttribute('data-screenshot-style')){element.setAttribute('style',element.dataset.screenshotStyle);delete element.dataset.screenshotStyle;}
                                if(element.shadowRoot)visit(element.shadowRoot);
                            }};visit(document);
                        }""")

                await panel.get_by_role("heading", name="Cores", exact=True).wait_for()
                await panel.evaluate(
                    "element => element.dispatchEvent(new CustomEvent('show-dialog',{detail:{dialogTag:'qsys-discard-dialog',dialogImport:()=>Promise.resolve(),addHistory:false,dialogParams:{confirm:()=>{},cancel:()=>{}}},bubbles:true,composed:true}))"
                )
                await page.get_by_role(
                    "button", name="Keep editing", exact=True
                ).click()
                await page.get_by_role("dialog").wait_for(state="hidden")
                await panel.get_by_role("button", name="Add entities", exact=False).wait_for()
                await panel.get_by_role("button", name="Manage entities", exact=False).wait_for()
                await screenshot("panel-dashboard.png")
                await panel.get_by_role(
                    "button", name="Components / Controls", exact=True
                ).click()
                await panel.get_by_role(
                    "heading", name="Or look up Named Controls", exact=True
                ).wait_for()
                await panel.get_by_role(
                    "button", name="About Components", exact=True
                ).hover()
                await panel.locator("#help-components").wait_for(state="visible")
                assert (
                    "Code Name" in await panel.locator("#help-components").inner_text()
                )
                assert (
                    "External" in await panel.locator("#help-components").inner_text()
                )
                await panel.get_by_role(
                    "button", name="About Named Controls", exact=True
                ).focus()
                await panel.locator("#help-named-controls").wait_for(state="visible")
                assert (
                    "no documented command"
                    in await panel.locator("#help-named-controls").inner_text()
                )
                assert await panel.locator("section.card #named").count() == 1
                await expect(panel.get_by_role("button", name="Review creation (0)", exact=True)).to_be_disabled()
                await panel.get_by_role("button", name="Look up control", exact=True).wait_for()
                assert await panel.locator(".action-bar").evaluate("el => getComputedStyle(el).position") == "sticky"
                await panel.get_by_role(
                    "textbox", name="Filter components", exact=True
                ).fill("Room Gain")
                await panel.get_by_role(
                    "checkbox", name="Single column", exact=True
                ).check()
                assert (
                    await panel.locator(".component-picker.single-column").count() == 1
                )
                await panel.get_by_role("button", name="Select all", exact=True).click()
                await panel.locator('[data-group="Room Gain"]').wait_for()
                assert await panel.locator("[data-group]").count() == 1
                await panel.get_by_role("button", name="Clear", exact=True).click()
                await panel.locator("[data-group]").first.wait_for(state="hidden")
                await panel.get_by_role(
                    "textbox", name="Filter components", exact=True
                ).fill("")
                await panel.get_by_role(
                    "checkbox", name="Single column", exact=True
                ).uncheck()
                await panel.get_by_role("button", name="Select all", exact=True).click()
                await panel.locator("[data-group]").nth(2).wait_for()
                assert await panel.locator("[data-group]").count() == 3
                await panel.get_by_role("button", name="Clear", exact=True).click()
                await panel.locator("[data-group]").first.wait_for(state="hidden")
                assert await panel.locator("[data-group]").count() == 0
                assert await panel.locator("[data-component-choice]").evaluate_all(
                    "(elements) => elements.map(el => el.dataset.componentChoice)"
                ) == ["Music Player", "Room Gain", "Room Mixer"]
                await panel.locator('[data-component="Room Mixer"]').check()
                await panel.locator("[data-control-group]").nth(1).wait_for()
                assert await panel.locator("[data-control-group]").evaluate_all(
                    "(rows) => rows.map(row => row.cells[1].textContent)"
                ) == ["gain", "mute"]
                control_widths = await panel.locator("thead th").evaluate_all(
                    "(cells) => cells.map(cell => cell.getBoundingClientRect().width)"
                )
                await panel.get_by_role("button", name="Control", exact=True).click()
                assert (
                    await panel.locator("thead th").evaluate_all(
                        "(cells) => cells.map(cell => cell.getBoundingClientRect().width)"
                    )
                    == control_widths
                )
                assert (
                    await panel.locator('[data-field="name"] ha-icon').get_attribute(
                        "icon"
                    )
                    == "mdi:sort-descending"
                )
                assert await panel.locator("[data-control-group]").evaluate_all(
                    "(rows) => rows.map(row => row.cells[1].textContent)"
                ) == ["mute", "gain"]
                await panel.get_by_role("button", name="Control", exact=True).click()
                assert (
                    await panel.get_by_role(
                        "columnheader", name="Control", exact=True
                    ).get_attribute("aria-sort")
                    == "ascending"
                )

                await panel.locator('[data-platform="1"]').select_option(
                    "binary_sensor"
                )
                assert await panel.get_by_role(
                    "checkbox", name="Select Room Mixer / mute", exact=True
                ).is_disabled()
                assert await panel.locator(".mapped-row").count() == 1
                await panel.get_by_role(
                    "button", name="Already mapped: Room muted", exact=True
                ).click()
                await page.get_by_role("dialog").wait_for()
                await page.get_by_role("button", name="Close", exact=True).click()
                await page.get_by_role("dialog").wait_for(state="hidden")
                await panel.locator("#all").check()
                assert not await panel.get_by_role(
                    "checkbox", name="Select Room Mixer / mute", exact=True
                ).is_checked()
                await panel.locator("#all").uncheck()
                await panel.locator('[data-platform="1"]').select_option("switch")
                assert await panel.get_by_role(
                    "checkbox", name="Select Room Mixer / mute", exact=True
                ).is_enabled()
                await panel.get_by_role(
                    "checkbox", name="Use position for Room Mixer / gain", exact=True
                ).check()
                await panel.locator('[data-platform="0"]').select_option("sensor")
                assert (
                    await panel.get_by_role(
                        "checkbox",
                        name="Use position for Room Mixer / gain",
                        exact=True,
                    ).count()
                    == 0
                )
                await panel.locator('[data-platform="0"]').select_option("number")
                assert await panel.get_by_role(
                    "checkbox", name="Use position for Room Mixer / gain", exact=True
                ).is_checked()
                await panel.locator("#all").check()
                await panel.locator('[data-name="0"]').fill("Room Mixer level")
                await panel.locator('[data-component="Room Gain"]').check()
                assert await panel.get_by_role(
                    "checkbox", name="Select Room Mixer / gain", exact=True
                ).is_checked()
                assert await panel.get_by_role(
                    "checkbox", name="Select Room Mixer / mute", exact=True
                ).is_checked()
                assert await panel.get_by_role(
                    "checkbox", name="Use position for Room Mixer / gain", exact=True
                ).is_checked()
                assert (
                    await panel.get_by_role(
                        "textbox", name="Entity name for Room Mixer / gain", exact=True
                    ).input_value()
                    == "Room Mixer level"
                )
                await panel.get_by_role(
                    "checkbox", name="Select Room Gain / gain", exact=True
                ).check()
                await panel.get_by_role(
                    "textbox", name="Entity name for Room Gain / gain", exact=True
                ).fill("Room Gain level")
                assert await panel.locator('[data-group="Room Mixer"]').count() == 1
                assert await panel.locator('[data-group="Room Gain"]').count() == 1
                media_checkbox = panel.get_by_role(
                    "checkbox",
                    name="Select Room Gain / Component media player",
                    exact=True,
                )
                await media_checkbox.check()
                await panel.get_by_role(
                    "button", name="Review creation (4)", exact=True
                ).click()
                await panel.locator("#review-title").wait_for()
                assert (
                    "media_player" in await panel.locator("section.review").inner_text()
                )
                await panel.locator("#review-dialog").wait_for()
                await page.keyboard.press("Escape")
                await panel.locator("#review-dialog").wait_for(state="hidden")
                assert await panel.get_by_role(
                    "button", name="Review creation (4)", exact=True
                ).evaluate("button => button.matches(':focus')")
                assert await media_checkbox.is_checked()
                await media_checkbox.uncheck()
                await panel.get_by_role("button", name="Entities", exact=True).click()
                await page.get_by_role(
                    "button", name="Keep editing", exact=True
                ).click()
                await page.get_by_role("dialog").wait_for(state="hidden")
                assert (
                    await panel.get_by_role(
                        "button", name="Review creation (3)", exact=True
                    ).count()
                    == 1
                )
                await panel.locator("#back").click()
                await page.get_by_role(
                    "button", name="Keep editing", exact=True
                ).click()
                await page.get_by_role("dialog").wait_for(state="hidden")
                assert page.url == BASE + "/qsys-qrc/cores/DemoCore/browser"
                await page.evaluate("history.back()")
                await page.get_by_role(
                    "button", name="Keep editing", exact=True
                ).click()
                await page.get_by_role("dialog").wait_for(state="hidden")
                assert page.url == BASE + "/qsys-qrc/cores/DemoCore/browser"
                await page.get_by_role("link", name="2 Settings 2", exact=True).click()
                await page.get_by_role(
                    "button", name="Keep editing", exact=True
                ).click()
                await page.get_by_role("dialog").wait_for(state="hidden")
                assert page.url == BASE + "/qsys-qrc/cores/DemoCore/browser"
                assert await panel.evaluate(
                    "element => {const event=new Event('beforeunload',{cancelable:true});window.dispatchEvent(event);return event.defaultPrevented;}"
                )
                await panel.evaluate(
                    "element => {element.scrollTop=0;element.shadowRoot.activeElement?.blur();}"
                )
                await screenshot("panel-components-controls.png")
                await panel.get_by_role(
                    "button", name="Review creation (3)", exact=True
                ).click()
                await panel.locator("#review-title").wait_for()
                await expect(panel.locator("#review-title")).to_have_text("Create 3 entities")
                await screenshot("panel-bulk-create.png", full_page=False)
                await panel.get_by_role("button", name="Create", exact=True).click()
                await panel.locator("#review-title").wait_for(
                    state="hidden"
                )
                assert await panel.locator(".error").count() == 0
                await panel.locator("#review-title").wait_for(
                    state="hidden"
                )
                assert await panel.locator(".error").count() == 0
                await page.wait_for_function("""() => {
                    const visit = root => {
                        const panel = root.querySelector('qsys-qrc-panel');
                        if (panel) return Object.values(panel._hass.states).some(state =>
                            state.entity_id.startsWith('number.'));
                        return [...root.querySelectorAll('*')].some(el => el.shadowRoot && visit(el.shadowRoot));
                    };
                    return visit(document);
                }""")
                await expect(panel.locator(".message")).to_contain_text("Created 3 entities.")
                await panel.get_by_role("button", name="View entities", exact=True).click()
                await expect(panel.get_by_role("button", name="Review bulk edit", exact=True)).to_be_disabled()
                await expect(panel.get_by_role("button", name="Review deletion", exact=True)).to_be_disabled()
                assert (
                    await panel.get_by_role(
                        "columnheader", name="Status", exact=True
                    ).count()
                    == 0
                )
                await panel.get_by_role(
                    "columnheader", name="Details", exact=True
                ).wait_for()
                await panel.get_by_role(
                    "textbox", name="Filter entities", exact=True
                ).fill("gain")
                assert await panel.locator("tbody tr:not([hidden])").count() == 2
                await panel.get_by_role(
                    "textbox", name="Filter entities", exact=True
                ).fill("")
                await (
                    panel.get_by_role("button", name="Room muted", exact=True)
                    .locator("ha-state-icon svg")
                    .wait_for(state="visible")
                )
                assert (
                    await panel.locator("[data-entity-icon]").count()
                    == await panel.locator("[data-entity-row]").count()
                )
                await panel.get_by_role("button", name="Room muted", exact=True).click()
                await page.get_by_role("dialog").wait_for()
                await page.get_by_role("button", name="Close", exact=True).click()
                await page.get_by_role("dialog").wait_for(state="hidden")
                await (
                    panel.locator('[data-entity-row="0"] details')
                    .locator("summary")
                    .click()
                )
                assert (
                    '"use_position": true'
                    in await panel.locator('[data-entity-row="0"] details').inner_text()
                )
                assert (
                    await panel.get_by_role(
                        "columnheader", name="Entity Name", exact=True
                    ).get_attribute("aria-sort")
                    == "ascending"
                )
                await panel.evaluate(
                    "element => {element.scrollTop=0;element.shadowRoot.activeElement?.blur();}"
                )
                await panel.locator('[data-select="0"]').check()
                await panel.locator('[data-select="2"]').check()
                await panel.locator("#edit-field").select_option("step")
                await panel.locator('[data-entity-row="0"] details summary').click()
                await screenshot("panel-entities.png")
                await panel.locator("#all").uncheck()
                await panel.locator("#edit-field").select_option("name")
                entity_names = await panel.locator("tbody tr").evaluate_all(
                    "(rows) => rows.map(row => row.cells[1].textContent.trim())"
                )
                assert entity_names == sorted(entity_names, key=str.casefold)
                await panel.locator('[data-select="0"]').check()
                await panel.get_by_role(
                    "button", name="Entity Name", exact=True
                ).click()
                assert await panel.locator("tbody tr").evaluate_all(
                    "(rows) => rows.map(row => row.cells[1].textContent.trim())"
                ) == list(reversed(entity_names))
                assert await panel.locator('[data-select="0"]').is_checked()
                await panel.get_by_role(
                    "button", name="Entity Name", exact=True
                ).click()
                entity_widths = await panel.locator("thead th").evaluate_all(
                    "(cells) => cells.map(cell => cell.getBoundingClientRect().width)"
                )
                await panel.get_by_role("button", name="Platform", exact=True).click()
                assert (
                    await panel.locator("thead th").evaluate_all(
                        "(cells) => cells.map(cell => cell.getBoundingClientRect().width)"
                    )
                    == entity_widths
                )
                assert (
                    await panel.get_by_role(
                        "columnheader", name="Platform", exact=True
                    ).get_attribute("aria-sort")
                    == "ascending"
                )
                entity_widths = await panel.locator("thead th").evaluate_all(
                    "(cells) => cells.map(cell => cell.getBoundingClientRect().width)"
                )
                await panel.get_by_role("button", name="Platform", exact=True).click()
                assert (
                    await panel.locator("thead th").evaluate_all(
                        "(cells) => cells.map(cell => cell.getBoundingClientRect().width)"
                    )
                    == entity_widths
                )
                assert (
                    await panel.get_by_role(
                        "columnheader", name="Platform", exact=True
                    ).get_attribute("aria-sort")
                    == "descending"
                )
                await panel.get_by_role(
                    "button", name="Entity Name", exact=True
                ).click()
                await panel.locator("#all").check()
                assert (
                    await panel.locator("#edit-value").get_attribute("type") == "text"
                )
                await panel.locator('[data-select="1"]').uncheck()
                await panel.locator("#edit-field").select_option("use_position")
                assert (
                    await panel.locator("#edit-value").get_attribute("type")
                    == "checkbox"
                )
                await panel.locator("#edit-value").check()
                await panel.locator("#edit-field").select_option("step")
                assert (
                    await panel.locator("#edit-value").get_attribute("type") == "number"
                )
                await panel.locator("#edit-field").select_option("mode")
                assert (
                    await panel.locator("#edit-value").evaluate("(el) => el.tagName")
                    == "SELECT"
                )
                await panel.locator("#edit-value").select_option("slider")
                await panel.locator("#edit-field").select_option("value_template")
                assert (
                    await panel.locator("#edit-value").evaluate("(el) => el.tagName")
                    == "TEXTAREA"
                )
                await panel.locator("#edit-field").select_option("name")
                await panel.locator('[data-select="1"]').check()
                await panel.locator("#edit-value").fill("Updated room control")
                await panel.get_by_role(
                    "button", name="Review bulk edit", exact=True
                ).click()
                await panel.locator("#review-title").wait_for()
                await panel.get_by_role("button", name="Save", exact=True).click()
                await panel.locator("#review-title").wait_for(
                    state="hidden"
                )
                assert await panel.locator(".error").count() == 0
                await panel.get_by_role(
                    "button", name="QRC Protocol Monitor", exact=True
                ).click()
                await panel.get_by_role(
                    "button", name="Start capture", exact=True
                ).click()
                await panel.get_by_role(
                    "cell", name="→ Sent", exact=True
                ).first.wait_for()
                await panel.locator("details").first.locator("summary").click()
                await panel.get_by_role(
                    "textbox", name="Filter protocol frames", exact=True
                ).focus()
                await panel.evaluate("""element => {
                    const root=element.shadowRoot;
                    window.qsysMonitorNodes={panel:element,header:root.querySelector('header'),
                        filter:root.querySelector('#monitor-search'),row:root.querySelector('#monitor-rows tr'),
                        details:root.querySelector('#monitor-rows details'),sequence:element.frames.at(-1).sequence};
                }""")
                await page.wait_for_function(
                    "window.qsysMonitorNodes.panel.frames.at(-1).sequence > window.qsysMonitorNodes.sequence"
                )
                assert await panel.evaluate("""element => {
                    const nodes=window.qsysMonitorNodes,root=element.shadowRoot;
                    return root.querySelector('header')===nodes.header && root.querySelector('#monitor-search')===nodes.filter &&
                        root.activeElement===nodes.filter && nodes.row.isConnected && nodes.details.open && !nodes.filter.disabled;
                }""")
                await panel.locator("#direction").select_option("sent")
                await panel.get_by_role(
                    "textbox", name="Filter protocol frames", exact=True
                ).fill("ChangeGroup")
                assert await panel.evaluate("""element => [...element.shadowRoot.querySelectorAll('#monitor-rows tr:not([hidden])')]
                    .every(row=>row.qsysDirection==='sent'&&row.qsysSearchText.includes('changegroup'))""")
                await panel.locator("#direction").select_option("")
                await panel.get_by_role(
                    "textbox", name="Filter protocol frames", exact=True
                ).fill("")

                await screenshot("panel-monitor.png")
                await panel.get_by_role("button", name="Dashboard", exact=True).click()
                await panel.get_by_role(
                    "button", name="Migrate from Home Assistant YAML", exact=False
                ).click()
                await panel.locator("#all").check()
                await panel.get_by_role(
                    "button", name="Review migration (1)", exact=True
                ).click()
                await panel.locator("#review-title").wait_for()
                await panel.get_by_role(
                    "button", name="Confirm and save", exact=True
                ).click()
                await panel.locator("#review-title").wait_for(
                    state="hidden"
                )
                assert await panel.locator(".error").count() == 0
                await panel.get_by_role("button", name="Dashboard", exact=True).click()
                await panel.get_by_role(
                    "button", name="Export YAML", exact=False
                ).click()
                displayed_document = await panel.locator(
                    "#export-document"
                ).inner_text()
                assert (
                    "version: 1" in displayed_document
                    and "mappings:" in displayed_document
                )
                await panel.evaluate(
                    "element => {element.scrollTop=0;element.shadowRoot.activeElement?.blur();}"
                )
                await screenshot("panel-yaml-export.png")
                await page.context.grant_permissions(
                    ["clipboard-read", "clipboard-write"]
                )
                await panel.get_by_role(
                    "button", name="Copy to clipboard", exact=True
                ).click()
                assert (
                    await page.evaluate("navigator.clipboard.readText()")
                    == displayed_document
                )
                async with page.expect_download() as download:
                    await panel.get_by_role(
                        "button", name="Download", exact=True
                    ).click()
                document = Path(await (await download.value).path()).read_text()
                assert document == displayed_document
                await panel.get_by_role("button", name="Dashboard", exact=True).click()
                await panel.get_by_role(
                    "button", name="Import YAML", exact=False
                ).click()
                await panel.locator("#file").set_input_files(
                    {
                        "name": "portable.yaml",
                        "mimeType": "application/yaml",
                        "buffer": document.encode(),
                    }
                )
                await expect(panel.locator("#document")).to_have_value(document)
                await panel.get_by_role(
                    "button", name="Review import", exact=True
                ).click()
                await panel.locator("#review-title").wait_for()
                await panel.get_by_role("button", name="Cancel", exact=True).click()
                await panel.get_by_role("button", name="Entities", exact=True).click()
                await page.get_by_role(
                    "button", name="Keep editing", exact=True
                ).click()
                await page.get_by_role("dialog").wait_for(state="hidden")
                assert await panel.locator("#document").input_value() == document
                await panel.get_by_role("button", name="Entities", exact=True).click()
                await page.get_by_role(
                    "button", name="Discard changes", exact=True
                ).click()

                await panel.locator("#all").check()
                await panel.get_by_role(
                    "button", name="Review deletion", exact=True
                ).click()
                await panel.get_by_text(
                    "Deleting this UI mapping reactivates", exact=False
                ).wait_for()
                await panel.get_by_role("button", name="Delete", exact=True).click()
                await panel.locator("#review-title").wait_for(
                    state="hidden"
                )
                assert await panel.locator(".error").count() == 0
                assert (
                    await panel.get_by_role(
                        "button", name="Diagnostics", exact=True
                    ).count()
                    == 0
                )
                await page.set_viewport_size({"width": 390, "height": 844})
                await panel.get_by_role("button", name="Dashboard", exact=True).click()
                await panel.get_by_role(
                    "heading", name="Import & migration", exact=True
                ).wait_for()
                await panel.locator("#back").click()
                await page.wait_for_url(BASE + "/config/connectivity")
                await page.get_by_role("link", name="Q-SYS", exact=False).wait_for()
                assert not errors, errors
                LOGGER.info(
                    "Full panel workflow passed against isolated Home Assistant and QRC simulator"
                )
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
recorder:
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
