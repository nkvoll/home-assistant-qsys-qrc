# README screenshots

Run from the repository root inside the devcontainer:

```sh
mise run screenshots
```

The task installs the Python dependencies declared in `requirements.txt` and
`requirements.dev.txt`, installs the pinned Playwright Chromium browser, then
runs the capture script using `$VENV_PATH/bin/python`. To only install or repair
the screenshot dependencies, run `mise run screenshots:setup`. To only download
the browser after installing Python dependencies, run `mise run screenshots:browser`.

The devcontainer's `scripts/setup` also invokes the browser installation task.
`Dockerfile.dev` includes the browser's system libraries and
fonts. No desktop, display server, Node installation, or physical Q-SYS Core is
needed. The pinned installer uses its Ubuntu 24.04 browser build on this
container's newer Ubuntu release; both setup and capture select that build.

The script starts a disposable Home Assistant instance on loopback port 18123
and a minimal read-only QRC simulator on loopback port 11710. Both ports must be
free. It uses a temporary configuration directory, links the current integration,
creates a demo administrator, and drives actual Home Assistant options dialogs.
It never uses your normal `config/` directory or connects to real hardware.
The processes and temporary configuration are cleaned up after capture, including
on failure. On failure the Home Assistant log is printed before cleanup.

Screenshots are written to `examples/screenshots/` with a fixed viewport, light
theme, English locale, and reduced motion. The Home Assistant/frontend version
also affects appearance; updating HA may require adjusting selectors and reviewing
the generated images. The devcontainer runs `scripts/setup` after rebuilding;
the screenshot task also installs its dependencies when invoked directly.

The simulator implements only the discovery and subscription methods this demo
needs. Unsupported methods return a JSON-RPC error; it is not a general purpose
Core emulator.
