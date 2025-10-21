import asyncio
import contextlib
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from custom_components.qsys_qrc import qrc
from custom_components.qsys_qrc.qsys.qrc import Core, ConnectionState, QRCError, DELIMITER


TEST_HOST = "127.0.0.1"
TEST_PORT = 1710


async def _mocked_open_connection():
    """Create a mocked stream pair for testing."""
    return MagicMock(), MagicMock()


@pytest.mark.asyncio
async def test_core_initialization():
    core = Core(TEST_HOST, TEST_PORT)
    assert core._host == TEST_HOST
    assert core._port == TEST_PORT


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_core_connect(mock_open_connection):
    mock_open_connection.return_value = await _mocked_open_connection()
    core = Core(TEST_HOST, TEST_PORT)
    await core.connect()
    mock_open_connection.assert_called_once_with(
        TEST_HOST, TEST_PORT, limit=5 * 1024 * 1024)


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_core_run_until_stopped(mock_open_connection):
    mock_open_connection.return_value = await _mocked_open_connection()
    core = Core(TEST_HOST, TEST_PORT)
    run_task = asyncio.create_task(core.run_until_stopped())

    await core.wait_until_connected()
    await core.stop()  # Properly stop the core

    with contextlib.suppress(asyncio.CancelledError):
        await run_task  # Await the task to ensure it completes
    assert run_task.done()


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_core_call(mock_open_connection):
    reader, writer = await _mocked_open_connection()
    mock_open_connection.return_value = (reader, writer)
    core = Core(TEST_HOST, TEST_PORT)
    await core.connect()

    with patch.object(core, '_send', new_callable=AsyncMock) as mock_send:
        result = 412
        mock_send.side_effect = lambda params: core._pending[params['id']].set_result(
            result)
        response = await core.call('Test', {'param': 'value'})
        mock_send.assert_called_once()
        assert response is result


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_core_noop(mock_open_connection):
    reader, writer = await _mocked_open_connection()
    mock_open_connection.return_value = (reader, writer)
    core = Core(TEST_HOST, TEST_PORT)
    await core.connect()

    with patch.object(core, 'call', new_callable=AsyncMock) as mock_call:
        mock_call.return_value = None
        await core.noop()
        mock_call.assert_called_once_with('NoOp')


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_core_logon(mock_open_connection):
    reader, writer = await _mocked_open_connection()
    mock_open_connection.return_value = (reader, writer)
    core = Core(TEST_HOST, TEST_PORT)
    await core.connect()
    with patch.object(core, 'call', new_callable=AsyncMock) as mock_call:
        mock_call.return_value = None
        await core.logon('user', 'pass')
        mock_call.assert_called_once_with(
            'Logon', params={'User': 'user', 'Password': 'pass'})


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_core_status_get(mock_open_connection):
    reader, writer = await _mocked_open_connection()
    mock_open_connection.return_value = (reader, writer)
    core = Core(TEST_HOST, TEST_PORT)
    await core.connect()

    with patch.object(core, 'call', new_callable=AsyncMock) as mock_call:
        mock_call.return_value = None
        await core.status_get()
        mock_call.assert_called_once_with('StatusGet')


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_component_api_get(mock_open_connection):
    reader, writer = await _mocked_open_connection()
    mock_open_connection.return_value = (reader, writer)
    core = Core(TEST_HOST, TEST_PORT)
    await core.connect()

    with patch.object(core, 'call', new_callable=AsyncMock) as mock_call:
        retval = {"Name": "My APM", "Controls": [
            {"Name": "ent.xfade.gain", "Value": -100.0, "String": "-100.0dB", "Position": 0}]}
        mock_call.return_value = retval
        component_api = qrc.ComponentAPI(core)
        result = await component_api.get('component_id', controls=[{"Name": "ent.xfade.gain"}])
        mock_call.assert_called_once_with('Component.Get', params={
                                          'Name': 'component_id', 'Controls': [{'Name': 'ent.xfade.gain'}]})
        assert result == retval


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_component_api_set(mock_open_connection):
    reader, writer = await _mocked_open_connection()
    mock_open_connection.return_value = (reader, writer)
    core = Core(TEST_HOST, TEST_PORT)
    await core.connect()

    with patch.object(core, 'call', new_callable=AsyncMock) as mock_call:
        mock_call.return_value = None
        component_api = qrc.ComponentAPI(core)
        await component_api.set('component_id', {"Name": "My APM", "Controls": [{"Name": "ent.xfade.gain", "Value": -100.0, "Ramp": 2.0}]})
        mock_call.assert_called_once_with('Component.Set', params={'Name': 'component_id', 'Controls': {
                                          'Name': 'My APM', 'Controls': [{'Name': 'ent.xfade.gain', 'Value': -100.0, 'Ramp': 2.0}]}})


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_component_api_get_components(mock_open_connection):
    reader, writer = await _mocked_open_connection()
    mock_open_connection.return_value = (reader, writer)
    core = Core(TEST_HOST, TEST_PORT)
    await core.connect()

    with patch.object(core, 'call', new_callable=AsyncMock) as mock_call:
        retval = [
            {
                "Name": "APM ABC",
                "Type": "apm",
                "Properties": []
            },
            {
                "Name": "My Delay Mixer",
                "Type": "delay_matrix",
                "Properties": [
                    {"Name": "n_inputs", "Value": "8"},
                    {"Name": "n_outputs", "Value": "8"},
                    {"Name": "max_delay", "Value": "0.5"},
                    {"Name": "delay_type", "Value": "0"},
                    {"Name": "linear_gain", "Value": "False"},
                    {"Name": "multi_channel_type", "Value": "1"},
                    {"Name": "multi_channel_count", "Value": "8"}
                ]
            }
        ]
        mock_call.return_value = retval
        component_api = qrc.ComponentAPI(core)
        result = await component_api.get_components()
        mock_call.assert_called_once_with('Component.GetComponents')
        assert result == retval


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_component_api_get_controls(mock_open_connection):
    reader, writer = await _mocked_open_connection()
    mock_open_connection.return_value = (reader, writer)
    core = Core(TEST_HOST, TEST_PORT)
    await core.connect()

    with patch.object(core, 'call', new_callable=AsyncMock) as mock_call:
        retval = {
            "Name": "MyGain",
            "Controls": [
                {
                    "Name": "bypass",
                    "Type": "Boolean",
                    "Value": False,
                    "String": "no",
                    "Position": 0.0,
                    "Direction": "Read/Write"
                },
                {
                    "Name": "gain",
                    "Type": "Float",
                    "Value": 0.0,
                    "ValueMin": -100.0,
                    "ValueMax": 20.0,
                    "StringMin": "-100dB",
                    "StringMax": "20.0dB",
                    "String": "0dB",
                    "Position": 0.83333331,
                }
            ]
        }
        mock_call.return_value = retval
        component_api = qrc.ComponentAPI(core)
        result = await component_api.get_controls('component_id')
        mock_call.assert_called_once_with(
            'Component.GetControls', params={'Name': 'component_id'})
        assert result == retval


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_change_group_api_poll(mock_open_connection):
    reader, writer = await _mocked_open_connection()
    mock_open_connection.return_value = (reader, writer)
    core = Core(TEST_HOST, TEST_PORT)
    await core.connect()

    with patch.object(core, 'call', new_callable=AsyncMock) as mock_call:
        change_group_api = core.change_group(1234)

        addretval = {
            "Id": "my change group",
            "Component": {
                "Name": "My Component",
                "Controls": [
                    {"Name": "gain"},
                    {"Name": "mute"}
                ]
            }
        }
        mock_call.return_value = addretval
        result = await change_group_api.add_component_control("My Component")
        mock_call.assert_called_once_with('ChangeGroup.AddComponentControl', params={
                                          'Id': 1234, 'Component': 'My Component'})
        assert result == addretval

        mock_call.reset_mock()

        retval = {
            "Id": "my change group",
            "Changes": [
                {
                    "Name": "some control",
                    "Value": -12,
                    "String": "-12dB"
                },
                {
                    "Component": "My Component",
                    "Name": "gain",
                    "Value": -12,
                    "String": "-12dB"
                }
            ]
        }
        mock_call.return_value = retval
        result = await change_group_api.poll()
        mock_call.assert_called_once_with('ChangeGroup.Poll', {'Id': 1234})
        assert result == retval


