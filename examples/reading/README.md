# Reading examples (flh_reading_pack_v1)

[`internal/reading/pack/reading_pack_v1.json`](../../internal/reading/pack/reading_pack_v1.json) holds six original French passages written in an A2–B1
*style*, with reviewed exam-style questions: a reference answer, accepted
alternatives, plausible wrong answers with their reasons, and verbatim
evidence by paragraph ID. They are **authored practice material**, not
official exam items, with no certified CEFR level. Every name, place and
address is invented.

The server embeds that file (`internal/reading/pack.go`; it lives under `internal/` so the release image's build context includes it), so the **Reading** view lists the
passages under **Authored examples**. **Use this example** imports one as a
lesson with its reviewed exercise; it makes no model call. Importing the same
passage again opens the existing lesson.

Over HTTP:

```bash
curl -s http://127.0.0.1:8080/reading/examples                                   # titles only
curl -s -X POST http://127.0.0.1:8080/reading/examples/rd-email-chaudiere         # import one
```

The pack is generated and validated outside this repository (its
`validate_pack.py`). If you edit the file, the server validates it again at
startup and refuses a pack that does not pass (`domain.ParseReadingPack`).
