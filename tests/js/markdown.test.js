// Run with: node --test tests/js
const test = require("node:test");
const assert = require("node:assert/strict");
const { parseBlocks, parseInline } = require("../../eduai/web/static/markdown.js");

test("fenced code keeps contents verbatim and language", () => {
  const blocks = parseBlocks("Here:\n```python\nx = 1  # **not bold**\nprint(x)\n```\nDone.");
  assert.deepEqual(blocks.map((b) => b.type), ["paragraph", "code", "paragraph"]);
  assert.equal(blocks[1].lang, "python");
  assert.equal(blocks[1].text, "x = 1  # **not bold**\nprint(x)");
  assert.equal(blocks[1].closed, true);
});

test("unfinished code block while streaming is still code", () => {
  const blocks = parseBlocks("```python\ndef f():\n    return 1");
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].type, "code");
  assert.equal(blocks[0].closed, false);
});

test("headings, lists, rules and quotes", () => {
  const blocks = parseBlocks("### Steps\n1. First\n2. Second\n   continued\n\n- a\n- b\n\n---\n> note");
  assert.deepEqual(blocks.map((b) => b.type), ["heading", "list", "list", "rule", "quote"]);
  assert.equal(blocks[0].level, 3);
  assert.deepEqual(blocks[1], { type: "list", ordered: true, start: 1, items: ["First", "Second continued"] });
  assert.deepEqual(blocks[2].items, ["a", "b"]);
});

test("tables", () => {
  const blocks = parseBlocks("| Type | Mutable |\n|---|:---:|\n| list | yes |\n| tuple | no |");
  assert.equal(blocks[0].type, "table");
  assert.deepEqual(blocks[0].header, ["Type", "Mutable"]);
  assert.deepEqual(blocks[0].rows, [["list", "yes"], ["tuple", "no"]]);
});

test("inline code, bold and italic", () => {
  const tokens = parseInline("Use `len(x)` for **length** and *not* x.size");
  assert.deepEqual(tokens.map((t) => t.type), ["text", "code", "text", "bold", "text", "italic", "text"]);
  assert.equal(tokens[1].text, "len(x)");
});

test("snake_case and multiplication are not italic", () => {
  assert.deepEqual(parseInline("my_var_name").map((t) => t.type), ["text"]);
  assert.deepEqual(parseInline("2 * 3 * 4").map((t) => t.type), ["text"]);
});

test("HTML from the model stays plain text", () => {
  const tokens = parseInline('<script>alert("x")</script> <img src=x onerror=alert(1)>');
  assert.deepEqual(tokens, [{ type: "text", text: '<script>alert("x")</script> <img src=x onerror=alert(1)>' }]);
  const blocks = parseBlocks("<b>hi</b>");
  assert.deepEqual(blocks, [{ type: "paragraph", text: "<b>hi</b>" }]);
});
