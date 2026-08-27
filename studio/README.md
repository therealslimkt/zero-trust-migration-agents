# React + TypeScript + Vite

## Local working demo

Run the modern site, loopback-only demo identity, browser BFF, and a durable
control-plane snapshot together with one command:

```bash
npm run dev:demo -- --state /private/tmp/ztm-hitl-YYYYMMDD-a/synthetic-control-plane.json
```

Open `http://127.0.0.1:5173`, choose **Sign in**, then **Enter as local demo
operator**. The dashboard lists the exact runs in the supplied state file; it
does not fabricate progress or publish them as public replays. The local demo
credential is intentionally non-secret and is accepted only while the Go
server is explicitly bound to loopback in this development profile.

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
