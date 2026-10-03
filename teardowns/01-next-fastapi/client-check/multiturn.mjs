// Break-it test for FIX-8 (Gemini's thought_signature). Turn 1 asks for the weather (tool
// call). Turn 2 sends the whole conversation back - including turn 1's tool part - and asks a
// follow-up. Run twice: once as useChat would (signature kept in callProviderMetadata), once
// with the signature stripped, as a backend that drops provider metadata would.
//
// Usage: node multiturn.mjs <url>

import { writeFileSync } from 'node:fs';
import { DefaultChatTransport, readUIMessageStream } from 'ai';

const api = process.argv[2] ?? 'http://127.0.0.1:8001/api/chat';
const transport = new DefaultChatTransport({ api });

async function turn(messages) {
  const chunks = await transport.sendMessages({
    chatId: 'chat-multiturn', messages, trigger: 'submit-message',
    messageId: undefined, abortSignal: undefined,
  });
  let last;
  try {
    for await (const m of readUIMessageStream({ stream: chunks, terminateOnError: true })) last = m;
    return { ok: true, message: last };
  } catch (e) {
    return { ok: false, error: String(e.message ?? e) };
  }
}

const u1 = { id: 'u1', role: 'user', parts: [{ type: 'text', text: 'What is the weather in Lahore in celsius?' }] };
const t1 = await turn([u1]);
const u2 = { id: 'u2', role: 'user', parts: [{ type: 'text', text: 'And in Karachi? Compare the two.' }] };

const withSig = await turn([u1, t1.message, u2]);
await new Promise(r => setTimeout(r, 2000));
const stripped = structuredClone(t1.message);
for (const p of stripped.parts) delete p.callProviderMetadata;
const withoutSig = await turn([u1, stripped, u2]);

const summarize = r => r.ok
  ? { ok: true, parts: r.message.parts.map(p => p.type === 'text' ? `text: ${p.text}` : p.type) }
  : r;
const report = { turn1: summarize(t1), turn2_with_signature: summarize(withSig), turn2_signature_stripped: summarize(withoutSig) };
writeFileSync(new URL('../captures/K-multiturn-signature.json', import.meta.url), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
