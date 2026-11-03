import assert from "node:assert/strict";
import { test } from "node:test";
import { Card, Editor, loadPage, settle, standInHass } from "./stand-in.mjs";

const ENTITY = { entity: "todo.bilka_to_go_shopping_list" };

async function cardWith(t, sections, data = {}) {
  const window = await loadPage(t);
  const hass = standInHass(data);
  const config = sections === undefined ? ENTITY : { ...ENTITY, sections };
  const card = new Card(window, config, hass);
  await settle();
  return { card, hass, window };
}

test("without sections the card shows everything", async (t) => {
  const { card } = await cardWith(t, undefined, { items: ["mælk"], known: ["pasta"] });
  for (const part of ["name", "amount", "add", "suggestions", "list"]) {
    assert.ok(card.shows(part), `${part} should show`);
  }
  assert.deepEqual(card.rows, ["mælk"]);
  assert.deepEqual(card.suggestions.map((chip) => chip.textContent), ["pasta"]);
});

test("sections [list] shows only the list", async (t) => {
  const { card } = await cardWith(t, ["list"], { items: ["mælk"], known: ["pasta"] });
  assert.ok(card.shows("list"));
  for (const part of ["name", "amount", "add", "suggestions"]) {
    assert.ok(!card.shows(part), `${part} should be hidden`);
  }
});

test("the order of the sections does not change where parts appear", async (t) => {
  const { card } = await cardWith(t, ["list", "add"], { items: ["mælk"] });
  const form = card.root.querySelector("form");
  const list = card.root.querySelector("ul");
  assert.ok(form.compareDocumentPosition(list) & card.window.Node.DOCUMENT_POSITION_FOLLOWING);
});

for (const [label, sections] of [
  ["not a list", "list"],
  ["empty", []],
  ["an unknown value", ["add", "chips"]],
  ["a duplicate", ["list", "list"]],
  ["amount without add", ["amount", "list"]],
  ["suggestions without add", ["suggestions"]],
]) {
  test(`sections is refused when it is ${label}`, async (t) => {
    const window = await loadPage(t);
    const element = window.document.createElement("bilka-shopping-list-card");
    assert.throws(() => element.setConfig({ ...ENTITY, sections }), /sections/);
  });
}

test("null sections is refused, as an empty YAML key would give", async (t) => {
  const window = await loadPage(t);
  const element = window.document.createElement("bilka-shopping-list-card");
  assert.throws(() => element.setConfig({ ...ENTITY, sections: null }), /sections/);
});

// Copied, because what the card builds belongs to the page's realm, not the test's.
const added = (hass) =>
  hass.calls.filter((call) => call.service === "add_item").map((call) => ({ ...call.data }));

test("without amount, typing adds an item with no amount", async (t) => {
  const { card, hass } = await cardWith(t, ["add", "suggestions"]);
  assert.ok(!card.shows("amount"));
  card.type("mælk");
  await card.submit();
  assert.deepEqual(added(hass), [{ item: "mælk" }]);
});

test("without amount, tapping a suggestion adds an item with no amount", async (t) => {
  const { card, hass } = await cardWith(t, ["add", "suggestions"], { known: ["pasta"] });
  await card.tapSuggestion("pasta");
  assert.deepEqual(added(hass), [{ item: "pasta" }]);
});

test("reconfiguring without amount drops an amount already typed", async (t) => {
  const { card, hass } = await cardWith(t, ["add", "amount"]);
  card.type("mælk", "2");
  card.element.setConfig({ ...ENTITY, sections: ["add"] });
  await card.submit();
  assert.deepEqual(added(hass), [{ item: "mælk" }]);
});

test("with the list hidden, suggestions already on the list are still dimmed", async (t) => {
  const { card } = await cardWith(t, ["add", "amount", "suggestions"], {
    items: ["Pasta"],
    known: ["pasta", "ris"],
  });
  const dimmed = card.suggestions.filter((chip) => chip.classList.contains("on-list"));
  assert.deepEqual(dimmed.map((chip) => chip.textContent), ["pasta"]);
});