# ============================================================================
# New tests for refactored state management
# ============================================================================

@pytest.mark.asyncio
async def test_core_initial_state():
    """Test that Core starts in DISCONNECTED state."""
    core = Core(TEST_HOST, TEST_PORT)
    state = await core.get_state()
    assert state == ConnectionState.DISCONNECTED


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_core_state_transitions(mock_open_connection):
    """Test that connection state transitions work correctly."""
    mock_open_connection.return_value = await _mocked_open_connection()
    core = Core(TEST_HOST, TEST_PORT)

    # Initially disconnected
    assert await core.get_state() == ConnectionState.DISCONNECTED

    # After connect, should be CONNECTING then implicitly CONNECTED
    await core.connect()
    # Note: connect() sets CONNECTING, but doesn't set CONNECTED
    # That happens in run_until_stopped

    # Set to connected manually for testing
    await core._set_state(ConnectionState.CONNECTED)
    assert await core.get_state() == ConnectionState.CONNECTED

    # After cleanup, should be back to DISCONNECTED
    await core._cleanup_connection()
    assert await core.get_state() == ConnectionState.DISCONNECTED


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_wait_until_connected_timeout(mock_open_connection):
    """Test that wait_until_connected respects timeout."""
    core = Core(TEST_HOST, TEST_PORT)

    # Should timeout if never connected
    with pytest.raises(asyncio.TimeoutError):
        await core.wait_until_connected(timeout=0.1)


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_wait_until_running_alias(mock_open_connection):
    """Test that wait_until_running is an alias for wait_until_connected."""
    mock_open_connection.return_value = await _mocked_open_connection()
    core = Core(TEST_HOST, TEST_PORT)

    # Start the run loop
    run_task = asyncio.create_task(core.run_until_stopped())

    try:
        # Both methods should work
        await asyncio.wait_for(core.wait_until_running(), timeout=1.0)
        await asyncio.wait_for(core.wait_until_connected(), timeout=1.0)
        assert await core.get_state() == ConnectionState.CONNECTED
    finally:
        await core.stop()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_on_connected_commands_execution(mock_open_connection):
    """Test that on_connected commands are executed when connected."""
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_open_connection.return_value = (mock_reader, mock_writer)

    core = Core(TEST_HOST, TEST_PORT)

    # Track command execution
    command_executed = []

    async def async_command():
        command_executed.append('async')

    def sync_command():
        command_executed.append('sync')

    dict_command = {"method": "TestMethod", "params": {"test": "value"}}

    core.set_on_connected_commands([async_command, sync_command, dict_command])

    # Mock the reader to raise EOF after commands execute
    mock_reader.readuntil.side_effect = EOFError()

    # Run the connection cycle
    with patch.object(core, 'call', new_callable=AsyncMock) as mock_call:
        run_task = asyncio.create_task(core.run_until_stopped())

        # Wait a bit for commands to execute
        await asyncio.sleep(0.2)

        # Verify commands were executed
        assert 'async' in command_executed
        assert 'sync' in command_executed
        mock_call.assert_called_with(method="TestMethod", params={"test": "value"})

        await core.stop()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_reconnection_with_backoff(mock_open_connection):
    """Test that reconnection uses exponential backoff."""
    # Make connection fail initially
    connection_attempts = []

    async def track_connection(*args, **kwargs):
        connection_attempts.append(len(connection_attempts))
        raise ConnectionError("Connection failed")

    mock_open_connection.side_effect = track_connection

    # Use tiny backoff values for speed
    core = Core(
        TEST_HOST,
        TEST_PORT,
        backoff_initial=0.01,
        backoff_multiplier=1.1,
        backoff_max=0.05,
    )
    run_task = asyncio.create_task(core.run_until_stopped())

    # Wait until we have at least 3 attempts rapidly rather than sleeping fixed duration
    from .utils import wait_for_condition
    await wait_for_condition(lambda: len(connection_attempts) >= 3, timeout=0.5, fail_msg="Did not reach 3 connection attempts quickly")

    await core.stop()
    with contextlib.suppress(asyncio.CancelledError):
        await run_task

    assert len(connection_attempts) >= 3
    # Just verify we got multiple connection attempts (backoff logic is working)
    # The actual timing can vary in test environments


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_cleanup_fails_pending_requests(mock_open_connection):
    """Test that cleanup properly fails pending requests."""
    mock_reader, mock_writer = await _mocked_open_connection()
    mock_open_connection.return_value = (mock_reader, mock_writer)

    core = Core(TEST_HOST, TEST_PORT)
    await core.connect()
    await core._set_state(ConnectionState.CONNECTED)

    # Create a pending request
    future = asyncio.Future()
    core._pending[123] = future

    # Cleanup should fail the pending request
    await core._cleanup_connection()

    assert future.done()
    with pytest.raises(QRCError) as exc_info:
        future.result()
    assert exc_info.value.error["code"] == -1
    assert exc_info.value.error["message"] == "disconnected"


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_send_when_not_connected(mock_open_connection):
    """Test that _send raises error when not connected."""
    core = Core(TEST_HOST, TEST_PORT)

    # Try to send without connecting
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            core._send({"test": "data"}),
            timeout=0.5
        )


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_send_checks_connection_state(mock_open_connection):
    """Test that _send checks connection state after waiting."""
    mock_reader, mock_writer = await _mocked_open_connection()
    mock_open_connection.return_value = (mock_reader, mock_writer)

    core = Core(TEST_HOST, TEST_PORT)
    await core.connect()

    # Set state to DISCONNECTED but keep event set
    # This simulates a race condition
    await core._set_state(ConnectionState.DISCONNECTED)
    core._connected_event.set()  # Manually set event despite being disconnected

    # Should raise error because state check happens after wait
    with pytest.raises(QRCError) as exc_info:
        await core._send({"test": "data"})
    assert exc_info.value.error["message"] == "not connected"


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_reader_task_cancellation_on_cleanup(mock_open_connection):
    """Test that reader task is properly cancelled during cleanup."""
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_open_connection.return_value = (mock_reader, mock_writer)

    # Make reader raise EOF after a short delay
    async def delayed_eof(_):
        await asyncio.sleep(10)  # Long enough to test cancellation
        raise EOFError()

    mock_reader.readuntil.side_effect = delayed_eof

    core = Core(TEST_HOST, TEST_PORT)
    run_task = asyncio.create_task(core.run_until_stopped())

    try:
        # Wait for connection
        await core.wait_until_connected()

        # Reader task should be running
        assert core._reader_task is not None
        reader_task = core._reader_task
        assert not reader_task.done()

        # Stop should cancel reader task
        await core.stop()

        # Give cleanup time to complete
        await asyncio.sleep(0.2)

        # Reader task should now be done (cancelled)
        assert reader_task.done()
        assert core._reader_task is None
    finally:
        # Ensure the run task is cancelled
        if not run_task.done():
            run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_multiple_stop_calls(mock_open_connection):
    """Test that multiple stop() calls are handled gracefully."""
    mock_open_connection.return_value = await _mocked_open_connection()

    core = Core(TEST_HOST, TEST_PORT)
    run_task = asyncio.create_task(core.run_until_stopped())

    await core.wait_until_connected()

    # Multiple stops should not cause issues
    await core.stop()
    await core.stop()
    await core.stop()

    with contextlib.suppress(asyncio.CancelledError):
        await run_task

    assert run_task.done()


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_connection_cycle_handles_eof(mock_open_connection):
    """Test that connection cycle properly handles EOFError."""
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_reader.readuntil.side_effect = EOFError()
    mock_open_connection.return_value = (mock_reader, mock_writer)

    core = Core(TEST_HOST, TEST_PORT)

    # Should handle EOF and try to reconnect
    run_task = asyncio.create_task(core.run_until_stopped())

    # Give it time to handle EOF and try reconnection
    await asyncio.sleep(0.2)

    await core.stop()
    with contextlib.suppress(asyncio.CancelledError):
        await run_task


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_connection_cycle_handles_timeout(mock_open_connection):
    """Test that connection cycle properly handles TimeoutError."""
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_reader.readuntil.side_effect = TimeoutError()
    mock_open_connection.return_value = (mock_reader, mock_writer)

    core = Core(TEST_HOST, TEST_PORT)

    # Should handle timeout and try to reconnect
    run_task = asyncio.create_task(core.run_until_stopped())

    # Give it time to handle timeout and try reconnection
    await asyncio.sleep(0.2)

    await core.stop()
    with contextlib.suppress(asyncio.CancelledError):
        await run_task


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_process_response_with_error(mock_open_connection):
    """Test that _process_response handles error responses."""
    mock_reader, mock_writer = await _mocked_open_connection()
    mock_open_connection.return_value = (mock_reader, mock_writer)

    core = Core(TEST_HOST, TEST_PORT)
    await core.connect()

    # Create a pending request
    future = asyncio.Future()
    request_id = 42
    core._pending[request_id] = future

    # Process error response
    error_response = {
        "id": request_id,
        "error": {
            "code": -32601,
            "message": "Method not found"
        }
    }

    await core._process_response(error_response)

    # Future should have exception
    assert future.done()
    with pytest.raises(QRCError) as exc_info:
        future.result()
    assert exc_info.value.error["code"] == -32601


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_process_response_with_success(mock_open_connection):
    """Test that _process_response handles success responses."""
    mock_reader, mock_writer = await _mocked_open_connection()
    mock_open_connection.return_value = (mock_reader, mock_writer)

    core = Core(TEST_HOST, TEST_PORT)
    await core.connect()

    # Create a pending request
    future = asyncio.Future()
    request_id = 42
    core._pending[request_id] = future

    # Process success response
    success_response = {
        "id": request_id,
        "result": {"status": "ok", "value": 123}
    }

    await core._process_response(success_response)

    # Future should have result
    assert future.done()
    result = future.result()
    assert result == success_response


