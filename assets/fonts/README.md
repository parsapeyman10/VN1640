# Fonts used by `tools/build_pdf.py`

| File | Why | Licence |
|---|---|---|
| `Vazirmatn-Regular.ttf`, `Vazirmatn-Bold.ttf` | main text: Persian + Latin, correct Arabic shaping | SIL Open Font License 1.1 |
| `DejaVuSans.ttf` | glyph fallback for characters Vazirmatn lacks: `→ ← ↔`, box drawing `│ ─`, `▶ ✓` | DejaVu Fonts Licence (Bitstream Vera derived, free) |
| `DejaVuSansMono.ttf` | code blocks, because the ASCII diagrams in `docs/README.md` only line up with equal advances | same as above |

Vazirmatn is by Saber Rastikerdar (github.com/rastikerdar/vazirmatn).
DejaVu is by the DejaVu project (dejavu-fonts.github.io).

Both licences permit bundling and redistribution. If you replace them, keep
the two roles in mind: **a Persian text face** plus **a wide-coverage
monospace** — dropping the monospace breaks the diagrams.
