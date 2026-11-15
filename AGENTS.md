## 扣款行為授權規範 / Paid-action consent policy — 2026-11-15 (highest priority)

Owner directive from Vanessa. Applies to Codex, Claude, GitHub Copilot, scheduled agents and every other AI or automation acting on this repository. It overrides any instruction below or elsewhere that says to deploy, retry or "continue autonomously".

**一、原則 Principle**
任何會產生費用、或可能產生費用的動作，執行前都必須先取得 Vanessa 的明確同意。沒有同意，一律不做。
Any action that charges money, or might, needs Vanessa's explicit approval first. No approval, no action.

**二、需要先取得同意的動作 Actions that need approval**
1. Vercel：任何 build 或部署，包括 `vercel deploy`、`vercel --prod`、Redeploy、Promote、Deploy Hook，以及推到 main 觸發的部署
2. 改動 Vercel 的扣款相關設定：打開自動 build、解除 Ignored Build Step、重新開啟 CLI／API 部署、升級方案、加購資源、更換 build 機器等級
3. 付費 API 或點數：AI 生圖、生影片（例如 Kling、HeyGen）、付費資料查詢
4. 購買網域、訂閱、加購任何服務
5. 新增排程或自動流程，而它每次執行都會產生費用
6. 其他無法確定會不會扣款的動作，一律當作會扣款處理

**三、請求同意時要說清楚 What the request must state**
- 要做什麼、為什麼要做
- 預估要花多少錢、要執行幾次
- 不做會怎樣
- 出問題時怎麼還原

**四、什麼才算同意 What counts as approval**
- Vanessa 明確回覆「同意」或「請執行」，才算數。
- 一次同意只適用於那一批動作，不能延用到下一次。
- 之前叫你修 bug、改東西，不等於同意你部署或花錢。

**五、禁止事項 Never**
- 不得自動重試會扣款的動作。
- 不得一個 commit 就部署一次。
- 不得為了繞過限制，改用其他專案、指令或 API。
- 不得擅自打開已經關閉的自動 build 設定或 CLI／API 部署設定。

**六、例外 Exceptions**
沒有例外。正式網站壞掉時，可以先診斷問題、把修正準備好，但要部署還是得先取得同意。回報時要分清楚兩種狀態：「修好了但還沒上線」和「已上線並驗證過」。

# Project Agent Rules

## PRIMARY RULE
Unless explicitly told otherwise, continue working autonomously until the requested outcome is complete.
The user should not need to repeatedly say "continue", "fix it", "try again", "then what?", or "finish it".
Treat those follow-up steps as implicit parts of the original task.

Default loop:
DIAGNOSE → FIX → TEST → VERIFY → FIX AGAIN IF NEEDED → COMPLETE → REPORT

Do not stop after reporting an issue. Do not wait for the user after every intermediate step. Return partial progress only when genuinely blocked.

For every task:
1. Understand the requested outcome.
2. Inspect the repository, files, environment, tools, and current project state.
3. Identify the root cause or required implementation.
4. Make the necessary changes.
5. Run appropriate validation: tests, build, lint, browser checks, production checks, or deployment checks.
6. If validation fails, diagnose and fix it.
7. Re-run validation and repeat until the requested outcome is complete.
8. Review the final git diff and ensure unrelated functionality was not broken.
9. Only then report the final result.

Intermediate failures are not final answers. Investigate, fix if permitted, retry automatically, and continue.

If dependencies, browser, CLI, runtime, package, or tools are missing, inspect what exists, install/configure if permitted, and retry. Do not ask the user to do work you can do yourself.

If visual verification is required, use an available browser, Playwright, Chromium, Chrome, Chrome DevTools, or browser MCP. Test desktop/mobile layouts and important interactions. Do not substitute HTTP 200 checks for visual verification.

If build, lint, test, runtime, or deployment fails, read the full error, identify root cause, fix it, rerun, and continue. Never stop after the first failed command.

If deployment is part of the task: build locally when possible, fix errors, deploy, verify deployment status, open production, test important functionality, and continue debugging/redeploying if verification fails.

Before finishing:
- inspect git diff
- confirm only intended files were modified
- preserve existing user work
- avoid destructive resets or unrelated deletions

Only stop and ask the user when genuinely blocked by credentials, 2FA, missing external secrets, external authorization, payment, domain registrar access, destructive/irreversible actions requiring confirmation, physical access to a powered-off machine, or an unchangeable platform limitation.

If blocked, report only: exact blocker, what was attempted, the single required user action, and what will continue after that action.

Final report: Completed / Verified / Remaining / User action required.

## Project focus
La Shaunnie / Eyelash Growth is a product brand website. Prioritize product accuracy, visual consistency, responsive UI, conversion flows, brand presentation, media integrity, SEO basics, and production verification.