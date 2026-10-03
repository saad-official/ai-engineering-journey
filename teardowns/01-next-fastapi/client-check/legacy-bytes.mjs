// What does today's useChat do with the LEGACY prefix lines the Python example emits?
// Feed hand-written legacy bytes straight into DefaultChatTransport's response parser.
import { DefaultChatTransport, readUIMessageStream } from 'ai';

const legacy = '0:"The sky "\n0:"is blue."\nd:{"finishReason":"stop","usage":{"promptTokens":9,"completionTokens":5}}\n';
const body = new Response(legacy).body;
const chunks = new DefaultChatTransport().processResponseStream(body);
let last, err;
try {
  for await (const m of readUIMessageStream({ stream: chunks, terminateOnError: true })) last = m;
} catch (e) { err = String(e.message ?? e); }
console.log(JSON.stringify({ input: legacy, assistantMessage: last ?? null, error: err ?? null }, null, 2));
