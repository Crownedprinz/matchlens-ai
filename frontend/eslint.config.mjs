import js from "@eslint/js";
import tsParser from "@typescript-eslint/parser";
import { FlatCompat } from "@eslint/eslintrc";
const compat = new FlatCompat({ baseDirectory: import.meta.dirname });
export default [...compat.extends("next/core-web-vitals"), js.configs.recommended, { files:["**/*.{ts,tsx}"], languageOptions:{parser:tsParser,parserOptions:{ecmaFeatures:{jsx:true}},globals:{React:"readonly",fetch:"readonly",setInterval:"readonly",clearInterval:"readonly",console:"readonly"}},rules:{"no-unused-vars":"off","no-undef":"off","react/no-unescaped-entities":"off"} }];