test("the list on its own removes an item and undo brings it back", async (t) => {
  const { card } = await cardWith(t, ["list"], { items: ["mælk", "ris"] });
  await card.remove("mælk");
  assert.deepEqual(card.rows, ["ris"]);
  assert.ok(card.visible("#undo"));
  await card.undo();
  assert.ok(card.rows.includes("mælk"));
});

// The focus itself is watched, since a real browser will not focus a hidden field but jsdom may.
async function focusedAfterOpening(t, sections) {
  const window = await loadPage(t);
  window.location.hash = "#indkob";
  const card = new Card(window, { ...ENTITY, sections, autofocus_hash: "#indkob" }, standInHass());
  let focused = false;
  card.nameField.focus = () => { focused = true; };
  await new Promise((resolve) => setTimeout(resolve, 400));
  return focused;
}

test("autofocus focuses the name when the add form shows", async (t) => {
  assert.equal(await focusedAfterOpening(t, ["add"]), true);
});

test("autofocus has no effect and raises nothing without add", async (t) => {
  assert.equal(await focusedAfterOpening(t, ["list"]), false);
});

test("two cards on a page follow the same list", async (t) => {
  const window = await loadPage(t);
  const hass = standInHass({ items: ["mælk"] });
  const adding = new Card(window, { ...ENTITY, sections: ["add"] }, hass);
  const list = new Card(window, { ...ENTITY, sections: ["list"] }, hass);
  await settle();
  adding.type("ris");
  await adding.submit();
  assert.deepEqual(list.rows, ["mælk", "ris"]);
});

test("the card asks for room for what it shows", async (t) => {
  const items = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"];
  assert.equal((await cardWith(t, undefined, { items })).card.element.getCardSize(), 10);
  assert.equal((await cardWith(t, ["add"], { items })).card.element.getCardSize(), 1);
  assert.equal((await cardWith(t, ["add", "suggestions"], { items })).card.element.getCardSize(), 2);
  assert.equal((await cardWith(t, ["list"], { items: ["a", "b"] })).card.element.getCardSize(), 2);
  assert.equal((await cardWith(t, ["list"])).card.element.getCardSize(), 1);
});

test("a list keeps following after being taken off the page and put back", async (t) => {
  const { card, hass, window } = await cardWith(t, ["list"], { items: ["mælk"] });
  card.element.remove();
  await settle();
  assert.equal(hass.live.length, 0);
  window.document.body.append(card.element);
  await settle();
  assert.equal(hass.live.length, 1);
  await hass.callService("todo", "add_item", { item: "ris" });
  assert.deepEqual(card.rows, ["mælk", "ris"]);
});

test("taking a card off and on while subscribing leaves one subscription", async (t) => {
  const window = await loadPage(t);
  const hass = standInHass({ items: ["mælk"] });
  let answer;
  hass.holdSubscribe = new Promise((resolve) => { answer = resolve; });
  const card = new Card(window, { ...ENTITY, sections: ["list"] }, hass);
  card.element.remove();
  window.document.body.append(card.element);
  answer();
  await settle();
  assert.equal(hass.live.length, 1);
  card.element.remove();
  await settle();
  assert.equal(hass.live.length, 0);
});

test("taken off the page while subscribing leaves no subscription", async (t) => {
  const window = await loadPage(t);
  const hass = standInHass();
  let answer;
  hass.holdSubscribe = new Promise((resolve) => { answer = resolve; });
  const card = new Card(window, { ...ENTITY, sections: ["list"] }, hass);
  card.element.remove();
  answer();
  await settle();
  assert.equal(hass.live.length, 0);
});

test("a card placed before it gets hass still follows the list", async (t) => {
  const window = await loadPage(t);
  const hass = standInHass({ items: ["mælk"] });
  const element = window.document.createElement("bilka-shopping-list-card");
  element.setConfig({ ...ENTITY, sections: ["list"] });
  window.document.body.append(element);
  element.hass = hass;
  await settle();
  assert.equal(hass.live.length, 1);
});

