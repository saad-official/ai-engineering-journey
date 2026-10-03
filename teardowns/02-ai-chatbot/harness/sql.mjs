// Run one SQL statement against the teardown's PGlite server and print rows as JSON.
// Read-mostly: used to look at what the app persisted, and to stage break-it states.
// Usage (from the app dir): node sql.mjs "select ..."
import postgres from 'postgres';

const sql = postgres('postgres://postgres@127.0.0.1:5433/postgres', { max: 1 });
try {
  const rows = await sql.unsafe(process.argv[2]);
  console.log(JSON.stringify(rows, null, 1));
} finally {
  await sql.end();
}
