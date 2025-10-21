import asyncio
import pytest

from custom_components.qsys_qrc.qsys import qrc
from custom_components.qsys_qrc.changegroup import ChangeGroupPoller, PollerState

pytestmark = pytest.mark.asyncio


class DummyChangeGroup:
    def __init__(self):
        self.add_component_control_calls = []
        self.poll_calls = 0
        self._poll_side_effects = []

    async def add_component_control(self, payload):
        self.add_component_control_calls.append(payload)

    async def poll(self):
        self.poll_calls += 1
        if self._poll_side_effects:
            effect = self._poll_side_effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            return effect
        return {"result": {"Changes": []}}


class FakeCore:
    def __init__(self):
        self._connected_event = asyncio.Event()
        self._connected_event.set()
        self._cg = DummyChangeGroup()

    async def wait_until_connected(self, timeout=None):
        if timeout:
            await asyncio.wait_for(self._connected_event.wait(), timeout)
        else:
            await self._connected_event.wait()

    def change_group(self, name):  # noqa: ARG002 - name unused for tests
        return self._cg


@pytest.fixture
def core():
    return FakeCore()


async def test_start_and_stop(core):
    poller = ChangeGroupPoller(core, "testcg", 0.01, 0.1)
    task = poller.start()
    await poller.wait_until_running(timeout=1)
    assert poller._state == PollerState.RUNNING
    await poller.stop()
    assert poller._state in (PollerState.IDLE, PollerState.STOPPING)
    assert task.done()


async def test_add_control_before_start(core):
    poller = ChangeGroupPoller(core, "testcg", 0.01, 0.1)
    listener_called = asyncio.Event()

    async def listener(p, change):  # noqa: ARG001
        listener_called.set()

    await poller.subscribe_component_control_changes(listener, "Comp", "Ctrl")
    poller.start()
    await poller.wait_until_running(timeout=1)
    # The dummy change group should have received add_component_control
    cg = poller.cg
    assert cg is not None
    assert cg.add_component_control_calls == [
        {"Name": "Comp", "Controls": [{"Name": "Ctrl"}]}
    ]
    await poller.stop()


async def test_dynamic_add_control_after_creation(core):
    poller = ChangeGroupPoller(core, "testcg", 0.01, 0.1)
    poller.start()
    await poller.wait_until_running(timeout=1)
    cg = poller.cg
    assert cg is not None
    await poller.subscribe_component_control_changes(lambda *_: None, "Comp", "Ctrl")
    # dynamic addition should attempt to add immediately
    assert cg.add_component_control_calls[-1] == {"Name": "Comp", "Controls": [{"Name": "Ctrl"}]}
    await poller.stop()


async def test_polling_changes_dispatch(core):
    poller = ChangeGroupPoller(core, "testcg", 0.01, 0.1)
    poller.start()
    await poller.wait_until_running(timeout=1)

    received = []

    async def listener(p, change):  # noqa: ARG001
        received.append(change)

    await poller.subscribe_component_control_changes(listener, "Comp", "Ctrl")
    # inject change into next poll
    poller.cg._poll_side_effects.append(
        {"result": {"Changes": [{"Component": "Comp", "Name": "Ctrl", "Value": 5}]}}
    )
    # allow loop to run
    await asyncio.sleep(0.05)
    assert received == [{"Component": "Comp", "Name": "Ctrl", "Value": 5}]
    await poller.stop()


async def test_timeout_handling(core):
    poller = ChangeGroupPoller(core, "testcg", 0.01, 0.01)
    poller.start()
    await poller.wait_until_running(timeout=1)

    poller.cg._poll_side_effects.append(asyncio.TimeoutError())
    # let loop process timeout without crashing
    await asyncio.sleep(0.05)
    assert poller._state == PollerState.RUNNING  # still running after timeout
    await poller.stop()


async def test_qrc_error_recreate(core):
    poller = ChangeGroupPoller(core, "testcg", 0.01, 0.05)
    poller.start()
    await poller.wait_until_running(timeout=1)
    poller.cg._poll_side_effects.append(qrc.QRCError("err"))
    await asyncio.sleep(0.05)
    # After QRCError we expect recreate attempt on next iteration
    assert poller._state in (PollerState.RUNNING, PollerState.STARTING)
    await poller.stop()


async def test_generic_exception(core):
    poller = ChangeGroupPoller(core, "testcg", 0.01, 0.05)
    poller.start()
    await poller.wait_until_running(timeout=1)
    poller.cg._poll_side_effects.append(ValueError("boom"))
    await asyncio.sleep(0.05)
    # Should continue running despite error
    assert poller._state in (PollerState.RUNNING, PollerState.STARTING)
    await poller.stop()


async def test_run_while_core_running_wrapper(core):
    poller = ChangeGroupPoller(core, "testcg", 0.01, 0.05)
    # Run briefly then stop (do not rely on timeout cancellation which is brittle)
    task = asyncio.create_task(poller.run_while_core_running())
    await asyncio.sleep(0.05)
    await poller.stop()
    if not task.done():
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_stop_idempotent(core):
    poller = ChangeGroupPoller(core, "testcg", 0.01, 0.05)
    poller.start()
    await poller.wait_until_running(timeout=1)
    await poller.stop()
    await poller.stop()  # second stop should not fail
    assert poller._loop_task is None

