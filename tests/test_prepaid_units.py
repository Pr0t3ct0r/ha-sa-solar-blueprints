"""The prepaid units blueprint, run in Home Assistant's own test harness."""
import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

BLUEPRINT = Path(__file__).parent.parent / "blueprints" / "automation" / "sa-solar" / "prepaid_units.yaml"
UNITS = "input_number.prepaid_units"
MARK = "input_number.prepaid_mark"


@pytest.fixture
async def env(hass: HomeAssistant, tmp_path):
    """A meter at 300 kWh, the grid import counter at 12000 kWh, the mark not set yet."""
    hass.config.config_dir = str(tmp_path)
    folder = tmp_path / "blueprints" / "automation" / "sa-solar"
    folder.mkdir(parents=True)
    shutil.copy(BLUEPRINT, folder / "prepaid_units.yaml")
    assert await async_setup_component(hass, "input_number", {"input_number": {
        "prepaid_units": {"name": "Prepaid units", "min": 0, "max": 10000, "step": 0.01, "initial": 300, "mode": "box"},
        "prepaid_mark": {"name": "Prepaid mark", "min": 0, "max": 1000000, "step": 0.001, "initial": 0, "mode": "box"},
    }})
    grid_import(hass, 12000)
    await hass.async_block_till_done()
    email = async_mock_service(hass, "notify", "send_message")
    assert await async_setup_component(hass, "automation", {"automation": {
        "alias": "Prepaid", "use_blueprint": {"path": "sa-solar/prepaid_units.yaml", "input": {
            "grid_import": "sensor.grid_import", "units_left": UNITS, "import_mark": MARK, "low_below": 50,
            "notify_entities": ["notify.email"]}}}})
    await hass.async_block_till_done()
    return email


def grid_import(hass, kwh):
    hass.states.async_set("sensor.grid_import", str(kwh), {"device_class": "energy", "unit_of_measurement": "kWh",
                                                           "state_class": "total_increasing"})


def value(hass, entity):
    return float(hass.states.get(entity).state)


async def reading(hass, kwh):
    grid_import(hass, kwh)
    await hass.async_block_till_done()


async def set_units(hass, kwh):
    """Set by hand (after loading a token, from the meter)."""
    await hass.services.async_call("input_number", "set_value", {"entity_id": UNITS, "value": kwh}, blocking=True)
    await hass.async_block_till_done()


async def test_first_reading_sets_the_mark_then_use_comes_off_in_steps(hass, env):
    await reading(hass, 12000.02)  # the first reading: the mark is set, the units stay
    assert value(hass, MARK) == pytest.approx(12000.02) and value(hass, UNITS) == 300
    await reading(hass, 12000.07)  # under one 0.1 kWh step: nothing written
    assert value(hass, MARK) == pytest.approx(12000.02) and value(hass, UNITS) == 300
    await reading(hass, 12000.32)
    assert value(hass, UNITS) == pytest.approx(299.7) and value(hass, MARK) == pytest.approx(12000.32)
    assert len(env) == 0


async def test_use_while_home_assistant_was_down_is_still_counted(hass, env):
    await reading(hass, 12000.0 + 0.001)
    await reading(hass, "unavailable")
    await reading(hass, "unknown")
    await reading(hass, 12003.5)
    assert value(hass, UNITS) == pytest.approx(296.501, abs=0.002)


async def test_a_daily_counter_starting_again_at_midnight(hass, env):
    await reading(hass, 7.4)  # a daily counter: the first reading sets the mark (a big drop from 12000)
    await reading(hass, 7.6)
    assert value(hass, UNITS) == pytest.approx(299.8)
    await reading(hass, 0.0)  # midnight: the mark starts again (at 0.001, as 0 means not set yet)
    assert value(hass, MARK) == pytest.approx(0.001) and value(hass, UNITS) == pytest.approx(299.8)
    await reading(hass, 0.3)
    assert value(hass, UNITS) == pytest.approx(299.5, abs=0.0011)  # at most 1 Wh a midnight goes uncounted


async def test_a_jump_too_big_is_not_taken_as_use(hass, env):
    await reading(hass, 12000.1)
    await reading(hass, 12000.3)
    assert value(hass, UNITS) == pytest.approx(299.8)
    await reading(hass, 12500.0)
    assert value(hass, UNITS) == pytest.approx(299.8) and value(hass, MARK) == pytest.approx(12500.0)
    assert env[-1].data["title"] == "Prepaid electricity - check the units"
    assert "jumped 499.7 kWh in one go, more than 50 kWh" in env[-1].data["message"]


async def test_running_low_warns_once_per_token_and_a_recharge_is_noted(hass, env, freezer):
    await set_units(hass, 50.3)
    await reading(hass, 12000.1)  # sets the mark
    await reading(hass, 12000.6)  # 49.8 left: below 50
    assert value(hass, UNITS) == pytest.approx(49.8)
    freezer.tick(timedelta(minutes=5, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    low = [c.data for c in env if c.data["title"] == "Prepaid electricity - running low"]
    assert len(low) == 1 and low[0]["message"].startswith("49.8 kWh left on the prepaid meter")
    for kwh in (12001.0, 12002.0, 12003.0):  # still going down (49.4, 48.4, 47.4): no more warnings
        await reading(hass, kwh)
    assert value(hass, UNITS) == pytest.approx(47.4)
    freezer.tick(timedelta(minutes=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len([c for c in env if c.data["title"] == "Prepaid electricity - running low"]) == 1

    await set_units(hass, 296.5)  # a token loaded: the meter shows 296.5
    recharged = [c.data for c in env if c.data["title"] == "Prepaid electricity - recharged"]
    assert recharged[-1]["message"] == "The units are now 296.5 kWh (+249.1 kWh)."
    await set_units(hass, 50.2)
    await reading(hass, 12003.5)  # below 50 again: a warning again
    freezer.tick(timedelta(minutes=5, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len([c for c in env if c.data["title"] == "Prepaid electricity - running low"]) == 2


async def test_a_correction_down_is_no_recharge_and_the_units_never_go_below_zero(hass, env, freezer):
    await set_units(hass, 0.5)
    assert not [c for c in env if c.data["title"] == "Prepaid electricity - recharged"]
    await reading(hass, 12000.1)
    await reading(hass, 12001.1)
    assert value(hass, UNITS) == 0
    freezer.tick(timedelta(minutes=5, seconds=1))  # the correction took it below 50: one warning
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [c.data["title"] for c in env] == ["Prepaid electricity - running low"]
