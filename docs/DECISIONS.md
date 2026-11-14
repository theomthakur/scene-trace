# Decisions

1. **Footage:** public CC0 clips from Wikimedia Commons, SHA-1 verified, not committed. Shot angle is outdoor and low, not an indoor aisle: accepted because licence clarity mattered more than scene match, and recorded as a limitation. Two clips found to be unsuitable (a bank news report with cuts and identifiable people; a low-angle walkway with tiny figures) were not used.
2. **Annotation scope:** only what could be judged reliably from raw frames. Crossings in the pedestrian clip were not annotated because ground contact is unreliable there.
3. **Defaults unchanged after the sweep:** one clip and two events cannot justify tuning. The sweep is reported, not adopted.
4. **Results are published, not retuned:** the frozen test showed a borderline match (temporal IoU 0.52) and a duplicate fragment counted as a false positive; both stay in the report.
5. **Single worker, SQLite WAL, no Redis:** matches the brief's first-version constraint.
6. **Search is a keyword parser, not semantic:** unsupported intents (unattended, who, why) return no events plus a notice.
7. **Review conflicts:** optimistic revision numbers, 409 on mismatch.
8. **Test infrastructure:** a scripted `FixtureDetector` carries `source = "fixture"` so test events can never be mistaken for real inference.
