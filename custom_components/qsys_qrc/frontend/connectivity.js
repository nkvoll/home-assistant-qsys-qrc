/* HA does not expose a registration API for Connectivity navigation entries.
 * Extend only this page's navigation; leave the bundled HA assets untouched.
 * If HA changes its page structure, the panel remains available at /qsys-qrc.
 */
customElements.whenDefined('ha-config-connectivity').then(() => {
  const prototype = customElements.get('ha-config-connectivity').prototype;
  if (prototype.qsysConnectivityInstalled) return;
  prototype.qsysConnectivityInstalled = true;
  const updated = prototype.updated;
  prototype.updated = function(changed) {
    updated?.call(this, changed);
    const navigation = this.shadowRoot?.querySelector('ha-config-navigation');
    const enabled = this.hass?.user?.is_admin && this.hass?.panels?.['qsys-qrc'];
    if (!navigation || !Array.isArray(navigation.pages)) return;
    const present = navigation.pages.some(page => page.path === '/qsys-qrc');
    if (enabled && !present) {
      navigation.pages = [...navigation.pages, {
        path: '/qsys-qrc', name: 'Q-SYS',
        description: 'Manage Cores, controls, entities, and QRC traffic',
        adminOnly: true,
        iconPath: 'M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M7,10A2,2 0 0,1 9,12A2,2 0 0,1 7,14A2,2 0 0,1 5,12A2,2 0 0,1 7,10M12,10A2,2 0 0,1 14,12A2,2 0 0,1 12,14A2,2 0 0,1 10,12A2,2 0 0,1 12,10M17,10A2,2 0 0,1 19,12A2,2 0 0,1 17,14A2,2 0 0,1 15,12A2,2 0 0,1 17,10',
      }];
    } else if (!enabled && present) {
      navigation.pages = navigation.pages.filter(page => page.path !== '/qsys-qrc');
    }
  };
});