test("reconfiguring a card on the page keeps its list and suggestions", async (t) => {
  const { card, hass } = await cardWith(t, ["add", "suggestions"], { items: ["mælk", "ris"], known: ["pasta"] });
  card.element.setConfig({ ...ENTITY, sections: ["add", "suggestions", "list"] });
  assert.equal(card.element.getCardSize(), 4);
  card.type("p");
  assert.deepEqual(card.suggestions.map((chip) => chip.textContent), ["pasta"]);
  hass.emit();
  assert.deepEqual(card.rows, ["mælk", "ris"]);
});

const CONFIG = { type: "custom:bilka-shopping-list-card", ...ENTITY, autofocus_hash: "#indkob" };

test("the editor shows everything ticked for a card without sections", async (t) => {
  const editor = new Editor(await loadPage(t), CONFIG);
  assert.deepEqual(editor.ticked, ["add", "amount", "suggestions", "list"]);
  assert.equal(editor.saved.length, 0);
});

test("the editor shows what a card's sections hold", async (t) => {
  const editor = new Editor(await loadPage(t), { ...CONFIG, sections: ["list", "add"] });
  assert.deepEqual(editor.ticked, ["add", "list"]);
});

test("unticking saves the sections left, and keeps the rest of the config", async (t) => {
  const editor = new Editor(await loadPage(t), CONFIG);
  editor.click("amount");
  assert.deepEqual(editor.lastSaved, { ...CONFIG, sections: ["add", "suggestions", "list"] });
});

test("sections leaves the config again when everything is ticked", async (t) => {
  const editor = new Editor(await loadPage(t), { ...CONFIG, sections: ["add", "suggestions", "list"] });
  editor.click("amount");
  assert.deepEqual(editor.lastSaved, CONFIG);
});

test("sections are saved in the card's order, whatever order they are ticked in", async (t) => {
  const editor = new Editor(await loadPage(t), { ...CONFIG, sections: ["list"] });
  editor.click("add");
  assert.deepEqual(editor.lastSaved.sections, ["add", "list"]);
});

test("unticking add also takes amount and suggestions, and locks them", async (t) => {
  const editor = new Editor(await loadPage(t), CONFIG);
  editor.click("add");
  assert.deepEqual(editor.lastSaved.sections, ["list"]);
  assert.deepEqual(editor.ticked, ["list"]);
  assert.deepEqual(editor.locked, ["amount", "suggestions", "list"]);
});

test("ticking add again unlocks amount and suggestions", async (t) => {
  const editor = new Editor(await loadPage(t), { ...CONFIG, sections: ["list"] });
  editor.click("add");
  assert.deepEqual(editor.locked, []);
  editor.click("amount");
  assert.deepEqual(editor.lastSaved.sections, ["add", "amount", "list"]);
});

test("the last part left cannot be unticked", async (t) => {
  const onlyAdd = new Editor(await loadPage(t), { ...CONFIG, sections: ["add"] });
  assert.deepEqual(onlyAdd.locked, ["add"]);
  const onlyList = new Editor(await loadPage(t), { ...CONFIG, sections: ["list"] });
  assert.deepEqual(onlyList.locked, ["amount", "suggestions", "list"]);
});

test("whatever the editor saves, the card accepts", async (t) => {
  const window = await loadPage(t);
  const editor = new Editor(window, CONFIG);
  for (const section of ["amount", "suggestions", "add", "add", "list", "amount"]) {
    editor.click(section);
    const card = window.document.createElement("bilka-shopping-list-card");
    card.setConfig(editor.lastSaved);
  }
  assert.equal(editor.saved.length, 6);
});

test("the editor refuses invalid sections, so Home Assistant can offer YAML instead", async (t) => {
  const window = await loadPage(t);
  const Card = window.customElements.get("bilka-shopping-list-card");
  assert.throws(() => Card.getConfigElement().setConfig({ ...CONFIG, sections: ["chips"] }), /sections/);
});

test("the card picker gets a config the card accepts", async (t) => {
  const window = await loadPage(t);
  const Card = window.customElements.get("bilka-shopping-list-card");
  const element = window.document.createElement("bilka-shopping-list-card");
  element.setConfig(Card.getStubConfig());
  assert.ok(element.shadowRoot);
});
