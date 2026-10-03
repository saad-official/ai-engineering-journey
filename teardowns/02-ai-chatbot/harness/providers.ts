// TEARDOWN 02 HARNESS - replaces upstream lib/ai/providers.ts (the ONLY upstream file changed).
// Upstream routes every model id through Vercel AI Gateway (`gateway.languageModel(id)`), which
// needs a gateway key with a card on file. CLAUDE.md rule 5 (cost first): send every model id
// to Gemini on the free tier instead. The model picker still lists the upstream models; whatever
// is picked, Gemini answers. Everything else (route handler, tools, DB, auth) is untouched.
//
// Upstream version: see teardowns/_src/ai-chatbot/lib/ai/providers.ts. Diff: providers.patch.
import { createGoogleGenerativeAI } from "@ai-sdk/google";
import { customProvider } from "ai";
import { isTestEnvironment } from "../constants";

const TEARDOWN_MODEL = process.env.TEARDOWN_MODEL ?? "gemini-3.5-flash-lite";

const google = createGoogleGenerativeAI({
  apiKey: process.env.GEMINI_API_KEY,
});

export const myProvider = isTestEnvironment
  ? (() => {
      const {
        chatModel,
        titleModel: mockTitleModel,
      } = require("./models.mock");
      return customProvider({
        languageModels: {
          "chat-model": chatModel,
          "title-model": mockTitleModel,
        },
      });
    })()
  : null;

export function getLanguageModel(modelId: string) {
  if (isTestEnvironment && myProvider) {
    return myProvider.languageModel(modelId);
  }

  return google(TEARDOWN_MODEL);
}

export function getTitleModel() {
  if (isTestEnvironment && myProvider) {
    return myProvider.languageModel("title-model");
  }
  return google(TEARDOWN_MODEL);
}
