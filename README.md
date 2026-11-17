# Bulgaria power outages

Home Assistant custom integration that reports power outages announced by the Bulgarian
electricity distribution operators, for a place or (ЕРМ Запад only) for a client number.

| operator | area | by client number | planned by place | unplanned by place |
|---|---|---|---|---|
| ЕРМ Запад (Electrohold) | western Bulgaria | yes, incl. unplanned | yes | yes, if the municipality is given |
| Електроразпределение Юг (EVN) | south-eastern Bulgaria | — | yes | yes |
| Електроразпределение Север (Energo-Pro) | north-eastern Bulgaria | — | yes | — |

Sources:

- **ЕРМ Запад** – <https://info.ermzapad.bg/webint/vok/avplan.php>: the per-client check
  (`?BBKING=FYI`), the daily PDFs "Планирани прекъсвания за DD.MM.YYYY" (`?PLAN=FYI`, usually
  published about two days ahead) and the map of outages registered right now.
- **Електроразпределение Юг** – the planned outage pages per province behind
  <https://www.elyug.bg/Customers/Planned_shutdowns.aspx> and the unplanned outage page
  <https://www.elyug.bg/Customers/Unscheduled-power-cuts.aspx>.
- **Електроразпределение Север** – the planned outage list per province behind
  <https://www.erpsever.bg/bg/prekysvanija>. Its unplanned outages and check by client number need
  a login and are not used.

The endpoints are undocumented and may change without notice. The small operator ЕРП Златни
пясъци is not covered.

## Installation

### HACS

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=wildsystems&repository=ws-bg-power-outages&category=integration)

Or manually: HACS → ⋮ → **Custom repositories** → repository
`https://github.com/wildsystems/ws-bg-power-outages`, type **Integration**. Then download
**Bulgaria power outages** and restart Home Assistant.

### Manual

Copy `custom_components/bg_power_outages/` to `<config>/custom_components/` and restart Home
Assistant.

Requires Home Assistant 2026.3 or newer. No Python packages are required; pages and PDFs are
parsed with the standard library.

The integration brings its own icon for Home Assistant (2026.3+). The HACS dashboard may still
show a placeholder icon, as HACS does not read bundled icons yet.

### Upgrading from ERM Zapad power outages (0.1.x)

The integration was renamed from `erm_zapad_outages` to `bg_power_outages`, and Home Assistant
treats it as a new integration. Delete the old entries, remove the old integration, install 0.2.0
and add the entries again with the same values; the entity IDs then stay the same. Do not just
press **Update** in HACS, as that leaves the old integration installed. Then replace the alert
blueprint. The steps are in [docs/upgrade-0.2.md](docs/upgrade-0.2.md), and the changes in
[CHANGELOG.md](CHANGELOG.md).

## Configuration

