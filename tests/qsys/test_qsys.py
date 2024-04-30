import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.qsys_qrc import qrc
from custom_components.qsys_qrc.qsys.qrc import Core, QRCError


TEST_HOST = "127.0.0.1"
TEST_PORT = 1710

async def _mocked_open_connection():
    """ Create a mocked stream pair for testing. """
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
    mock_open_connection.assert_called_once_with(TEST_HOST, TEST_PORT, limit=5 * 1024 * 1024)

@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_core_run_until_stopped(mock_open_connection):
    mock_open_connection.return_value = await _mocked_open_connection()
    core = Core(TEST_HOST, TEST_PORT)
    run_task = asyncio.create_task(core.run_until_stopped())

    await core._connected
    run_task.cancel()  # Simulate stopping the run loop

    try:
        await run_task  # Await the task to ensure it completes
    except asyncio.CancelledError:
        pass
    assert run_task.cancelled()

@pytest.mark.asyncio
@patch('asyncio.open_connection', new_callable=AsyncMock)
async def test_core_call(mock_open_connection):
    reader, writer = await _mocked_open_connection()
    mock_open_connection.return_value = (reader, writer)
    core = Core(TEST_HOST, TEST_PORT)
    await core.connect()

    with patch.object(core, '_send', new_callable=AsyncMock) as mock_send:
        result = 412
        mock_send.side_effect = lambda params: core._pending[params['id']].set_result(result)
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
        mock_call.assert_called_once_with('Logon', params={'User': 'user', 'Password': 'pass'})

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
        retval = { "Name": "My APM", "Controls": [ { "Name": "ent.xfade.gain", "Value": -100.0, "String": "-100.0dB", "Position": 0 } ] }
        mock_call.return_value = retval
        component_api = qrc.ComponentAPI(core)
        result = await component_api.get('component_id', controls=[{ "Name": "ent.xfade.gain" }])
        mock_call.assert_called_once_with('Component.Get', params={'Name': 'component_id', 'Controls': [{'Name': 'ent.xfade.gain'}]})
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
        await component_api.set('component_id', { "Name": "My APM", "Controls": [ { "Name": "ent.xfade.gain", "Value": -100.0, "Ramp": 2.0 } ] })
        mock_call.assert_called_once_with('Component.Set', params={'Name': 'component_id', 'Controls': {'Name': 'My APM', 'Controls': [{'Name': 'ent.xfade.gain', 'Value': -100.0, 'Ramp': 2.0}]}})

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
                    { "Name": "n_inputs", "Value": "8" },
                    { "Name": "n_outputs", "Value": "8" },
                    { "Name": "max_delay", "Value": "0.5" },
                    { "Name": "delay_type", "Value": "0" },
                    { "Name": "linear_gain", "Value": "False" },
                    { "Name": "multi_channel_type", "Value": "1" },
                    { "Name": "multi_channel_count", "Value": "8" }
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
                    "Name": "invert",
                    "String": "normal",
                    "Name": "mute",
                    "String": "unmuted",
                }
            ]
        }
        mock_call.return_value = retval
        component_api = qrc.ComponentAPI(core)
        result = await component_api.get_controls('component_id')
        mock_call.assert_called_once_with('Component.GetControls', params={'Name': 'component_id'})
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
            "Component" : {
            "Name": "My Component",
            "Controls": [
                { "Name": "gain" },
                { "Name": "mute" }
            ]
            }
        }
        mock_call.return_value = addretval
        result = await change_group_api.add_component_control("My Component")
        mock_call.assert_called_once_with('ChangeGroup.AddComponentControl', params={'Id': 1234, 'Component': 'My Component'})
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
