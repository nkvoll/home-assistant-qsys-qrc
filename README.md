# Home Assistant Q-Sys QRC

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE.md)
[![hacs][hacsbadge]][hacs]
[![Community Forum][forum-shield]][forum]

Note: This is a work in progress.

A custom component that integrates Q-Sys Cores with Home Assistant via [QRC](https://q-syshelp.qsc.com/Index.htm#External_Control_APIs/QRC/QRC_Overview.htm). This is useful to expose elements such as gain controls, mute buttons and different media players to HA.

### Installing

Add the custom component via your `custom_components` folder or via HACS (untested).

#### Manual installation

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
1. If you do not have a `custom_components` directory (folder) there, you need to create it.
1. In the `custom_components` directory (folder) create a new folder called `qsys_qrc`.
1. Download _all_ the files from the `custom_components/qsys_qrc/` directory (folder) in this repository.
1. Place the files you downloaded in the new directory (folder) you created.
1. Restart Home Assistant
1. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "Q-Sys QRC Integration"

### Configuring

First, set up the integration through the UI to configure the core name and credentials.

To expose component controls to HA, configure them via the configuration file.

See [the example configuration](examples/configuration.yaml) for an example of what can be configured.

### TODO


- Add tests, see [`pytest-homeassistant-custom-component`](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component) to get started.
- Add brand images (logo/icon) to https://github.com/home-assistant/brands.
- Create a releasee.
- Share your integration on the [Home Assistant Forum](https://community.home-assistant.io/).
- Submit your integration to the [HACS](https://hacs.xyz/docs/publish/start).
- Verify audio player works in practice as HA media players.
- Anything else?

### Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

***

[commits-shield]: https://img.shields.io/github/commit-activity/y/nkvoll/home-assistant-qsys-qrc.svg?style=for-the-badge
[commits]: https://github.com/nkvoll/home-assistant-qsys-qrc/commits/main
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=for-the-badge
[forum]: https://community.home-assistant.io/
[license-shield]: https://img.shields.io/github/license/nkvoll/home-assistant-qsys-qrc.svg?style=for-the-badge&bust=123
[releases-shield]: https://img.shields.io/github/release/nkvoll/home-assistant-qsys-qrc.svg?style=for-the-badge
[releases]: https://github.com/nkvoll/home-assistant-qsys-qrc/releases