# React + TypeScript + Vite

## Local working demo

## M4 cartridge lab (no backend or credentials)

To review the three local synthetic fixture packets without configuring the
Mission Control proxy, run:

```bash
npm run dev:m4
```

Open `http://127.0.0.1:5173/lab/m4`. This exposes only the M4 local evidence
screen; it does not start a backend or make a cloud, customer-data, or plugin
claim.

## Full local working demo

Run the modern site, loopback-only demo identity, browser BFF, and a durable
control-plane snapshot together with one command:

```bash
npm run dev:demo -- --state /private/tmp/ztm-hitl-YYYYMMDD-a/synthetic-control-plane.json
```

Open the **Local demo UI** address printed by the command, choose **Sign in**,
then **Enter as local demo operator**. The launcher uses `5173` when it is
free and automatically selects another loopback port when it is occupied (for
example, by the M4 cartridge lab). The dashboard lists the exact runs in the
supplied state file; it does not fabricate progress or publish them as public
replays. The local demo credential is intentionally non-secret and is accepted
only while the Go server is explicitly bound to loopback in this development
profile.

## Firebase account setup

The production login uses Google Identity Platform through Firebase Auth. Set
the four `VITE_FIREBASE_*` public application values listed in `.env.example`
for the browser, and set the matching `MISSION_CONTROL_FIREBASE_PROJECT_ID` for
server-side ID-token verification. Google sign-in creates the Firebase user on
first successful authentication.

Do not add Firebase Admin credentials, service-account JSON, refresh tokens, or
cloud access keys to a `VITE_*` setting. Public recorded replays do not require
authentication. The production owner/admin designation and the future
self-service BYO-cloud switch remain deployment-controlled release gates.

For the combined Cloud Run image, durable Firestore state, invitation
policy, and deployment sequence, see
[`cloud_architecture/HOSTED_DRAFT.md`](../cloud_architecture/HOSTED_DRAFT.md).

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
