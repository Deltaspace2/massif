# Cassettes

Recorded model output, replayed offline so the suite never touches the network
and never varies. Two kinds:

- **`real-*.json`** — what a correct reading of a stored Saint-Gervais notice
  looks like. These pin that a good answer survives all four guards intact.
- **`bad-*.json`** — deliberately wrong readings, hand-written. These are the
  interesting ones: the guards exist for these, and a test suite made only of
  correct answers proves nothing about a component whose whole job is catching
  incorrect ones.

Each file is the raw JSON array a model returns for one document. The document
text it was recorded against lives beside it in the test module, because a
cassette divorced from its document replays an answer about text nobody has.
