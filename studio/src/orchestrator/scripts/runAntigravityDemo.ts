import { resolve } from "node:path";

import { loadRuntimeConfig } from "../config/runtime.js";
import { runAntigravityReview } from "../providers/antigravity.js";

const config = loadRuntimeConfig();
const capsuleRelative = ".task-context/v2-demo/antigravity-review";
const result = await runAntigravityReview({
  executable: "/Users/kohalloran/.local/bin/agy",
  repositoryRoot: config.repositoryRoot,
  capsuleRoot: resolve(config.repositoryRoot, capsuleRelative),
  contextPaths: [
    `${capsuleRelative}/TASK.md`,
    `${capsuleRelative}/CONTRACT.ts`,
    `${capsuleRelative}/taskSummary.ts`,
    `${capsuleRelative}/implementation-notes.md`,
  ],
  scope: {
    readAllowlist: [`${capsuleRelative}/**`],
    readDenylist: [],
    writeAllowlist: [],
  },
  instructions: "Act as the independent reviewer. Follow TASK.md exactly and return only the requested review Markdown.",
  model: "gemini-3.7-flash-high",
});

console.log(JSON.stringify(result));
