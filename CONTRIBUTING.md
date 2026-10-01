# Contribution guidelines

Contributing to this project should be as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features

## Github is used for everything

Github is used to host code, to track issues and feature requests, as well as accept pull requests.

Pull requests are the best way to propose changes to the codebase.

1. Fork the repo and create your branch from `main`.
2. If you've changed something, update the documentation.
3. Make sure your code lints (using `scripts/lint`).
4. Test you contribution.
5. Issue that pull request!

## Any contributions you make will be under the MIT Software License

In short, when you submit code changes, your submissions are understood to be under the same [MIT License](http://choosealicense.com/licenses/mit/) that covers the project. Feel free to contact the maintainers if that's a concern.

## Report bugs using Github's [issues](../../issues)

GitHub issues are used to track public bugs.
Report a bug by [opening a new issue](../../issues/new/choose); it's that easy!

## Write bug reports with detail, background, and sample code

**Great Bug Reports** tend to have:

- A quick summary and/or background
- Steps to reproduce
  - Be specific!
  - Give sample code if you can.
- What you expected would happen
- What actually happens
- Notes (possibly including why you think this might be happening, or stuff you tried that didn't work)

People *love* thorough bug reports. I'm not even kidding.

## Use a Consistent Coding Style

Use [black](https://github.com/ambv/black) to make sure the code follows the style.

## Test your code modification

### Development tasks

Use `mise tasks` to list the repository's development commands. Inside the
devcontainer, the virtualenv is configured by `VENV_PATH` in `mise.toml`.
`mise run setup` initializes it; `mise run deps` refreshes all declared Python
dependencies in an existing environment.

| Command | Purpose |
| --- | --- |
| `mise run dev` | Start development Home Assistant on port 8123; stop with Ctrl-C. |
| `mise run config:check` | Validate your local Home Assistant configuration. |
| `mise run lint` | Check Python code with Ruff. |
| `mise run lint:fix` | Apply Ruff's automatic fixes. |
| `mise run format` | Format Python code with Black. |
| `mise run format:check` | Check formatting without changing files. |
| `mise run test` | Run the full pytest suite. |
| `mise run test:qrc` | Run QRC client and change-group tests. |
| `mise run check` | Run lint, formatting checks, and tests together. |
| `mise run screenshots` | Install capture dependencies and regenerate README screenshots. |
| `mise run screenshots:setup` | Install screenshot Python dependencies and Chromium. |
| `mise run screenshots:browser` | Download Chromium after Python dependencies are installed. |
| `mise run dependencies:update` | Update requirements from PyPI and the HACS minimum version. |
| `mise run release:prepare v0.9.2 v0.9.3` | Check release prerequisites and print release commands. |

Tasks accept additional command arguments. For example, use
`mise run test tests/test_options_flow.py -q` for a targeted test run or
`mise run lint scripts/screenshots/capture.py` to check a specific file.
`check` reports failures without applying fixes. Dependency updates change files
and can update the pinned browser version; review the diff and regenerate
screenshots after upgrading Playwright. The release preparation task only prints
commands and requires a clean working tree on `main`.

See [the screenshot instructions](scripts/screenshots/README.md) for the demo
environment and generated images.

This custom component comes with development environment in a container, easy to launch
if you use Visual Studio Code. With this container you will have a stand alone
Home Assistant instance running and already configured with the included
[`configuration.yaml`](./config/configuration.yaml)
file.

## License

By contributing, you agree that your contributions will be licensed under its Apache License, Version 2.0. See [LICENSE](LICENSE.md).
