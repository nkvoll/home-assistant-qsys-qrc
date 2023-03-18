# Home Assistant Q-Sys QRC

Note: This is a work in progress.

A custom component that integrates Q-Sys Cores with Home Assistant via [QRC](https://q-syshelp.qsc.com/Index.htm#External_Control_APIs/QRC/QRC_Overview.htm). This is useful to expose elements such as gain controls, mute buttons and different media players to HA.

### Installing

Add the custom component via your `custom_components` folder or via HACS (untested).

### Configuring

First, set up the integration through the UI to configure the core name and credentials.

To expose component controls to HA, configure them via the configuration file.

See [the example configuration](examples/configuration.yaml) for an example of what can be configured.

### TODO

- Testing.
- Verify url receiver and audio player works in practice as HA media players.
- Customizable polling rate.
- Add to HACS proper?
- Anything else?