"""Sample texts for lab 02.

Six deliberately different shapes. The point is that "tokens" is not a property of
length alone: the same number of characters costs wildly different amounts depending
on what those characters are.

All text here is synthetic and public. Free-tier prompts are used to improve the
provider's products (see TECHNOLOGY_STACK.md), so nothing private or company-related
ever goes through these labs.

`JSON_MIN` and `JSON_PRETTY` are serialised from the *same* Python object, so any
token difference between them is pure formatting - whitespace and indentation - with
identical meaning. That pair is the cheapest cost lever in the whole lab.
"""

from __future__ import annotations

import json

PROSE_EN = (
    "The release train leaves every second Tuesday. Anything merged to the main branch "
    "before the freeze on Monday evening ships automatically; anything after it waits two "
    "weeks. Hotfixes are the only exception, and they need a second reviewer before they "
    "can be cherry-picked onto the release branch. If a change alters a public interface, "
    "it must be flagged as breaking in the pull request title so the notes pick it up."
)

# The same meaning in Urdu. Non-Latin scripts are usually far less token-efficient,
# which means the same feature costs more and fits less for those users.
PROSE_UR = (
    "ریلیز ٹرین ہر دوسرے منگل کو روانہ ہوتی ہے۔ پیر کی شام فریز سے پہلے مین برانچ میں "
    "ضم ہونے والی ہر تبدیلی خود بخود شپ ہو جاتی ہے؛ اس کے بعد آنے والی کو دو ہفتے انتظار "
    "کرنا پڑتا ہے۔ صرف ہاٹ فکس مستثنیٰ ہیں، اور انہیں ریلیز برانچ پر چیری پک کرنے سے پہلے "
    "دوسرے جائزہ کار کی ضرورت ہوتی ہے۔ اگر کوئی تبدیلی عوامی انٹرفیس کو بدلتی ہے تو اسے "
    "پل ریکویسٹ کے عنوان میں بریکنگ کے طور پر نشان زد کرنا لازمی ہے۔"
)

CODE_TS = """\
import { useCallback, useEffect, useState } from "react";

type ReleaseStatus = "pending" | "shipped" | "rolled-back";

interface Release {
  id: string;
  version: string;
  status: ReleaseStatus;
  mergedAt: string | null;
  breakingChanges: number;
}

export function useReleases(projectId: string) {
  const [releases, setReleases] = useState<Release[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await fetch(`/api/projects/${projectId}/releases`);
      if (!response.ok) throw new Error(`Failed: ${response.status}`);
      setReleases((await response.json()) as Release[]);
    } finally {
      setIsLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { releases, isLoading, refresh };
}
"""

# One object, two serialisations. Identical meaning, different token cost.
RELEASE_OBJ = {
    "release": {
        "version": "4.2.0",
        "publishedAt": "2026-09-02T09:15:00Z",
        "status": "shipped",
        "breakingChanges": 2,
        "changes": [
            {
                "id": "PR-1841",
                "category": "breaking",
                "title": "Rename the `onComplete` prop to `onFinish`",
                "author": "octocat",
            },
            {
                "id": "PR-1846",
                "category": "feature",
                "title": "Add offline queueing for release webhooks",
                "author": "octocat",
            },
            {
                "id": "PR-1852",
                "category": "fix",
                "title": "Stop retrying webhooks after a 410 response",
                "author": "monalisa",
            },
        ],
    }
}

JSON_MIN = json.dumps(RELEASE_OBJ, separators=(",", ":"), ensure_ascii=False)
JSON_PRETTY = json.dumps(RELEASE_OBJ, indent=2, ensure_ascii=False)

URLS = """\
https://github.com/saad-official/ai-engineering-journey/pull/1841
https://github.com/saad-official/ai-engineering-journey/pull/1846#issuecomment-2938471027
https://api.github.com/repos/saad-official/ai-engineering-journey/compare/v4.1.0...v4.2.0
https://ai.google.dev/gemini-api/docs/tokens?hl=en&utm_source=lab02&utm_medium=notes
https://console.groq.com/docs/rate-limits#tokens-per-minute
"""

# (label, text) - order matters only for readability of the printed table.
SAMPLES: list[tuple[str, str]] = [
    ("prose-en", PROSE_EN),
    ("prose-ur", PROSE_UR),
    ("code-ts", CODE_TS),
    ("json-min", JSON_MIN),
    ("json-pretty", JSON_PRETTY),
    ("urls", URLS),
]
