// A real Postgres wire-protocol server backed by PGlite (Postgres compiled to WASM), so the
// chatbot's unmodified `postgres` driver + Drizzle code talks to it exactly as it would to Neon
// or RDS. Why not Docker Postgres: the daemon isn't running here and G: has ~2 GB free.
// What this is NOT: a production database. PGlite is single-process; the socket server queues
// queries from several connections onto one engine. Fine for one person clicking around.
//
// Usage (from the app dir): node pg-server.mjs <dataDir> [port]

import { PGlite } from '@electric-sql/pglite';
import { PGLiteSocketServer } from '@electric-sql/pglite-socket';

const dataDir = process.argv[2] ?? './.pglite';
const port = Number(process.argv[3] ?? 5433);

const db = await PGlite.create(dataDir);
// postgres.js opens a pool of up to 10 connections by default (lib/db/queries.ts uses defaults).
const server = new PGLiteSocketServer({ db, port, host: '127.0.0.1', maxConnections: 20 });
await server.start();
console.log(`pglite listening on postgres://postgres@127.0.0.1:${port}/postgres (data: ${dataDir})`);

const stop = async () => {
  await server.stop();
  await db.close();
  process.exit(0);
};
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
