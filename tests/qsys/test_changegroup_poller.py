import asyncio
import pytest

from custom_components.qsys_qrc.changegroup import ChangeGroupPoller, PollerState
from custom_components.qsys_qrc.qsys.qrc import QRCError


class FakeChangeGroup:
    def __init__(self):
        self.added = []
        self.poll_calls = 0
        self._changes = []  # list of change dicts
        self._poll_exception = None
        self._poll_delay = 0

    async def add_component_control(self, component):
        self.added.append(component)

    async def poll(self):
        self.poll_calls += 1
        if self._poll_delay:
            await asyncio.sleep(self._poll_delay)
        if self._poll_exception:
            raise self._poll_exception
        # mimic real response structure
        return {"result": {"Changes": list(self._changes)}}


class FakeCore:
    """Minimal stub of Core needed by ChangeGroupPoller tests."""
    def __init__(self):
        self._connected_event = asyncio.Event()
        self._connected_event.set()  # immediately "connected"
        self.cg_instance = None

    async def wait_until_connected(self, timeout=None):  # pragma: no cover - trivial
        if timeout:
            await asyncio.wait_for(self._connected_event.wait(), timeout)
        else:
            await self._connected_event.wait()

    def change_group(self, name):  # pragma: no cover - simple
        return self.cg_instance


@pytest.fixture
def fake_core():
    return FakeCore()

@pytest.mark.asyncio
async def test_poller_starts_and_runs(fake_core):
    cg = FakeChangeGroup()
    fake_core.cg_instance = cg
    poller = ChangeGroupPoller(fake_core, 'test_cg', poll_interval=0.01, request_timeout=0.05)
    poller.start()
    await asyncio.wait_for(poller.wait_until_running(timeout=1), timeout=1)
    await asyncio.sleep(0.05)  # allow some polls
    assert poller._state == PollerState.RUNNING
    assert cg.poll_calls >= 2
    await poller.stop()
    assert poller._state in (PollerState.IDLE, PollerState.STOPPING)

@pytest.mark.asyncio
async def test_subscribe_component_control_changes_before_start(fake_core):
    cg = FakeChangeGroup()
    fake_core.cg_instance = cg
    poller = ChangeGroupPoller(fake_core, 'test_cg', poll_interval=0.01, request_timeout=0.05)
    received = []
    async def listener(p, change):
        received.append(change)
    await poller.subscribe_component_control_changes(listener, 'CompA', 'Gain')
    poller.start()
    await poller.wait_until_running(timeout=1)
    assert any('CompA' in str(c) for c in cg.added)
    await poller.stop()

@pytest.mark.asyncio
async def test_control_added_after_cg_creation(fake_core):
    cg = FakeChangeGroup()
    fake_core.cg_instance = cg
    poller = ChangeGroupPoller(fake_core, 'test_cg', poll_interval=0.01, request_timeout=0.05)
    poller.start()
    await poller.wait_until_running(timeout=1)
    # add after start
    received = []
    async def listener(p, change):
        received.append(change)
    await poller.subscribe_component_control_changes(listener, 'CompB', 'Mute')
    # allow add
    await asyncio.sleep(0.02)
    assert any('CompB' in str(c) for c in cg.added)
    await poller.stop()

@pytest.mark.asyncio
async def test_poll_changes_dispatch(fake_core):
    cg = FakeChangeGroup()
    cg._changes.append({'Component': 'CompX', 'Name': 'Level', 'Value': 0.5})
    fake_core.cg_instance = cg
    poller = ChangeGroupPoller(fake_core, 'test_cg', poll_interval=0.01, request_timeout=0.05)
    received = []
    async def listener(p, change):
        received.append(change)
    await poller.subscribe_component_control_changes(listener, 'CompX', 'Level')
    poller.start()
    await poller.wait_until_running(timeout=1)
    await asyncio.sleep(0.03)
    assert received
    await poller.stop()

@pytest.mark.asyncio
async def test_timeout_handling(fake_core):
    cg = FakeChangeGroup()
    cg._poll_delay = 0.2  # longer than request_timeout
    fake_core.cg_instance = cg
    poller = ChangeGroupPoller(fake_core, 'test_cg', poll_interval=0.01, request_timeout=0.05)
    poller.start()
    await poller.wait_until_running(timeout=1)
    # let it hit timeout
    await asyncio.sleep(0.15)
    # should still be running or have restarted
    assert poller._state in (PollerState.STARTING, PollerState.RUNNING)
    await poller.stop()

