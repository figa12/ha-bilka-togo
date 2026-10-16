# The shopping list lives in Home Assistant, apart from the Bilka basket

The household's shopping list is kept in Home Assistant and is never the Bilka To Go basket
itself. The two meet only in a transfer, where each item is moved into the basket one at a
time: a product is chosen, added to the basket, and the item leaves the list in the same
step. We chose this over writing additions straight into the basket because the product
behind an item ("mælk", "kød") is chosen fresh for each order from that week's offers. The
list also holds things Bilka will never supply, and the children add to it from the kitchen
display, so nothing should reach a real order without an adult deciding.

## Considered options

- **The basket is the list.** Every addition goes straight into the Bilka basket. It is the
  simplest design, with no transfer step and one source of truth. Rejected because it fixes
  the product when the item is added, before the offers for the actual order are known,
  and it lets anything anyone adds land in the real order.
- **Transfer as one batch with a final confirmation.** Rejected in favour of per-item moves.
  A paused or failed batch leaves an in-between state to recover, while moves keep the list
  and basket in step after every tap and let the minimum-order gap update as you go.

## Consequences

- Home Assistant cannot see Bilka's checkout. So a move counts as done once the line is
  in the basket, not when the order is placed. Previously chosen therefore records choices,
  not purchases.
- The basket can also be changed from Bilka's own app. A transfer adds to whatever is
  already there (increasing counts) rather than replacing it.
