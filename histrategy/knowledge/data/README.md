# Knowledge Base Data

This directory contains the historical knowledge base for 三國志略 (histrategy). Each JSON file holds structured data about the Three Kingdoms period that drives the game simulation.

## File Overview

| File | Description |
|---|---|
| `characters.json` | Historical figures — their traits, skills, and faction affiliations |
| `factions.json` | Warlord factions — military strength, economy, diplomacy posture |
| `regions.json` | Geographic regions — capitals, resources, neighbors, ownership |
| `events.json` | Historical events — scripted timeline events with triggers and effects |
| `schema.json` | JSON Schema definitions for all data files (see below) |

## Schema

`schema.json` defines the exact format for each data file. Use it as the authoritative reference when adding or editing data. Each definition includes field types, required fields, allowed values, and descriptions.

## Field Reference

### characters.json — `Character`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | Unique snake_case identifier (e.g. `"caocao"`, `"guan_yu"`) |
| `name` | string | yes | Full Chinese name (e.g. `"曹操"`) |
| `alias` | string | yes | Courtesy name / 字 (e.g. `"孟德"`). Use `""` if unknown. |
| `title` | string | yes | Display title |
| `faction` | string | yes | Faction ID from factions.json |
| `birth` | int or null | no | Birth year. `null` if unknown. |
| `death` | int or null | no | Death year. `null` if unknown. |
| `personality` | string[] | yes | Chinese trait phrases used by the simulation engine |
| `skills` | string[] | yes | Abilities (e.g. `"统帅"`, `"谋略"`, `"武艺"`) |
| `description` | string | yes | Character biography |

### factions.json — `Faction`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | Unique snake_case identifier (e.g. `"cao"`, `"yuan_shao"`) |
| `name` | string | yes | Display name (e.g. `"曹操军"`) |
| `ruler_id` | string or null | yes | Character ID of the ruler. `null` for "other" factions. |
| `color` | string | yes | One of: `red`, `blue`, `yellow`, `green`, `cyan`, `magenta`, `white`, `grey` |
| `description` | string | yes | Faction flavor text |
| `capital` | string | yes | Capital region ID. `""` for "other" factions. |
| `starting_territories` | string[] | yes | Region IDs controlled at game start |
| `strength` | int | yes | Military strength (troop count). Minimum 0. |
| `economy` | int | yes | Economy rating (0–100) |
| `morale` | int | yes | Morale rating (0–100) |
| `intel_level` | int | yes | Intelligence/information rating (0–100) |
| `aggression` | int | yes | Aggression tendency (0–100). Higher = more likely to attack. |
| `diplomacy_tendency` | string | yes | AI stance: `hostile`, `neutral`, `calculating`, `friendly`, `pragmatic`, `arrogant`, `defensive` |

### regions.json — `Region`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | Unique snake_case identifier (e.g. `"sili"`, `"jizhou"`) |
| `name` | string | yes | Chinese region name (e.g. `"司隶"`) |
| `capital` | string | yes | Capital city name |
| `description` | string | yes | Region flavor text |
| `owner_190` | string | no | Faction ID owning this region in the 190 scenario |
| `strategic_value` | int | yes | Strategic importance (0–100) |
| `resources` | string[] | yes | Natural resources (e.g. `"粮食"`, `"铁"`, `"马"`) |
| `neighbors` | string[] | yes | Adjacent region IDs |

### events.json — `HistoricalEvent`

| Field | Type | Required | Description |
|---|---|---|---|
| `year` | int | yes | Year the event occurs |
| `season` | string | yes | One of: `spring`, `summer`, `autumn`, `winter` |
| `title` | string | yes | Event title (displayed in-game) |
| `description` | string | yes | Event narrative |
| `trigger` | string | yes | Trigger identifier (e.g. `"game_start"`, `"time_190_summer"`) |
| `effects` | object | yes | State effects as key-value flags |
| `is_historical` | boolean | yes | `true` for historical events, `false` for dynamic ones |

## Multi-Era Structure

Scenario-specific data lives in numbered subdirectories:

```
data/
  characters.json      # Current active data (backward compatible)
  factions.json
  regions.json
  events.json
  schema.json          # Schema definitions
  190/                 # 190 AD scenario data
    characters.json
    factions.json
    regions.json
    events.json
```

When adding a new scenario (e.g. 208 AD / Red Cliffs), create a `data/208/` directory with the same four files.

## How to Contribute

1. Read `schema.json` to understand the expected format for the file you're editing.
2. Make your changes to the appropriate JSON file.
3. Run the validation script:
   ```
   python histrategy/knowledge/scripts/validate_data.py
   ```
4. Fix any validation errors before submitting.
5. Ensure IDs are consistent across files — character `faction` values must match faction `id` values; faction `ruler_id` values must match character `id` values; region `neighbors` and `starting_territories` must reference valid region IDs.

## ID Naming Convention

- Use **snake_case** for all IDs (e.g. `"caocao"`, `"liu_biao"`, `"guan_yu"`)
- No spaces, no special characters
- Keep names consistent: the same character/faction/region should use the same ID everywhere
