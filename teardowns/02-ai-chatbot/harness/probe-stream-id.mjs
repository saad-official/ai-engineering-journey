// Probe: route.ts consumeSseStream() does
//     const streamId = generateId();            // from "ai"
//     await createStreamId({ chatId: id, streamId });
// and the Stream table's id column is `uuid` (lib/db/migrations/0000_initial.sql). What does
// ai's generateId() return, and does Postgres accept it? The whole block sits in try/catch
// "non-critical", so a failure here would be silent in the app. Uses their exact queries.ts
// insert shape via the same postgres.js driver, against the same migrated schema.
//
// Usage (from the app dir, pg-server running): node probe-stream-id.mjs

import { randomUUID } from 'node:crypto';
import { generateId } from 'ai';
import postgres from 'postgres';

const sql = postgres('postgres://postgres@127.0.0.1:5433/postgres', { max: 1 });
const userId = randomUUID();
const chatId = randomUUID();
await sql`insert into "User" (id, email) values (${userId}, ${'probe-' + Date.now()})`;
await sql`insert into "Chat" (id, "createdAt", title, "userId") values (${chatId}, now(), 'probe', ${userId})`;

const streamId = generateId();
console.log('generateId() ->', JSON.stringify(streamId), `(${streamId.length} chars)`);
for (const [label, id] of [['generateId()', streamId], ['crypto.randomUUID()', randomUUID()]]) {
  try {
    await sql`insert into "Stream" (id, "chatId", "createdAt") values (${id}, ${chatId}, now())`;
    console.log(`${label}: insert OK`);
  } catch (e) {
    console.log(`${label}: insert FAILED -> ${e.code} ${e.message}`);
  }
}
await sql.end();