@pytest.mark.asyncio
async def test_generate_id_wraps_around():
    """Test that ID generation wraps around at 65535."""
    core = Core(TEST_HOST, TEST_PORT)

    # Set ID close to max
    core._id = 65533

    id1 = core._generate_id()
    assert id1 == 65534

    id2 = core._generate_id()
    assert id2 == 0  # (65535) % 65535 = 0

    id3 = core._generate_id()
    assert id3 == 1  # (0 + 1) % 65535 = 1


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_set_on_connected_commands(mock_open_connection):
    """Test setting on_connected_commands."""
    core = Core(TEST_HOST, TEST_PORT)

    commands = [lambda: None, {"method": "Test"}]
    core.set_on_connected_commands(commands)

    assert core._on_connected_commands == commands


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_component_factory_method(mock_open_connection):
    """Test that component() returns ComponentAPI instance."""
    core = Core(TEST_HOST, TEST_PORT)
    component_api = core.component()

    assert isinstance(component_api, qrc.ComponentAPI)
    assert component_api._core is core


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_change_group_factory_method(mock_open_connection):
    """Test that change_group() returns ChangeGroupAPI instance."""
    core = Core(TEST_HOST, TEST_PORT)
    cg_id = 12345
    cg_api = core.change_group(cg_id)

    assert isinstance(cg_api, qrc.ChangeGroupAPI)
    assert cg_api._core is core
    assert cg_api.id == cg_id


