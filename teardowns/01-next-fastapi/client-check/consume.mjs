// Drive a backend with the REAL `ai` package client code - the same transport classes useChat
// uses - minus React. useChat is roughly: transport.sendMessages() -> a stream of UI message
// chunks -> readUIMessageStream() folds them into one UIMessage -> React re-renders `parts`.
// We do exactly that and print the final UIMessage, so "does the frontend work with this
// backend?" is answered by Vercel's own parser, not by our reading of the docs.
//
// It also tees the raw HTTP response into ../captures/<name>.txt via a wrapping fetch, so we
// keep the exact bytes that went over the wire next to what the client made of them.
//
// Usage: node consume.mjs <name> <url> <data|text> "<prompt>"

import { writeFileSync } from 'node:fs';
import { DefaultChatTransport, TextStreamChatTransport, readUIMessageStream } from 'ai';

const [name, api, mode, prompt] = process.argv.slice(2);
if (!name || !api || !mode || !prompt) {
  console.error('usage: node consume.mjs <name> <url> <data|text> "<prompt>"');
  process.exit(2);
}

// Tee: let the transport read the body while we keep a copy of the raw bytes.
const teeFetch = async (input, init) => {
  const res = await fetch(input, init);
  const raw = await res.clone().text();
  const head = [...res.headers].map(([k, v]) => `${k}: ${v}`).join('\n');
  writeFileSync(
    new URL(`../captures/${name}.txt`, import.meta.url),
    `# REQUEST BODY (what useChat sends)\n${init.body}\n\n# RESPONSE ${res.status}\n${head}\n\n# RAW BODY\n${raw}`,
  );
  return res;
};

const transport =
  mode === 'text'
    ? new TextStreamChatTransport({ api, fetch: teeFetch })
    : new DefaultChatTransport({ api, fetch: teeFetch });

// A UIMessage, exactly the shape sendMessage({ text }) creates.
const userMessage = { id: 'msg-user-1', role: 'user', parts: [{ type: 'text', text: prompt }] };

try {
  const chunks = await transport.sendMessages({
    chatId: 'chat-teardown-01',
    messages: [userMessage],
    trigger: 'submit-message',
    messageId: undefined,
    abortSignal: undefined,
  });
  let last;
  for await (const message of readUIMessageStream({ stream: chunks, terminateOnError: true })) {
    last = message; // each yield is the assistant message so far - what React would render
  }
  console.log(JSON.stringify({ name, ok: true, assistantMessage: last ?? null }, null, 2));
} catch (err) {
  console.log(JSON.stringify({ name, ok: false, error: String(err?.message ?? err) }, null, 2));
}
