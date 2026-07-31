import js from "@eslint/js";
import globals from "globals";
export default [
  { files: ["src/**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2024, sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser, ...globals.es2024 } },
    rules: { "no-undef": "error", "no-redeclare": "error",
      "no-unused-vars": ["warn", { varsIgnorePattern: "^React$" }] } },
];
