# Bilka To Go for Home Assistant

A household shopping list in Home Assistant that feeds [Bilka To Go](https://www.bilkatogo.dk)
orders.

Anyone adds items to the list during the week, usually from a wall display. When the household
decides to order, someone works through the list on a phone. Each item is turned into a
specific Bilka product, chosen with this week's offers in view, and moved into the Bilka
basket. Booking a pickup slot and paying stay in Bilka's own site.

> **Status: early.** You can sign in; the shopping list exists as a to-do list
> (`todo.bilka_to_go_shopping_list`) that keeps the household's rules; and the transfer exists
> as actions (`bilka_togo.get_transfer`, `search`, `move`, `forget`, `empty_basket`,
> `known_items`). The wall display card (`custom:bilka-shopping-list-card`) exists; the
> phone transfer card does not yet.

## Cards

The integration serves its cards itself; no dashboard resource needs adding.

```yaml
type: custom:bilka-shopping-list-card
entity: todo.bilka_to_go_shopping_list
autofocus_hash: "#indkob"   # open the keyboard when this Bubble Card pop-up opens
```

## Install

1. In HACS, open the menu → *Custom repositories*, add `https://github.com/figa12/ha-bilka-togo`
   with the type *Integration*, then download **Bilka To Go**.
2. Restart Home Assistant.
3. *Settings → Devices & services → Add integration → Bilka To Go*, and sign in with the
   household's Bilka To Go account. The account must have a pickup store chosen on
   bilkatogo.dk.

## Unofficial

Bilka publishes no API. This integration uses the same endpoints bilkatogo.dk's own website
uses, so Bilka can change or break them at any time. It signs in as your own Bilka account and
only touches your basket. It never books a slot, checks out or pays.

The keys in `api.py` are the public ones Bilka embeds in its website. Your Bilka email and
password are entered in Home Assistant and are never stored in this repository.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install "pytest-homeassistant-custom-component==0.13.365" \
    "home-assistant-frontend==20260826.7"
.venv/bin/python -m pytest
```

That version of the test harness pins Home Assistant 2026.9.2, the version the household runs.
