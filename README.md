# Brunner Fenix Bridge

A small Windows app that makes Brunner force-feedback rudder pedals behave like the real Airbus in the **Fenix A320 for MSFS 2024**:

- The pedals physically move with rudder trim, from the RUD TRIM knob, the RESET button or the autopilot, as they do in the aircraft.
- Small autopilot trim adjustments are ignored, so the pedals stay still in normal AP flight.
- Your pedal input is sent relative to the trimmed pedal position, so trim is never counted twice.

It's the MSFS counterpart of [brunner-toliss-pedals](https://github.com/Soarbywire/brunner-toliss-pedals) for X-Plane.

## How it works

The Fenix doesn't use MSFS's standard rudder trim, so SimUX's built-in trim following does nothing. The Fenix does animate its cockpit pedals with `L:N_FC_RUDDER`, which holds trim plus pilot input (about ±1000 at full pedal, 33.3 per degree). The bridge separates the two:

| Step | Who | What |
|---|---|---|
| 1 | SimUX | Publishes the physical pedal position to `L:BRUNNER_RAW_PEDAL` |
| 2 | Bridge | Reads that and `L:N_FC_RUDDER`, and works out the Fenix rudder trim |
| 3 | Bridge | Writes the trim to `L:BRUNNER_RUDDER_TRIM`, and sends your input relative to the trim to MSFS as rudder |
| 4 | SimUX | Reads `L:BRUNNER_RUDDER_TRIM` as the rudder trim position, and the pedals move |

## Requirements

- Windows 10/11 and MSFS 2024 (MSFS 2020 should also work)
- Fenix A320 (V3)
- Brunner rudder pedals with SimUX

## Installation

