# Groceries

How the household collects what it needs during the week and turns it into a Bilka To Go
order for pickup.

## Language

**Shopping list**:
The household's single running list of everything it needs to buy, wherever it will be
bought, and anyone can add to it at any time. It lives in Home Assistant and is never the
Bilka basket itself. Items that a transfer cannot place in the basket stay on it.
_Avoid_: basket, cart, indkøbskurv

**Item**:
One entry on the shopping list, naming what is wanted rather than which product ("mælk",
"kød, 2 aftener"). It is never tied to a product while on the list; the product is chosen at
transfer, when the current offers are known. Two items are the same item when their names
match, ignoring capitals and surrounding spaces, so the list never holds the same item twice.
_Avoid_: line, product, need, entry

**Amount**:
An optional free-text hint on an item about how much is wanted ("2", "6 l", "ekstra til
fredag"). It is kept apart from the item's name and guides the transfer, where the basket
count is actually set.
_Avoid_: quantity, count, note

**Known item**:
An item name that has had a product chosen for it in at least one transfer. Only known items
are offered as suggestions when adding to the shopping list. A name stops being a known item
only when someone deliberately forgets it, which forgets its previously chosen products too;
it becomes known again the next time a product is chosen for it.
_Avoid_: saved item, favourite, suggestion

**Previously chosen**:
The Bilka products the household has picked for an item in earlier transfers. It is a set
that grows over time, never a single fixed product, and says nothing about whether the order
was in the end placed. A product leaves the set only when someone deliberately forgets it for
that item; products Bilka no longer sells are hidden from it.
_Avoid_: previously ordered, usual product, favourite, accepted products

**Preference order**:
The one household rule for which of an item's previously chosen products are shown first
during a transfer: organic with a price cut, then any price cut, then organic, then the
rest, cheapest per unit within each group. It orders the choice and never removes options.
It does not apply to searching Bilka for something new, which keeps Bilka's own order.
_Avoid_: ranking, sort order, priority

**Basket**:
The Bilka To Go basket on the household's Bilka account. It holds specific products with
quantities, plus Bilka's own service lines (such as the packing choice), which transfers
never touch and which do not count as items.
_Avoid_: cart, kurv, shopping list

**Transfer**:
The deliberate session, when the household decides to make an order, of working through the
shopping list and moving items into the basket. It is a series of moves with no final
confirmation, and can be paused and resumed. Items not moved stay on the list. Anything
added after a transfer belongs to the next one.
_Avoid_: sync, push, send

**Move**:
One item becoming a basket line: a product and count are chosen, the line is added to the
basket, and the item leaves the shopping list, all at once. A product already in the basket
has its count increased rather than replaced.
_Avoid_: add to basket, transfer (for a single item)

**Remove**:
An item leaving the shopping list without a move, because it is no longer needed (bought
elsewhere, added by mistake). It never touches the basket or previously chosen. An item
leaves the list only by a move or a remove; there is no "bought" state.
_Avoid_: tick off, complete, check, delete

**Order**:
One Bilka To Go order, whose pickup slot and payment are completed in Bilka's own site or
app after a transfer.
_Avoid_: purchase, checkout

**Offer**:
A time-limited Bilka price reduction on a product, valid in specific stores. It only
matters if it still holds for the order it is bought in. Every offer is either a price cut or
a multibuy.
_Avoid_: discount, deal, tilbud

**Price cut**:
An offer that lowers the price of each unit, however many are bought ("Skarp pris",
99,00 → 69,00). Only price cuts make a product count as on offer when choosing.
_Avoid_: sale price, discount

**Multibuy**:
An offer that saves money only when enough units from a named group are bought together
("Mix 5 for 300,00"). The unit price is unchanged, so it is shown with how full it is but
never makes a product count as on offer.
_Avoid_: bundle, mix-deal, volume discount
