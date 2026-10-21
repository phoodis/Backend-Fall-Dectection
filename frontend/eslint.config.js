import globals from 'globals'
import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'

// Plain flat-config array, not the `defineConfig`/`globalIgnores` helpers from
// `eslint/config` -- those, and @vue/eslint-config-prettier (originally imported
// here too), only exist in ESLint 9+/were never actually installed, while this
// project pins eslint ^8.49 (eslint.config.js support since 8.21, stable without
// those helpers). The config as originally written could never run at all --
// `npm run lint` wasn't even a defined script -- so this had never once
// successfully linted the project.
export default [
  {
    name: 'app/files-to-lint',
    files: ['**/*.{js,mjs,jsx,vue}'],
  },
  {
    ignores: ['**/dist/**', '**/dist-ssr/**', '**/coverage/**'],
  },
  {
    languageOptions: {
      globals: {
        ...globals.browser,
      },
    },
  },
  js.configs.recommended,
  ...pluginVue.configs['flat/essential'],
]
