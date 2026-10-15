"""The grid outage blueprint, run in Home Assistant's own test harness (pytest-homeassistant-custom-component)."""
import asyncio
import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

BLUEPRINT = Path(__file__).parent.parent / "blueprints" / "automation" / "sa-solar" / "grid_outage.yaml"
LATCH = "input_boolean.grid_outage"
LOADS = ["input_boolean.geyser", "input_boolean.pool_pump"]


@pytest.fixture
async def env(hass: HomeAssistant, tmp_path):
    """A house: the grid at 231 V, the battery at 80%, a geyser and a pool pump on, the outage helper off."""
    hass.config.config_dir = str(tmp_path)
    folder = tmp_path / "blueprints" / "automation" / "sa-solar"
    folder.mkdir(parents=True)
    shutil.copy(BLUEPRINT, folder / "grid_outage.yaml")
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {
        "grid_outage": {"name": "Grid outage"},
        "geyser": {"name": "Geyser", "initial": True},
        "pool_pump": {"name": "Pool pump", "initial": True},
    }})
    grid(hass, 231)
    battery(hass, 80)
    await hass.async_block_till_done()
    return {"email": async_mock_service(hass, "notify", "send_message"),
            "phone": async_mock_service(hass, "notify", "mobile_app_test")}


def grid(hass, volts):
    hass.states.async_set("sensor.grid_voltage", str(volts), {"device_class": "voltage", "unit_of_measurement": "V"})


def battery(hass, pct):
    hass.states.async_set("sensor.battery", str(pct), {"device_class": "battery", "unit_of_measurement": "%"})


async def automation(hass, **inputs):
    config = {"grid_voltage": "sensor.grid_voltage", "outage_helper": LATCH, "battery_soc": "sensor.battery",
              "shed_loads": LOADS, "restore_loads": LOADS, "notify_entities": ["notify.email"],
              "notify_action": "notify.mobile_app_test"}
    config.update(inputs)
    assert await async_setup_component(hass, "automation", {"automation": {
        "alias": "Grid outage", "use_blueprint": {"path": "sa-solar/grid_outage.yaml", "input": config}}})
    await hass.async_block_till_done()


async def later(hass, freezer, **kw):
    freezer.tick(timedelta(**kw))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def is_on(hass, entity):
    return hass.states.get(entity).state == "on"


async def test_outage_one_message_loads_off_then_back_on_checked(hass, env, freezer):
    await automation(hass)
    grid(hass, 0)
    await later(hass, freezer, seconds=16)
    assert is_on(hass, LATCH)
    assert not any(is_on(hass, e) for e in LOADS)
    assert len(env["email"]) == 1 and len(env["phone"]) == 1
    call = env["email"][0].data
    assert call["entity_id"] == ["notify.email"] and call["title"] == "Grid off"
    assert "(0 V). Battery 80%. Switched off: Geyser, Pool pump." in call["message"]
    assert env["phone"][0].data["title"] == "Grid off"

    # The monitor dropping out and coming back during the outage (or a restart) sends nothing twice.
    grid(hass, "unavailable")
    await later(hass, freezer, seconds=30)
    grid(hass, 0)
    await later(hass, freezer, seconds=30)
    assert len(env["email"]) == 1

    # The grid back after an hour: one message, the loads on and checked.
    await later(hass, freezer, minutes=60)
    battery(hass, 55)
    grid(hass, 229)
    await later(hass, freezer, seconds=121)
    assert not is_on(hass, LATCH)
    assert all(is_on(hass, e) for e in LOADS)
    assert len(env["email"]) == 2
    back = env["email"][1].data
    assert back["title"] == "Grid restored"
    assert "after 1 h 3 min (229 V). Battery 55%. Switched back on: Geyser, Pool pump." in back["message"]
    assert "Not on" not in back["message"]