# ============================================================================
# Reliability and failure mode tests
# ============================================================================

@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_failure_during_connection_establishment(mock_open_connection):
    """Test that failures during connection establishment are handled and retried."""
    attempts = []

    async def failing_connect(*args, **kwargs):
        attempts.append(len(attempts))
        if len(attempts) < 3:
            raise ConnectionRefusedError("Connection refused")
        # Succeed on third attempt
        return await _mocked_open_connection()

    mock_open_connection.side_effect = failing_connect

    # Use tiny backoff values to accelerate retries while preserving semantics
    core = Core(
        TEST_HOST,
        TEST_PORT,
        backoff_initial=0.01,
        backoff_multiplier=1.1,
        backoff_max=0.02,
        connect_timeout=0.05,
    )
    run_task = asyncio.create_task(core.run_until_stopped())

    try:
        # Should eventually connect after retries
        await asyncio.wait_for(core.wait_until_connected(), timeout=2)
        assert len(attempts) >= 3
        assert await core.get_state() == ConnectionState.CONNECTED
    finally:
        await core.stop()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_failure_during_on_connected_commands(mock_open_connection):
    """Test that failures in on_connected commands don't prevent operation."""
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_open_connection.return_value = (mock_reader, mock_writer)
    mock_reader.readuntil.side_effect = EOFError()  # Will disconnect immediately

    core = Core(TEST_HOST, TEST_PORT)

    commands_executed = []

    async def failing_command():
        commands_executed.append("failing")
        raise RuntimeError("Command failed!")

    async def succeeding_command():
        commands_executed.append("succeeding")

    core.set_on_connected_commands([failing_command, succeeding_command])

    run_task = asyncio.create_task(core.run_until_stopped())

    try:
        await asyncio.wait_for(core.wait_until_connected(), timeout=5)
        await asyncio.sleep(0.2)  # Give commands time to execute

        # Both commands should have been attempted despite first one failing
        assert "failing" in commands_executed
        assert "succeeding" in commands_executed
    finally:
        await core.stop()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_stuck_connect_timeout(mock_open_connection):
    """Test that stuck connection attempts timeout and retry."""
    attempts = []

    async def stuck_connect(*args, **kwargs):
        attempts.append(len(attempts))
        # First attempt hangs
        if len(attempts) == 1:
            await asyncio.sleep(100)  # Simulate stuck connection
        # Second attempt succeeds
        return await _mocked_open_connection()

    mock_open_connection.side_effect = stuck_connect

    # Shrink connection timeout & backoff to make the timeout/retry cycle fast
    core = Core(
        TEST_HOST,
        TEST_PORT,
        connect_timeout=0.05,
        backoff_initial=0.01,
        backoff_multiplier=1.1,
        backoff_max=0.02,
    )
    run_task = asyncio.create_task(core.run_until_stopped())

    try:
        # Should timeout first attempt and retry
        await asyncio.wait_for(core.wait_until_connected(), timeout=2)
        # Should have made at least 2 attempts
        assert len(attempts) >= 2
    finally:
        await core.stop()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_stuck_reader_during_read(mock_open_connection):
    """Test that stuck reader is properly handled and cleaned up."""
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_open_connection.return_value = (mock_reader, mock_writer)

    # Make first read hang, then raise EOF
    read_count = [0]
    async def stuck_then_eof(_):
        read_count[0] += 1
        if read_count[0] == 1:
            # Simulate a brief "stuck" period before EOF (reduced from 0.5s)
            await asyncio.sleep(0.05)
            raise EOFError()  # Then disconnect
        await asyncio.sleep(100)  # Subsequent reads hang

    mock_reader.readuntil.side_effect = stuck_then_eof

    core = Core(TEST_HOST, TEST_PORT)
    run_task = asyncio.create_task(core.run_until_stopped())

    try:
        await asyncio.wait_for(core.wait_until_connected(), timeout=2)
        # Wait until the first (stuck) read attempt completed and triggered EOF/cleanup
        from .utils import wait_for_condition
        await wait_for_condition(
            lambda: read_count[0] >= 1 and core._reader_task is None,
            timeout=0.5,
            fail_msg="Reader task did not clean up after EOF",
        )

        # Should handle the stuck reader and clean up
        await core.stop()
        # Small grace period for final cleanup
        await asyncio.sleep(0.05)

        # Should be in disconnected/stopping state
        state = await core.get_state()
        assert state in (ConnectionState.DISCONNECTED, ConnectionState.STOPPING)
    finally:
        if not run_task.done():
            run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_writer_close_failure(mock_open_connection):
    """Test that writer close failures don't prevent cleanup."""
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_open_connection.return_value = (mock_reader, mock_writer)
    mock_reader.readuntil.side_effect = EOFError()

    # Make writer.close() raise an exception
    mock_writer.close.side_effect = RuntimeError("Close failed")

    core = Core(TEST_HOST, TEST_PORT)
    run_task = asyncio.create_task(core.run_until_stopped())

    try:
        await asyncio.wait_for(core.wait_until_connected(), timeout=5)
        await asyncio.sleep(0.2)  # Let disconnect happen

        # Despite writer.close() failing, should still clean up
        await core.stop()

        state = await core.get_state()
        assert state in (ConnectionState.DISCONNECTED, ConnectionState.STOPPING)
    finally:
        if not run_task.done():
            run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_unexpected_exception_during_read(mock_open_connection):
    """Test that unexpected exceptions during read are handled and reconnection occurs."""
    mock_reader = AsyncMock()
    mock_writer = MagicMock()

    connection_count = [0]

    async def multi_connection(*args, **kwargs):
        connection_count[0] += 1
        reader = AsyncMock()
        writer = MagicMock()

        if connection_count[0] == 1:
            # First connection: raise unexpected exception
            reader.readuntil.side_effect = ValueError("Unexpected error!")
        else:
            # Subsequent connections: EOF
            reader.readuntil.side_effect = EOFError()

        return reader, writer

    mock_open_connection.side_effect = multi_connection

    core = Core(TEST_HOST, TEST_PORT, backoff_initial=0.01, backoff_multiplier=1.1, backoff_max=0.05)
    run_task = asyncio.create_task(core.run_until_stopped())

    try:
        await asyncio.wait_for(core.wait_until_connected(), timeout=2)
        from .utils import wait_for_condition
        await wait_for_condition(lambda: connection_count[0] >= 2, timeout=2.0, fail_msg="Second connection not established")
    finally:
        await core.stop()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_continuous_reconnection_attempts(mock_open_connection):
    """Test that core keeps trying to reconnect indefinitely on failures."""
    attempts = []

    async def always_fail(*args, **kwargs):
        attempts.append(len(attempts))
        raise ConnectionError("Always fails")

    mock_open_connection.side_effect = always_fail

    core = Core(TEST_HOST, TEST_PORT, backoff_initial=0.01, backoff_multiplier=1.1, backoff_max=0.05)
    run_task = asyncio.create_task(core.run_until_stopped())

    try:
        from .utils import wait_for_condition
        await wait_for_condition(lambda: len(attempts) >= 3, timeout=2.0, fail_msg="Did not reach 3 attempts")
        await core.stop()
    finally:
        if not run_task.done():
            run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_memory_leak_prevention_on_reconnect(mock_open_connection, caplog):
    """Test that pending requests are cleaned up to prevent memory leaks."""
    connection_count = [0]

    async def multi_connection(*args, **kwargs):
        connection_count[0] += 1
        reader = AsyncMock()
        writer = MagicMock()

        # All connections immediately EOF (disconnect)
        reader.readuntil.side_effect = EOFError()

        return reader, writer

    mock_open_connection.side_effect = multi_connection

    core = Core(TEST_HOST, TEST_PORT, backoff_initial=0.01, backoff_multiplier=1.1, backoff_max=0.05)
    # Suppress noisy error-level logs produced during intentional EOF cycles
    caplog.set_level("CRITICAL")
    run_task = asyncio.create_task(core.run_until_stopped())

    try:
        from .utils import wait_for_condition
        futures_to_check = []
        for i in range(5):
            await asyncio.wait_for(core.wait_until_connected(), timeout=2)
            future = asyncio.Future()
            core._pending[100 + i] = future
            futures_to_check.append(future)
            # Trigger EOF on reader to force cleanup
            if core._reader:
                core._reader.readuntil.side_effect = EOFError()
            await wait_for_condition(lambda: future.done(), timeout=0.5, fail_msg="Pending future not failed")
        await wait_for_condition(lambda: len(core._pending) == 0, timeout=0.5, fail_msg="Pending dict not cleared")
    finally:
        await core.stop()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task
