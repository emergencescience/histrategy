# Schema Reference

Field format specifications for 三國志略 knowledge base data files. See `schema.json` for machine-readable definitions.

---

## Character (`characters.json`)

| # | Field | Type | Required | Constraints |
|---|-------|------|----------|-------------|
| 1 | `id` | `string` | yes | snake_case, unique across all characters |
| 2 | `name` | `string` | yes | Full Chinese name |
| 3 | `alias` | `string` | yes | Courtesy name (字). Empty string `""` if unknown |
| 4 | `title` | `string` | yes | Display title, typically same as `name` |
| 5 | `faction` | `string` | yes | Must match an `id` in `factions.json` |
| 6 | `birth` | `int \| null` | no | Birth year. `null` if unknown |
| 7 | `death` | `int \| null` | no | Death year. `null` if unknown |
| 8 | `personality` | `string[]` | yes | Chinese trait phrases. Non-empty for named characters |
| 9 | `skills` | `string[]` | yes | Abilities: `统帅`, `谋略`, `武艺`, `内政`, etc. |
| 10 | `description` | `string` | yes | Short biography (1–2 sentences) |

Example:
```json
{
  "id": "caocao",
  "name": "曹操",
  "alias": "孟德",
  "title": "曹操",
  "faction": "cao",
  "birth": 155,
  "death": 220,
  "personality": ["雄才大略", "多疑", "用人唯才"],
  "skills": ["统帅", "谋略", "政治", "文学"],
  "description": "东汉末年杰出的政治家、军事家、文学家。"
}
```

---

## Faction (`factions.json`)

| # | Field | Type | Required | Constraints |
|---|-------|------|----------|-------------|
| 1 | `id` | `string` | yes | snake_case, unique across all factions |
| 2 | `name` | `string` | yes | Display name, usually `{ruler}军` |
| 3 | `ruler_id` | `string \| null` | yes | Must match a character `id`. `null` for generic factions |
| 4 | `color` | `string` | yes | Enum: `red` `blue` `yellow` `green` `cyan` `magenta` `white` `grey` |
| 5 | `description` | `string` | yes | Flavor text (1 sentence) |
| 6 | `capital` | `string` | yes | Region ID of capital. `""` for generic factions |
| 7 | `starting_territories` | `string[]` | yes | Region IDs. Each must match a region `id` |
| 8 | `strength` | `int` | yes | Military strength (troop count). Min 0 |
| 9 | `economy` | `int` | yes | Economy rating. Range 0–100 |
| 10 | `morale` | `int` | yes | Morale rating. Range 0–100 |
| 11 | `intel_level` | `int` | yes | Intelligence/info rating. Range 0–100 |
| 12 | `aggression` | `int` | yes | Aggression tendency. Range 0–100 |
| 13 | `diplomacy_tendency` | `string` | yes | Enum: `hostile` `neutral` `calculating` `friendly` `pragmatic` `arrogant` `defensive` |

Example:
```json
{
  "id": "cao",
  "name": "曹操军",
  "ruler_id": "caocao",
  "color": "yellow",
  "description": "乱世奸雄，奉天子以令不臣",
  "capital": "xuchang",
  "starting_territories": ["yanzhou"],
  "strength": 30000,
  "economy": 55,
  "morale": 75,
  "intel_level": 80,
  "aggression": 70,
  "diplomacy_tendency": "calculating"
}
```

---

## Region (`regions.json`)

| # | Field | Type | Required | Constraints |
|---|-------|------|----------|-------------|
| 1 | `id` | `string` | yes | snake_case, unique across all regions |
| 2 | `name` | `string` | yes | Chinese region name |
| 3 | `capital` | `string` | yes | Capital city name |
| 4 | `description` | `string` | yes | Flavor text (1 sentence) |
| 5 | `owner_190` | `string` | no | Faction ID owning this region in the 190 scenario |
| 6 | `strategic_value` | `int` | yes | Strategic importance. Range 0–100 |
| 7 | `resources` | `string[]` | yes | Natural resources: `粮食`, `铁`, `马`, `盐`, `丝绸`, etc. |
| 8 | `neighbors` | `string[]` | yes | Adjacent region IDs. Each must match a region `id` |

Example:
```json
{
  "id": "sili",
  "name": "司隶",
  "capital": "洛阳",
  "description": "天子脚下，中原腹地",
  "owner_190": "dongzhuo",
  "strategic_value": 95,
  "resources": ["粮食", "人口"],
  "neighbors": ["兖州", "豫州", "荆州", "雍州"]
}
```

---

## HistoricalEvent (`events.json`)

| # | Field | Type | Required | Constraints |
|---|-------|------|----------|-------------|
| 1 | `year` | `int` | yes | Year the event occurs |
| 2 | `season` | `string` | yes | Enum: `spring` `summer` `autumn` `winter` |
| 3 | `title` | `string` | yes | Display title |
| 4 | `description` | `string` | yes | Narrative text |
| 5 | `trigger` | `string` | yes | Trigger ID: `game_start`, `time_<year>_<season>`, or event name |
| 6 | `effects` | `object` | yes | Key-value state flags. Values are typically `bool` |
| 7 | `is_historical` | `bool` | yes | `true` for scripted events, `false` for dynamic |

Example:
```json
{
  "year": 190,
  "season": "spring",
  "title": "讨董联盟成立",
  "description": "曹操发矫诏，号召天下诸侯共讨董卓。",
  "trigger": "game_start",
  "effects": {"alliance_against_dongzhuo": true},
  "is_historical": true
}
```

---

## ID Naming Convention

- **snake_case**: lowercase, underscores between words (`caocao`, `liu_biao`, `guan_yu`)
- No spaces, no special characters, no leading/trailing underscores
- Keep IDs consistent across files — the same entity uses the same ID everywhere
- Chinese names are romanized in pinyin (e.g. `xuchang` not `许昌`)

## Validation

Run before submitting changes:

```
python histrategy/knowledge/scripts/validate_data.py
```

The game also validates data on load and emits warnings for any issues found.