async def test_a_short_dip_or_an_unavailable_sensor_is_no_outage(hass, env, freezer):
    await automation(hass)
    grid(hass, 0)
    await later(hass, freezer, seconds=5)
    grid(hass, 231)
    await later(hass, freezer, seconds=30)
    grid(hass, "unavailable")
    await later(hass, freezer, minutes=10)
    grid(hass, "unknown")
    await later(hass, freezer, minutes=10)
    assert not is_on(hass, LATCH)
    assert all(is_on(hass, e) for e in LOADS)
    assert len(env["email"]) == 0


async def test_loads_wait_for_the_battery_when_the_grid_returns_low(hass, env, freezer):
    await automation(hass, restore_above=50)
    battery(hass, 40)
    grid(hass, 0)
    await later(hass, freezer, seconds=16)
    battery(hass, 30)
    grid(hass, 230)
    await later(hass, freezer, seconds=121)
    assert is_on(hass, LATCH), "the outage is not over for the loads yet"
    assert not any(is_on(hass, e) for e in LOADS)
    assert env["email"][1].data["title"] == "Grid restored"
    assert "The loads wait until the battery reaches 50%." in env["email"][1].data["message"]

    battery(hass, 52)
    await later(hass, freezer, seconds=61)
    assert not is_on(hass, LATCH)
    assert all(is_on(hass, e) for e in LOADS)
    assert len(env["email"]) == 3
    assert env["email"][2].data["message"] == ("The battery reached 50% with the grid back (230 V). Battery 52%. "
                                               "Switched back on: Geyser, Pool pump.")


async def test_loads_stay_on_when_the_battery_is_above_the_shed_limit(hass, env, freezer):
    await automation(hass, shed_below=60)
    grid(hass, 0)
    await later(hass, freezer, seconds=16)
    assert is_on(hass, LATCH)
    assert all(is_on(hass, e) for e in LOADS)
    assert "Switched off" not in env["email"][0].data["message"]


async def test_a_load_that_does_not_come_back_is_named(hass, env, freezer):
    hass.states.async_set("switch.pool_relay", "unavailable", {"friendly_name": "Pool pump relay"})
    await automation(hass, shed_loads=[], restore_loads=["input_boolean.geyser", "switch.pool_relay"], check_after=30)
    grid(hass, 0)
    await later(hass, freezer, seconds=16)
    assert "Switched off" not in env["email"][0].data["message"]
    grid(hass, 231)
    # The restore starts and then waits on the clock for the relay that never comes on; blocking until every task is
    # done here would wait for that wait, so let the run reach it first, then move the clock past the 30 s.
    freezer.tick(timedelta(seconds=121))
    async_fire_time_changed(hass)
    for _ in range(50):
        await asyncio.sleep(0)
    await later(hass, freezer, seconds=31)
    back = env["email"][-1].data
    assert back["title"] == "Grid restored - check the loads"
    assert "Switched back on: Geyser." in back["message"]
    assert "Not on after 30 s: Pool pump relay. Check them." in back["message"]


async def test_the_grid_returning_while_home_assistant_was_down(hass, env, freezer):
    await automation(hass)
    grid(hass, 0)
    await later(hass, freezer, seconds=16)
    assert is_on(hass, LATCH)
    # Down for a while; the grid came back meanwhile: the sensor comes back unknown, then reads the grid again.
    grid(hass, "unknown")
    await later(hass, freezer, minutes=30)
    grid(hass, 232)
    await later(hass, freezer, seconds=121)
    assert not is_on(hass, LATCH)
    assert all(is_on(hass, e) for e in LOADS)
    assert env["email"][-1].data["title"] == "Grid restored"


async def test_without_a_battery_sensor_or_loads(hass, env, freezer):
    await automation(hass, battery_soc="", shed_loads=[], restore_loads=[], notify_action="")
    grid(hass, 0)
    await later(hass, freezer, seconds=16)
    grid(hass, 231)
    await later(hass, freezer, seconds=121)
    assert [c.data["title"] for c in env["email"]] == ["Grid off", "Grid restored"]
    assert env["email"][0].data["message"].endswith("(0 V).")
    assert len(env["phone"]) == 0