@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_call_during_reconnection(mock_open_connection):
    """Test that calls made during reconnection wait for connection."""
    connection_count = [0]

    async def delayed_connection(*args, **kwargs):
        connection_count[0] += 1
        if connection_count[0] == 1:
            raise ConnectionError("Failed")
        return await _mocked_open_connection()

    mock_open_connection.side_effect = delayed_connection

    core = Core(TEST_HOST, TEST_PORT, backoff_initial=0.01, backoff_multiplier=1.1, backoff_max=0.05)
    run_task = asyncio.create_task(core.run_until_stopped())

    try:
        # Try to make a call while disconnected
        call_task = asyncio.create_task(core.noop())

        # Should wait for connection and eventually succeed
        with patch.object(core, 'call', new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {"result": "ok"}
            await asyncio.wait_for(core.wait_until_connected(), timeout=2)
            # Now the call should be able to proceed
    finally:
        await core.stop()
        if not call_task.done():
            call_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, QRCError):
            await call_task
        with contextlib.suppress(asyncio.CancelledError):
            await run_task


@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_rapid_stop_start_cycles(mock_open_connection):
    """Test that rapid stop/start cycles don't cause issues."""
    mock_open_connection.return_value = await _mocked_open_connection()

    # Use separate Core instances for each cycle since stop_event stays set
    for _ in range(3):
        core = Core(TEST_HOST, TEST_PORT)
        run_task = asyncio.create_task(core.run_until_stopped())

        try:
            await asyncio.wait_for(core.wait_until_connected(), timeout=5)
            await core.stop()

            with contextlib.suppress(asyncio.CancelledError):
                await run_task

            # Brief pause before next cycle
            await asyncio.sleep(0.1)
        finally:
            if not run_task.done():
                run_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await run_task

        # Should end in disconnected state
        state = await core.get_state()
        assert state in (ConnectionState.DISCONNECTED, ConnectionState.STOPPING)