1. Download `BrunnerFenixBridge.exe` from the [latest release](https://github.com/Soarbywire/brunner-fenix-bridge/releases/latest).
2. Put it anywhere you like, for example `Documents\BrunnerFenixBridge`, and run it. It connects to MSFS automatically, whether it's started before or after the sim.

Windows may warn that the app is from an unknown publisher. Click **More info > Run anyway**. Some antivirus programs flag apps packaged this way by mistake. The full source code is here, and every release is built automatically by GitHub from this source.

The app checks for updates when it starts. When a new version is available, a banner appears. Click **Install** and it downloads, verifies and restarts itself.

## Required SimUX settings

Use these in the SimUX profile you fly the Fenix with. **Restart SimUX after changing mappings.** SimUX only picks up new L:var mappings after a restart.

### 1. Rudder deadzone: 0.0%

Any deadzone stops the pedals reporting their true position near centre. The bridge reads the gap as rudder input and the pedals creep under autopilot.

### 2. Trim settings

In **Rudder > List of Effects > Trim**, enable the Trim effect and set:

| Setting | Value |
|---|---|
| Read trim from simulation | On |
| Write trim to simulation | **Off** |
| Write trim to device | On |

### 3. Mappings

Turn on **Show Advanced Settings** at the bottom of the screen and open the mappings.

**Input Mappings:** edit the mapping used by the rudder trim behaviour (`controls/rudder/trim/position`), or add one:

| Field | Value |
|---|---|
| SimVar | `L:BRUNNER_RUDDER_TRIM` |
| SimVar Datatype | FloatDouble |
| SimVar Unit | Ratio Signed |
| SimData Key | `controls/rudder/trim/position` |

**Output Mappings:** edit the mapping for the rudder actuator position (`controls/rudder/position`) so it publishes to the bridge instead of to MSFS:

| Field | Value |
|---|---|
| SimVar | `L:BRUNNER_RAW_PEDAL` |
| SimVar Datatype | FloatDouble |
| SimVar Unit | Ratio Signed |
| SimData Key | `controls/rudder/position` |

Click **Apply & Save**, then restart SimUX.

### 4. Only the bridge sends rudder to MSFS

The bridge sends rudder input itself. Make sure nothing else does while you fly the Fenix:

- No other SimUX output mapping writes rudder position to MSFS.
- In MSFS **Controls**, the Brunner pedals (and any vJoy device) have **no rudder axis** assigned.

Note: the bridge needs to be running for rudder to work in the Fenix.

## The status window

| Line | Meaning |
|---|---|
| MSFS | Connection status |
| Aircraft | The loaded aircraft. The bridge is active when it contains "FNX" or "Fenix". |
| Mode | **Active** in the Fenix, otherwise **Idle** (or **Passthrough**, see settings) |
| Fenix rudder trim | The trim the bridge has worked out, like the pedestal display (e.g. "L 5.0") |
| Fenix pedals | Raw `L:N_FC_RUDDER` |
| Trim to pedals | Position sent to SimUX |
| Pedal position | Physical pedal position from SimUX |
| Rudder to MSFS | Your input relative to trim |

### First flight check

With the Fenix loaded and your feet off the pedals:

1. **Fenix rudder trim** shows 0.0 and **Rudder to MSFS** stays at +0.0000.
2. Turn RUD TRIM to L 5. The trim line follows the pedestal display, the pedals glide left, and **Rudder to MSFS** returns to +0.0000.
3. Press RESET. The pedals return to centre.
4. Press a pedal. **Rudder to MSFS** follows, and the trim line doesn't change.

If pressing the right pedal makes **Fenix pedals** go negative (left rudder), flip `invert_rudder_output`. If the pedals move the wrong way when you trim, set `invert_pedal` to `true` (see below).

## Settings

Click **Edit settings** to open `%APPDATA%\BrunnerFenixBridge\settings.json` in Notepad, save it, then click **Reload settings**.

| Setting | Default | What it does |
|---|---|---|
| `fenix_rudder_lvar` | `L:N_FC_RUDDER` | Fenix pedal animation variable |
| `pedal_lvar` | `L:BRUNNER_RAW_PEDAL` | Pedal position published by SimUX |
| `trim_lvar` | `L:BRUNNER_RUDDER_TRIM` | Trim position read by SimUX |
| `aircraft_match` | `["FNX", "Fenix"]` | The bridge is active when the aircraft path contains one of these |
| `force_active` | `false` | Act as if a Fenix is always loaded |
| `passthrough_other_aircraft` | `false` | In other aircraft, send the pedals straight through as rudder. Leave off if SimUX handles rudder in other aircraft. |
| `invert_pedal` | `false` | Flip the pedal direction, if SimUX's is opposite to the Fenix's |
| `invert_rudder_output` | `true` | Flip the rudder sent to MSFS. MSFS's rudder command runs opposite to the Fenix, so this is on by default. |
| `hw_scale` | `1.0` | Trim units to pedal units. Adjust if the pedals settle short of or past the trim position. |
| `trim_friction` | `0.013` | Trim change (about 0.4°) before the pedals start to move |
| `settle_time` | `0.5` | Seconds the trim must be still before the friction locks in again |
| `trim_slew_rate` | `0.10` | Maximum pedal speed when following trim |
| `rest_deadband` | `0.015` | Rudder deadband when the pedals are settled. Raise to 0.03 if you get phantom rudder. |
| `motion_deadband` | `0.10` | Rudder deadband while the motor is moving the pedals |
| `check_updates_on_start` | `true` | Check GitHub for a new version at start-up |

The log is at `%APPDATA%\BrunnerFenixBridge\bridge.log`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| "Waiting for MSFS..." | MSFS isn't running yet, or the sim is still loading. |
| Mode stays Idle in the Fenix | The aircraft path doesn't contain "FNX" or "Fenix". Add part of the path shown to `aircraft_match`, or set `force_active` to `true`. |
| Pedal position stays at 0.0000 | SimUX isn't publishing `L:BRUNNER_RAW_PEDAL`. Check the output mapping and restart SimUX. |
| Trim line changes but the pedals don't move | SimUX isn't reading `L:BRUNNER_RUDDER_TRIM`. Check the input mapping, trim settings, and restart SimUX. |
| No rudder at all | The bridge isn't running, or the mode isn't Active. |
| Rudder doubled or fighting | Something else is also sending rudder to MSFS. See section 4. |
| Pedals twitch under AP | SimUX deadzone isn't 0%, or raise `rest_deadband`. |

## Building from source

Python 3.12 on Windows:

```
pip install pyinstaller
python -m unittest discover -s tests
pyinstaller --onefile --windowed --name BrunnerFenixBridge --add-binary "SimConnect.dll;." main.py
```

`SimConnect.dll` comes from the MSFS SDK. The build workflow takes it from the [SimConnect](https://pypi.org/project/SimConnect/) package on PyPI. You can also run `python main.py` directly with `SimConnect.dll` next to it.

## Releasing a new version

Publish a release on GitHub with a new tag such as `v1.1.0` (or push the tag). The **Build** workflow runs the tests, builds `BrunnerFenixBridge.exe`, and attaches it and its checksum to the release. Installed copies will then offer the update.

## License

MIT. See [LICENSE](LICENSE). `SimConnect.dll` is Microsoft's, part of the MSFS SDK.
