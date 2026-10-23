# Blind hold-out: DO NOT TUNE AGAINST THIS SET

Scored only at CP2 and at freeze (`python -m teratai.evaluate --set messy_holdout --i-am-scoring-the-holdout`).
Nobody reads its rows to change a regex, a prompt or a threshold. BA: review realism and `reply_language` before the
first scoring run.

- 49 rows (`MH-001..MH-049`, 7 per category), rewritten by `claude-sonnet-5-5` from the style card in
  `docs/dev/reviews/2026-10-23-robustness.md` §5.4 and the facts of one training complaint only (`source_id`).
  The generator prompt contained no code, no regex list and no reviewer row. Sources were picked at random
  (fixed seed) per category, excluding every source of `messy_dev`.
- Customer, `received_at` and every gold field except `reply_language` are the source row's. `reply_language` follows
  the REPLY_LANGUAGE rule on the new text: the language the generator declared (`declared_language`), or the customer's
  `preferred_language` when it declared MIXED or wrote a staff note (`staff_note`, channel `Call centre note`).
  The declared language comes from an LLM and is the least certain label: that is what the BA should check.
- Shapes asked for (column `shape`): second non-disputed amount, third-person staff notes (EN, MS), 12-word complaints,
  `k` / spaced / word / glued-`myr` amounts, SMS dates and spellings, misspelt merchants, Manglish, ALL CAPS, formal Malay.
- A row whose source amount was approximate keeps an approximation marker (checked by the generator script).
