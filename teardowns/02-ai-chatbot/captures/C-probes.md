# Teardown 02 / capture C: break-it probes (2026-10-03)

All requests made from inside the running app's page (guest session cookie), against the unmodified
route handler. DB state read with `harness/sql.mjs`.

## C1. What the DB stored after capture B
| table | row | note |
|---|---|---|
| User | `guest-1791051623553`, isAnonymous=false | a guest is a full User row; one per new browser, never cleaned up |
| Chat | title "San Francisco Weather" | title from a separate LLM call (`generateTitleFromUserMessage`) |
| Message_v2 | user, parts 64 bytes | saved BEFORE the model call |
| Message_v2 | assistant, parts **5661 bytes** | saved in `onEnd`; UIMessage parts verbatim, incl. `data-chat-title`, the full weather JSON, and Gemini's thoughtSignature |
| Stream | 0 rows | no REDIS_URL, so consumeSseStream returns early |

## C2. Guards
| probe | result |
|---|---|
| POST with another user's chat id | **403** `forbidden:chat` (ownership check works) |
| text part of 2001 chars | **400** `bad_request:api` (zod max 2000: a cost guard) |
| chat id not a UUID | **400** `bad_request:api` |

## C3. Rate limit (entitlement: guest maxMessagesPerHour = 10)
Staged user messages in the window with SQL, then sent real requests.
| state before | requests | result |
|---|---|---|
| 10 in window | 1 | **200** (the 11th message is allowed: `count > max` is checked before the insert) |
| 11 in window | 1 | **429** `rate_limit:chat` |
| 9 in window | 5 concurrent | 2 × 200, 3 × 429: **no race reproduced**. Caveat: PGlite runs every query on one serialized engine, so it cannot interleave like a pooled Postgres. Absence not proven. |

Side finding while staging: `createdAt` is `timestamp without time zone`. App rows hold UTC wall
time (JS Date via postgres.js); SQL `now()` / `defaultNow()` rows hold the DB session's zone
(PGlite picked up Etc/GMT-5). The first staging attempt was off by 5 hours because of it.

## C4. Stream id vs uuid column (harness/probe-stream-id.mjs → capture A)
`generateId()` → `"o7MR2KI5QSpHkFem"` (16 chars). Insert into `"Stream".id uuid` → **22P02 invalid
input syntax for type uuid**. `crypto.randomUUID()` → OK. In route.ts this runs before
`createNewResumableStream`, inside try/catch "non-critical", so even with REDIS_URL set no
resumable stream is ever created, silently.

## C5. Stop mid-generation (essay → createDocument → nested streamText)
| time (UTC) | event |
|---|---|
| 18:29:19.251 | user message saved |
| +4.37 s | first `data-textDelta` of the document reaches the browser |
| +5.87 s | client aborts (same as pressing Stop): 90 document deltas received |
| 18:29:36.243 | **Document "The History of the Telescope", 5608 chars, saved**, about 11 s after the abort |
| (later) | **no assistant message ever saved** for this chat |

So the sub-generation ran to completion after Stop (fully billed), its result was persisted, and
the message that references it was not: the Document is orphaned (`Document` has no chatId).

## C6. Reload after the abort (autoResume)
`GET /api/chat/94485964-.../stream` → **204**. The page shows the user's question and nothing else.
The 204 handler replaced a 113-line Redis resume implementation in upstream commit `9d5d8a3`
(2026-01-15, "fix: title generation + ai sdk upgrade"); `getStreamIdsByChatId` is now dead code.
