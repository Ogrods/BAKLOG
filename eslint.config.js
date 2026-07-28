import js from '@eslint/js';
import { importX } from 'eslint-plugin-import-x';
import globals from 'globals';

/** Weight/complexity guardrails - warnings until monolith splits land. */
const WEIGHT_RULES = {
  'max-lines': ['warn', { max: 1200, skipBlankLines: true, skipComments: true }],
  'max-lines-per-function': ['warn', { max: 120, skipBlankLines: true, skipComments: true }],
  complexity: ['warn', 25],
  'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
  // eslint-plugin-import does not peer-support ESLint 10; import-x does.
  'import-x/no-cycle': ['warn', { maxDepth: 4 }],
  // Legacy empty catch blocks - weight pass only; tighten later.
  'no-empty': 'off',
  'no-useless-escape': 'off',
};

export default [
  {
    ignores: [
      'node_modules/**',
      'dist/**',
      'vendor/**',
      'js/vendor/**',
      'profiles/**',
      'landing/**',
      'admin/**',
      'curated/**',
      'scripts/**',
      'tests/**',
    ],
  },
  js.configs.recommended,
  {
    files: ['js/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        ...globals.browser,
        Chart: 'readonly',
      },
    },
    plugins: { 'import-x': importX },
    rules: WEIGHT_RULES,
  },
];
