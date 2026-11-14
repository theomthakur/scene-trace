# Agent notes for this repository

- Local-only project. Do not push, publish or deploy without an explicit request from Om.
- Real inference gate: never substitute fixture detections for detector output. Fixtures are for the temporal-rule lane only and are tagged `source: fixture`.
- Record every tuned or added constant in `docs/PARAMETER-LEDGER.md`. Do not tune on the frozen test split.
- Keep `IMPLEMENTATION-STATUS.md` honest: actual commands, actual outcomes, unmet gates.
- No em dashes in docs or UI text. No Co-Authored-By or AI attribution in commits.
- Video positions are integer milliseconds. Boxes and zones are normalized xyxy in the orientation-correct frame.
