# Concepts

The two marks considered for v0.1.1, kept as a record of the choice. Both keep
the Cosecre C and put it on something; they differ in what.

**Superseded in v0.2.0.** When the print tool moved into Cosecre, its mark —
*Aperture*, the C whose opening is a paper slot — became the app's icon, along
with Cosecre-print's blue palette. Ledger, below, was the icon until then.

| | | |
|---|---|---|
| [`option-a-desk.svg`](option-a-desk.svg) | **Desk** | The C on a writing desk — the secretary's workspace. Holds together best at 16px: the overhanging top and two legs stay separable when everything else has merged. |
| [`option-b-ledger.svg`](option-b-ledger.svg) | **Ledger** | The C on a data table — header row, two body rows, two columns. **Chosen.** It describes what the product does rather than where it sits. |

The chosen one is the master in [`../icon.svg`](../icon.svg); edit there, not
here. These two files are frozen.

## What small sizes decided

Both were rendered at 512, 64, 32 and 16 before choosing, because an app icon is
judged at the size it actually appears in a Dock or a browser tab, not at the
size it is drawn.

Two things changed as a result, and they are the reason the numbers in
`icon.svg` look arbitrary:

- The column gap went from 14 units to **24**. At 14 it closed up under
  downsampling and the table read as plain stripes.
- The body rows step down in **opacity** rather than in width. Narrowing them
  looked better at full size but turned into an indistinct wedge at 16px;
  a weight gradient still reads top-to-bottom as "header, then data".
