# Bilka To Go for Home Assistant

A household shopping list in Home Assistant that feeds [Bilka To Go](https://www.bilkatogo.dk)
orders.

Anyone adds items to the list during the week, usually from a wall display. When the household
decides to order, someone works through the list on a phone. Each item is turned into a
specific Bilka product, chosen with this week's offers in view, and moved into the Bilka
basket. Booking a pickup slot and paying stay in Bilka's own site.

> **Status: early.** Only the Bilka client exists so far: login, product search with
> per-store offers, and reading and changing the basket. The shopping list, setup flow and
> cards are not built yet.

## Unofficial

Bilka publishes no API. This integration uses the same endpoints bilkatogo.dk's own website
uses, so Bilka can change or break them at any time. It signs in as your own Bilka account and
only touches your basket. It never books a slot, checks out or pays.

The keys in `api.py` are the public ones Bilka embeds in its website. Your Bilka email and
password are entered in Home Assistant and are never stored in this repository.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install "aiohttp==3.14.3" pytest pytest-asyncio
.venv/bin/python -m pytest
```

The aiohttp version matches the one Home Assistant 2026.9 ships.