@pytest.mark.asyncio
async def test_qrc_error_triggers_recreate(fake_core):
    cg = FakeChangeGroup()
    cg._poll_exception = QRCError({'code': 6, 'message': 'Unknown change group'})
    fake_core.cg_instance = cg
    poller = ChangeGroupPoller(fake_core, 'test_cg', poll_interval=0.01, request_timeout=0.05)
    poller.start()
    await asyncio.sleep(0.05)
    # should cycle through STARTING again
    assert poller._state in (PollerState.STARTING, PollerState.RUNNING)
    await poller.stop()

@pytest.mark.asyncio
async def test_generic_exception_logged_and_continues(fake_core):
    cg = FakeChangeGroup()
    cg._poll_exception = RuntimeError('boom')
    fake_core.cg_instance = cg
    poller = ChangeGroupPoller(fake_core, 'test_cg', poll_interval=0.01, request_timeout=0.05)
    poller.start()
    await asyncio.sleep(0.05)
    assert poller._state in (PollerState.STARTING, PollerState.RUNNING)
    await poller.stop()

@pytest.mark.asyncio
async def test_stop_idempotent(fake_core):
    cg = FakeChangeGroup()
    fake_core.cg_instance = cg
    poller = ChangeGroupPoller(fake_core, 'test_cg', poll_interval=0.01, request_timeout=0.05)
    poller.start()
    await poller.wait_until_running(timeout=1)
    await poller.stop()
    await poller.stop()  # second stop should be harmless
    assert poller._loop_task is None

@pytest.mark.asyncio
async def test_backward_compat_run_while_core_running(fake_core):
    cg = FakeChangeGroup()
    fake_core.cg_instance = cg
    poller = ChangeGroupPoller(fake_core, 'test_cg', poll_interval=0.01, request_timeout=0.05)
    # cancel shortly after start
    task = asyncio.create_task(poller.run_while_core_running())
    await asyncio.sleep(0.05)
    await poller.stop()
    await asyncio.sleep(0.01)
    assert poller._state in (PollerState.IDLE, PollerState.STOPPING)
    if not task.done():
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class ReconnectingCore(FakeCore):
    """Core stub that can disconnect/reconnect and yields new change group instances each time."""
    def __init__(self):
        super().__init__()
        self._connected_event = asyncio.Event()
        self._connected_event.set()
        self.created_cgs = []

    def change_group(self, name):  # noqa: ARG002
        cg = FakeChangeGroup()
        self.created_cgs.append(cg)
        return cg

    def disconnect(self):
        # Clear connection event (simulate loss). New event to drop existing waiters deterministically.
        self._connected_event = asyncio.Event()

    def reconnect(self):
        self._connected_event.set()


@pytest.mark.asyncio
async def test_recreate_after_disconnect_and_reconnect():
    """Verify poller recreates change group after core disconnect + reconnect.

    Steps:
    - Start poller while connected; initial CG created and control added.
    - Simulate disconnect and inject QRCError so inner loop exits.
    - Ensure poller transitions to STARTING and waits on reconnection.
    - Reconnect core; poller should create a NEW change group (second instance) and re-add subscribed controls.
    """
    core = ReconnectingCore()
    poller = ChangeGroupPoller(core, 'recreate_cg', poll_interval=0.01, request_timeout=0.05)
    # subscribe control before start
    await poller.subscribe_component_control_changes(lambda *_: None, 'CompC', 'Level')
    poller.start()
    await poller.wait_until_running(timeout=1)
    assert len(core.created_cgs) == 1
    first_cg = core.created_cgs[0]
    # control added
    assert any('CompC' in str(c) for c in first_cg.added)

    # Simulate disconnect & change group invalidation
    core.disconnect()
    # Cause poll error so loop unwinds promptly
    poller.cg._poll_exception = QRCError({'code': 6, 'message': 'Unknown change group'})

    # Wait until poller leaves RUNNING (STARTING or RUNNING with new instance after reconnect)
    async def wait_for_state_change():
        for _ in range(100):
            if poller._state == PollerState.STARTING:
                return True
            await asyncio.sleep(0.01)
        return False
    assert await wait_for_state_change(), 'Poller did not transition to STARTING after disconnect'

    # Reconnect core, allowing wait_until_connected to proceed and recreate
    core.reconnect()
    # wait until running again
    await poller.wait_until_running(timeout=1)
    # Allow one extra loop iteration for recreation completion
    await asyncio.sleep(0.05)
    assert poller._creation_count >= 2, f'Expected recreation count >=2, got {poller._creation_count}'
    second_cg = poller.cg
    assert second_cg is not first_cg
    assert any('CompC' in str(c) for c in second_cg.added), 'Control not re-added on recreation'
    await poller.stop()
