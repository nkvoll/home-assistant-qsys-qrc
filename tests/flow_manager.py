"""Home Assistant flow-manager harness for registered-step validation."""

from homeassistant.data_entry_flow import FlowManager


class TestFlowManager(FlowManager):
    """Exercise the real step dispatcher with an already supplied flow."""

    __test__ = False

    async def async_create_flow(self, handler, *, context, data):
        raise NotImplementedError

    async def async_finish_flow(self, flow, result):
        return result
