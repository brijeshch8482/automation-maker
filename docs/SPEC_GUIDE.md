# Designing an AutomationSpec

Read by the `am-spec` routine (and anyone writing a catalog automation). A spec describes the **format** of a task, never its data: the user types real names, amounts and files only inside the EXE on their own PC. The models are in `spec/src/spec/models.py`, the blocks in `spec/schema/block_catalog.json`, and complete examples in `examples/catalog/` (in automation-builds; `automations/` in automation-maker) and `examples/custom/word-count/`.

Check every spec with `uv run --no-sync python -m tools.validate_spec spec.json`.

## 1. The shape

```json
{
  "id": "word-count", "version": "1.0.0", "title": "Word Count",
  "description": "One or two plain sentences for the website. Say what stays unchanged.",
  "category": "documents",
  "network": { "required": false, "domains": [] },
  "settings": [ ... ], "inputs": [ ... ], "steps": [ ... ],
  "output": { "type": "file", "open_after": true },
  "sample_data": { ... }
}
```

- `id`: lower-case words joined by `-`. `version`: `1.0.0` for a new design; raise the minor number on a revision.
- `category`: `documents`, `pdf`, `images`, `excel`, `files`, `convert` or `other`.
- `settings`: asked **once** and remembered (business name, logo, the folder to save to). `inputs`: asked **every run**. A key may not be in both.
- `output.type`: `file` (one saved file, usually with `open_after: true`), `files`, `folder` (changes inside a folder, such as renames) or `none`.

## 2. Fields

Every field has `key` (`snake_case`), `type`, a short `label` in the user's words, and optionally `required` and `help` (one sentence, shown under the field).

| type | Use for | Extra keys |
|---|---|---|
| `text` | names, notes | `multiline`, `default` |
| `number` | counts, percentages | `min`, `max`, `default` |
| `money` | amounts | `currency` (default `INR`), `default` |
| `phone`, `email` | contact details | `default` |
| `date` | dates | `default: "today"` |
| `select` | one of a few choices | `options` (unique), `default` |
| `checkbox` | yes/no | `default` |
| `file` / `files` | documents to read | `extensions` (`["pdf"]`, no dot), `files` also `min_count` |
| `image_file` | a logo or photo | |
| `folder` | a folder to read, or to save into | |
| `table` | rows of items | `columns` (fields of the simple types above), `min_rows` |

Write labels for someone who has never used the tool: "Customer name", "Save invoices to", "PDF files, in order". Prefer a `default` that works, so the first run needs little typing.

## 3. Steps

Steps run in order. Each is `{ "block": "<name>", "args": { ... }, "out": "<name>" }`; `out` makes its result available to later steps by that name.

References inside `args`:
- an input key or an earlier `out` name: `"files": "pdfs"`;
- a setting: `"folder": "@settings.output_folder"` (an empty folder setting means the app's own output folder);
- a name template: `"name": "{invoice_no} {customer_name}.pdf"` (inputs and outs in braces).

| Block | Does | Produces |
|---|---|---|
| `counter.next` | next number of a counter that persists (INV-0007) | text |
| `calc.line_totals` | qty × rate per table row, subtotal, tax %, total | totals |
| `pdf.render_template` | a PDF from a bundled template: only `invoice_basic`, which reads the field keys of `invoice-generator` | PDF document |
| `pdf.merge` | PDFs into one, in order | PDF document |
| `pdf.from_files` | photos, scans and PDF pages into one PDF | PDF document |
| `file.save` | saves a document under a new name; never overwrites | saved file |
| `files.scan` | lists the files in a folder | list of files |
| `files.rename` | plans new names; the user sees a preview and can undo | rename plan |
| `custom.step` | runs `custom_step.py` (section 5) | what it returns |

Exact arguments are in `spec/schema/block_catalog.json`. A document (PDF, report) is saved only by a `file.save` step, so end with one when the result is a file.

## 4. sample_data

**Fake** values for every required input and setting, used for the smoke test and the guide's screenshots. They must look realistic and be obviously not real: "Asha Traders", "+91 00000 00000", "example@example.com". File and folder values are paths relative to `spec.json` inside `samples/` (`"samples/Notes.txt"`); the `am-build` routine creates those small files.

## 5. When there is no block for it: `custom.step`

Use `custom.step` only when no combination of blocks can do the job, and describe exactly what the function must do in `args.description` (inputs it reads, what it returns). The `am-build` routine writes `custom_step.py` from that description. The function receives a context (`engine/src/engine/custom_api.py`):

- `ctx.input(key)`, `ctx.setting(key)`, `ctx.out(name)`: values;
- `ctx.read_bytes(path)`: read a file the user selected;
- `ctx.document(data, "txt")`: return a file made in memory, then save it with a `file.save` step (the normal way);
- `ctx.save_bytes(name, data)`: save extra files straight into the output folder.

It may not delete, rename or overwrite files, start programs, or use the internet (unless the spec declares it). The engine enforces this while the step runs.

## 6. Network

Keep `"network": { "required": false, "domains": [] }`. Set `required: true` only if the task cannot work without the internet (for example, fetching exchange rates), and list the exact host names (`"api.example.com"`, no scheme, path or wildcard). The website shows a 🌐 badge for such automations.

## 7. Questions and assumptions

With the spec, `am-spec` returns:
- `assumptions`: short statements of what it decided ("Invoices are numbered INV-0001, INV-0002, ...");
- `questions`: at most 5 short questions about the **format** only ("Should the invoice show a GSTIN?"), never asking for real data.

If the user's description contains real-looking data (names, numbers, IDs, amounts), turn each into a field and leave the value out of the spec.