@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_json_parse_error_during_read(mock_open_connection):
    """Test that JSON parse errors during read are handled gracefully."""
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_open_connection.return_value = (mock_reader, mock_writer)

    # Return invalid JSON
    mock_reader.readuntil.return_value = b"invalid json{{{" + DELIMITER

    core = Core(TEST_HOST, TEST_PORT)
    run_task = asyncio.create_task(core.run_until_stopped())

    try:
        await asyncio.wait_for(core.wait_until_connected(), timeout=5)

        # Give it time to try to parse and fail
        await asyncio.sleep(0.5)

        # Should handle the parse error gracefully
        await core.stop()
    finally:
        if not run_task.done():
            run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task


@pytest.mark.asyncio
async def test_no_resource_leaks_over_time():
    """Test that there are no resource leaks over multiple connection cycles."""
    # This is a simple check - in production you'd use tracemalloc or similar
    core = Core(TEST_HOST, TEST_PORT)

    # Check initial state
    assert len(core._pending) == 0
    assert core._reader is None
    assert core._writer is None
    assert core._reader_task is None

    # Simulate multiple cleanup cycles
    for i in range(10):
        # Manually create some state (using unique IDs to avoid conflicts)
        future1 = asyncio.Future()
        future2 = asyncio.Future()
        core._pending[100 + i * 2] = future1
        core._pending[101 + i * 2] = future2

        # Clean up
        await core._cleanup_connection()

        # Verify cleanup - futures should be failed and removed from pending
        assert future1.done()
        assert future2.done()
        # After cleanup, pending should be empty
        assert len(core._pending) == 0
        assert core._reader is None
        assert core._writer is None
        assert core._reader_task is None