[![Add the integration to your Home Assistant instance.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=bg_power_outages)

Settings → Devices & services → Add integration → **Bulgaria power outages**, then choose the
operator. Add one entry per client number or place; any number of entries of any operator can
coexist.

### ЕРМ Запад

Choose **By client number** or **By place**.

| mode | field | example | meaning |
|---|---|---|---|
| client number | Client number | `300000000000` | 12 digits from the electricity bill. The address of its metering points, with the number masked, becomes the device name, e.g. `Златуша (…0000)` |
| place | Place | `ЗЛАТУША` | place name as written in the schedules; case-insensitive substring match |
| place | Municipality / Sofia district | `БОЖУРИЩЕ` | optional; narrows the match when the name exists in several municipalities. For Sofia it is the district (`ВРЪБНИЦА`, `ОВЧА КУПЕЛ`). Needed for unplanned outages by place |

### Електроразпределение Юг and Електроразпределение Север

| field | example | meaning |
|---|---|---|
| Province | `Бургас` | chosen from the list |
| Place | `СОЗОПОЛ` | case-insensitive substring of the published description of the affected area, usually the town or village name |
| Street or quarter | `ОДЕСА` | optional; must also appear in the description. Leave empty to be told about every outage in the place |

These operators publish free text ("гр. Созопол - ул. Одеса, ул. Републиканска …"), so the match
is a plain text search. A short or common word matches more than intended; a street name that the
operator writes differently ("ул. Ал. Стамболийски") is missed.

Any entry can be changed later with **Reconfigure** (same operator and mode). A device name you
have changed is kept; entity IDs do not change.

## Entities (per entry)

| entity | state | attributes |
|---|---|---|
| `calendar.<name>_planned_outages` | on while the current or next outage lasts (see [Calendar events](#calendar-events)) | `message`, `description`, `location`, `start_time`, `end_time` of that outage |
| `binary_sensor.<name>_outage_now` | on while an outage is in progress (see below) | `kind`, `start`, `expected_end`, `point` or `place` |
| `binary_sensor.<name>_outage_tomorrow` | on if an outage is scheduled tomorrow | `outages` |
| `sensor.<name>_next_outage` | time window of the next or current outage, e.g. `13.11 07:00–17:00`; `?` for an unknown end; `—` if none | the outage's fields, `upcoming` |
| `sensor.<name>_next_outage_start` | start of the next or current outage (timestamp) | |
| `sensor.<name>_next_outage_end` | end of the next or current outage (timestamp); unknown if not announced | |
| `event.<name>_new_outage_published` | time of the last event, fired when a new or changed planned outage appears | `event_type: published`, `outages` |

Every entry has all of these entities except `outage_now`. The table shows which entries have
`outage_now`, which outages they show and how often they are checked:

| entry | `outage_now` | outages shown | checked every |
|---|---|---|---|
| ЕРМ Запад, by client number | yes | planned (known 48 hours ahead), unplanned | 30 min; planned 3 h |
| ЕРМ Запад, by place with municipality | yes | planned, unplanned | 30 min; planned 3 h |
| ЕРМ Запад, by place without municipality | — | planned | 3 h |
| Електроразпределение Юг | yes | planned, unplanned | 30 min; planned 3 h |
| Електроразпределение Север | — | planned, possible | 3 h |

`outage_now` exists only where the operator reports outages registered right now. By client number
it is on while ЕРМ Запад has an outage registered for it, planned or unplanned. By place it is on
while an unplanned outage matching the place is registered, or while the time window of a matching
planned outage lasts. The other entries have no `outage_now`, because a planned schedule alone does
not say whether the power is off.

Each outage is `{place, district, oblast, start, end, kind}` with ISO 8601 times (Europe/Sofia);
client-number outages add `point` (metering point) and have empty `district`/`oblast`. For
Електроразпределение Юг and Север, `place` is the published description of the affected area and
`oblast` the province. `end` is null when no restore time is announced. `kind` is one of:

- `planned` – announced planned outage;
- `unplanned` – unplanned (emergency) outage registered right now. Електроразпределение Юг gives
  only the date, so such an outage starts at midnight of that day, usually without an end;
- `possible` – Електроразпределение Север announces switching during which the supply "may be
  disturbed" ("възможни смущения"). Shown in the calendar and the sensors, but not counted by
  `outage_now`.

A published period with daily hours ("16.11–20.11, 09:00–17:00") becomes one outage per day, for
at most 31 days.

The `upcoming` and `outages` lists hold at most 20 outages. They and `point` are not stored in the
recorder history, but they are in the state, so triggers and templates can read them.

### Calendar events

Each outage becomes one event:

| field | content |
|---|---|
| `summary` | `Планирано прекъсване на тока`, `Непланирано прекъсване на тока` or `Възможни смущения в захранването` (by `kind`), then ` – ` and the place, cut to 60 characters |
| `description` | by client number: `Точка на измерване <point>.`; by place: the full place or area description, a note that the outage may affect only part of it, and the operator's name and page. Without an announced end, `Очакваното време за възстановяване не е обявено.` is added |
| `location` | by client number: the address of the metering points; by place: the place (cut to 60 characters), `общ. <municipality>` and `обл. <province>` when known |
| `start` | start of the outage |
| `end` | the announced end. Without one, a placeholder: one hour after the start or, once the start has passed, one hour from now, so it keeps moving forward |

Because of this placeholder:

- the calendar stays on until the operator stops listing an outage without an announced end;
- a calendar trigger with `event: end` does not fire for such an outage. Its end is always ahead,
  and once the operator stops listing the outage, its event is removed. Use `outage_now`;
- when a restore time is announced, the event ends at that time.

A calendar trigger with `event: start` fires only for outages that are known before they start, so
not for unplanned ones: they are registered after they begin, and Електроразпределение Юг dates
them from midnight. The kind can be checked in the summary, e.g.
`trigger.calendar_event.summary.startswith('Планирано')`.

### Next outage sensors

`next_outage`, `next_outage_start` and `next_outage_end` show the outage with the earliest start
among those that have not ended yet, meaning their end is in the future or not announced. In
practice:

- During an outage they show that outage until its announced end. Within a minute after that end
  they switch to the following outage, without waiting for a refresh. They use the announced end,
  not the actual restore, which the integration cannot see.
- An outage without an announced end stays until the operator no longer lists it. For unplanned
  outages this is noticed at the next 30-minute check.
- When the operator announces or changes the restore time of a listed outage, `next_outage_end`
  changes from unknown to that time, or to the new time, at the next check: within 30 minutes for
  outages registered right now, within 3 hours for planned ones. Електроразпределение Юг has so far
  not been seen announcing it for unplanned outages.
- `next_outage_end` is unknown both when there is no outage and when the end is not announced.
  To tell the two apart, check `next_outage_start` (unknown only when there is no outage) or
  `next_outage` (`—` when there is no outage).

### New outage event

The event entity has one event type, `published`. It fires when a refresh finds planned outages
that were not in the previous successful refresh, and its `outages` attribute lists them. The
entity's state is the time of the last event. `event_type` and `outages` are attributes of that
state, so a state trigger reads them as `trigger.to_state.attributes.outages`.

- An outage counts as new if any of its fields differs from the previous refresh. So a known
  outage with a new start, end or description fires the event again, and only its new version is
  listed. A cancelled outage just disappears, and no event is fired for it.
- The first successful refresh after Home Assistant starts, or after the entry is reloaded or
  reconfigured, only records what is published; no event is fired for those outages.
- Unplanned outages do not fire it (use `outage_now`). `possible` outages (Електроразпределение
  Север) do.
- Like every event entity, it restores its last event (time and attributes) after a restart or a
  reload. Its state then changes from `unavailable` to the time of that old event, and the same
  happens when it becomes available again after failed refreshes. A state trigger fires on such a
  change, so check that the event is recent rather than excluding `unavailable` (a new event can
  arrive just as the entity becomes available again) or `unknown` (the state before the very first
  event); see the [example](docs/automations.md#new-outage-published).

### Availability

When a refresh fails, the entities keep showing the last data for up to 12 hours and then become
unavailable. `outage_now` is the exception: it is unavailable as soon as a check fails, because
an old answer says nothing about the power right now.

So an outage can end as `on → unavailable → off`, and an outage that ends while Home Assistant
restarts gives no `on → off` either. A trigger `from: "on"` `to: "off"` misses these. Dropping
`from` does not help, because `off → unavailable → off` would then look like a restore. The
[example](docs/automations.md#outage-started-or-ended) keeps the last known state in a template
binary sensor.

### Times and time zones

- Times in attributes (`start`, `end`, `expected_end` and the items of `outages` and `upcoming`)
  are ISO 8601 strings in Europe/Sofia time with its offset, e.g. `2026-11-13T07:00:00+02:00`.
  `as_datetime()` keeps the offset, so `strftime()` shows Sofia time; add `| as_local` to show
  them in Home Assistant's time zone when it is not Europe/Sofia.
- The states of `next_outage_start`, `next_outage_end` and the event entity are timestamps. Home
  Assistant keeps them in UTC, e.g. `2026-11-13T05:00:00+00:00`. Dashboards show them in local
  time, but in templates convert them:
  `states('sensor.<name>_next_outage_start') | as_datetime | as_local`.
- The `next_outage` text (`13.11 07:00–17:00`) is in Sofia time.
- Comparisons such as `now() < as_datetime(...)` are correct in any time zone.

## Polling and request limits

All entries of one operator share one client that sends one request at a time; entries asking for
the same data within 10 minutes share one download. Entries with `outage_now` check it every 30
minutes and the planned outages every 3 hours; other entries are refreshed every 3 hours.

- **ЕРМ Запад** refuses requests ("tomuch") above roughly 100 per period; the period and whether it
  is per IP are not known.
  - By client number: the registered outage every 30 minutes, the planned outages for the next
    48 hours every 3 hours (56 requests a day per number).
  - By place: every 3 hours one request for the list plus one per published day (usually 3–4 in
    total). With a municipality, also every 30 minutes the list of municipalities with an outage
    right now and, when the municipality is in it, its outage map (up to 3 matching
    municipalities).
  Many ЕРМ Запад entries can reach the limit; after a "tomuch" refusal no request at all is sent
  to ЕРМ Запад for one hour.
- **Електроразпределение Юг**: one request per province every 3 hours for the planned outages and
  two (page and province selection) every 30 minutes for the unplanned ones.
- **Електроразпределение Север**: one request per province every 3 hours.

An HTTP 429 answer from any operator also stops requests to it for one hour.

## Alert blueprint

`blueprints/automation/bg_power_outages/outage_alert.yaml` notifies when a new outage is published
and again at a chosen evening time (default 19:00) before the outage day. The title names the
operator and the device (place or address); long area descriptions are shortened. HACS installs
only the integration; import the blueprint separately:

[![Open your Home Assistant instance and show the blueprint import dialog.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fwildsystems%2Fws-bg-power-outages%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fbg_power_outages%2Foutage_alert.yaml)

Then create an automation from it and set the notification actions, using `{{ title }}` and
`{{ message }}`:

```yaml
- action: notify.mobile_app_phone
  data:
    title: "{{ title }}"
    message: "{{ message }}"
```

[docs/automations.md](docs/automations.md) has YAML examples that you can copy and adapt: a new
outage is published, an outage starts or ends, a restore time is announced, and a reminder from
the calendar.

## Limitations

- By place the operators name places or areas, not addresses, so an entry means "part of the
  place". ЕРМ Запад schedule times can differ from its per-client data (seen: schedule
  07:00–17:00, client number 09:15–17:00).
- ЕРМ Запад by client number: planned outages are known only 48 hours ahead. Metering points
  (`32Z…`) are not accepted, because the site's planned check by metering point ignores the point.
  The format of the planned (48 h) answer that lists outages has not been observed yet.
- Електроразпределение Север: no unplanned outages (they need a login).
- Електроразпределение Юг: unplanned outages carry a date but no time.
- If an answer is not recognised, a repair issue "<operator> answer not understood" appears under
  Settings → System → Repairs with the text received. Please report it (see below).
- Planned works can be cancelled; a cancelled outage simply disappears from the calendar.

## Reporting problems

Open an issue at <https://github.com/wildsystems/ws-bg-power-outages/issues> with the log lines
or the repair issue text. Client numbers and metering points are hidden in these texts, but
answers from the operators can contain your address: remove it, and any other personal data,
before posting.

## Development

Lint and type settings are in `pyproject.toml`: `ruff check .`, `ruff format --check .`, and
`mypy bg_power_outages` from `custom_components/` with Home Assistant installed. GitHub Actions
run ruff, hassfest and the HACS validation.
