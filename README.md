# Home Assistant blueprints for South African solar homes

Automations for a home with a solar inverter and a battery: load shedding, grid outages, a prepaid meter. They come
from a working installation (a Deye/Sunsynk inverter read through Solar Assistant), are tested against Home Assistant's
own test harness, and are written so that they work with any inverter integration that gives a grid voltage.

## Grid outage: one message, loads off and back on, checked

[![Open your Home Assistant instance and show the blueprint import dialog with this blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FPr0t3ct0r%2Fha-sa-solar-blueprints%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsa-solar%2Fgrid_outage.yaml)

When the grid goes:

- **one message** per outage ("Grid off at 18:02 (0 V). Battery 64%. Switched off: Geyser, Pool pump."),
- optionally the heavy loads switched off to save the battery, always or only below a battery level.

When the grid is back:

- one message with how long it was gone,
- the loads switched back on, at once or once the battery has reached a level you choose,
- **each load checked** after a short wait. A Wi-Fi relay that is unreachable after an outage (behind a tripped breaker,
  or still booting) raises no error when it is switched on, so without a check nobody notices it stayed off. The message
  names any load that is not on: "Grid restored - check the loads ... Not on after 30 s: Pool pump. Check them."

Why it is built the way it is:

- It watches the grid **voltage**, not the frequency. A single 0 Hz reading from an inverter monitor has sent "grid
  off" alarms with the grid at 234 V.
- A short wait (15 s by default) before an outage counts, so one bad reading is not an outage. An unavailable sensor is
  not an outage either: the monitor going offline sends nothing.
- A Toggle helper remembers the outage, so a Home Assistant restart or the monitor reconnecting during an outage sends
  nothing twice, and the loads still come back if the grid returned while Home Assistant was down.

### Setup

1. Create a Toggle helper: Settings > Devices & services > Helpers > Create helper > Toggle, named for example
   "Grid outage". Keep it for this automation alone.
2. Import the blueprint (the button above), then create an automation from it.
3. Choose the inverter's grid voltage sensor and the helper. The rest is optional: the battery charge sensor, the loads
   to switch off and on, and where the messages go (notify entities such as email, or a phone's notify action such as
   `notify.mobile_app_my_phone`).

### Inputs

| Input | Default | What it does |
|:--|:--|:--|
| Grid voltage sensor | (required) | The inverter's grid voltage. |
| Outage helper | (required) | The Toggle helper from step 1. |
| Grid off below / for at least | 50 V / 15 s | When the grid counts as gone. |
| Grid back above / for at least | 200 V / 2 min | When it counts as back (a 230 V supply reads about 220 to 245 V). |
| Battery charge sensor | none | Shown in the messages; needed for the two limits below. |
| Switch the loads off only when the battery is below | 100% | 100 switches them off at every outage. |
| Switch the loads back on only when the battery is at least | 0% | The loads wait for the battery when the grid returns lower. |
| Switch off when the grid goes | none | Switches, lights, fans or toggles. |
| Switch on when the grid is back | none | Usually the same; each one is checked. |
| Check the loads after | 30 s | How long a load has to come on. |
| Notify entities / Notify action | none | Where the messages go; both can be used. |

Only list loads in "Switch on when the grid is back" that should run whatever the time of day: a pool pump with its own
daytime schedule is better left to that schedule.

## Tests

`tests/` runs the blueprint in Home Assistant's own test harness
([pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)):

```bash
python -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

## Licence

MIT, see [LICENSE](LICENSE).
