# Signal Messenger UI

A Home Assistant custom integration that sends Signal messages through
[signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api). It is set up
entirely from the UI, with no `configuration.yaml` needed.

It is inspired by the core [Signal Messenger](https://www.home-assistant.io/integrations/signal_messenger)
integration, but adds:

- **Config flow**: enter the REST API URL, then pick the sender account from the registered accounts.
- **Recipients as subentries**: add phone numbers, or pick groups from a list. Each recipient becomes a
  `notify` entity, so it works with `notify.send_message` and the automation editor.
- **Action `signal_messenger_ui.send_message`**: target one or more recipient entities, with an optional title,
  styled text, local file attachments, URL attachments and ad-hoc recipients.

## Installation

1. HACS → ⋮ → *Custom repositories* → add this repository (category *Integration*).
2. Install **Signal Messenger UI** and restart Home Assistant.
3. *Settings → Devices & services → Add integration → Signal Messenger UI*.
4. On the integration page, use **Add recipient** to add phone numbers or groups.

## Usage

```yaml
# Plain text to one or more recipients
action: notify.send_message
target:
  entity_id: notify.family
data:
  title: Doorbell
  message: Someone is at the door

# Styled text with a camera snapshot
action: signal_messenger_ui.send_message
target:
  entity_id: [notify.alice, notify.family]
data:
  title: Alarm
  message: "**Motion** in the _garden_"
  text_mode: styled
  attachments:
    - /config/www/garden.jpg
  urls:
    - http://frigate.local:5000/api/events/123/snapshot.jpg
```

Local files must be in a folder listed in `allowlist_external_dirs` (`/config/www` is
allowed by default). URLs must be listed in `allowlist_external_urls`. Attachments are
limited to 50 MiB each.

Ad-hoc recipients that are not configured as entities can be sent to by passing
`config_entry_id` (the sender account) together with `recipients`.

## Development

```bash
uv venv && uv pip install -r requirements_test.txt
pytest
```
