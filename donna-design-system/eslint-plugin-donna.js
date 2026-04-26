/**
 * DONNA · custom ESLint rules
 *
 * Drop into your ESLint config:
 *   plugins: ['donna'],
 *   rules: {
 *     'donna/no-raw-hex': 'error',
 *     'donna/no-inline-font-size': 'error',
 *     'donna/no-inline-box-shadow': 'error',
 *     'donna/no-arbitrary-tailwind': 'error',
 *     'donna/no-italic-class': 'error',
 *   }
 *
 * These catch the most common violations Claude Code makes when building fast.
 */

const HEX_REGEX = /#[0-9A-Fa-f]{3,8}\b/;
const PX_SIZE_REGEX = /\b(font-size|fontSize)\s*[:=]\s*['"]?(\d+)(px|rem|em)/;
const ARBITRARY_TW_REGEX = /\b(text|bg|border|shadow|font|p|m|gap|w|h)-\[[^\]]+\]/;
// Italic allowed only via the three approved classes:
const ALLOWED_ITALIC = new Set([
  'italic-accent-heading',
  'italic-accent-inline',
  'italic-accent-memory',
]);

module.exports = {
  rules: {
    'no-raw-hex': {
      meta: {
        type: 'problem',
        docs: { description: 'Disallow raw hex colors in JSX/TS. Use a token.' },
        messages: { rawHex: 'Donna: raw hex "{{hex}}" found. Use a token from tokens.css.' },
      },
      create(context) {
        return {
          Literal(node) {
            if (typeof node.value !== 'string') return;
            const match = node.value.match(HEX_REGEX);
            if (match) {
              context.report({ node, messageId: 'rawHex', data: { hex: match[0] } });
            }
          },
          TemplateElement(node) {
            const match = node.value.raw.match(HEX_REGEX);
            if (match) {
              context.report({ node, messageId: 'rawHex', data: { hex: match[0] } });
            }
          },
        };
      },
    },

    'no-inline-font-size': {
      meta: {
        type: 'problem',
        docs: { description: 'Disallow inline font-size. Use type-* classes.' },
        messages: { inlineSize: 'Donna: inline font-size is forbidden. Use a type role (type-h1, type-body, etc.).' },
      },
      create(context) {
        return {
          JSXAttribute(node) {
            if (node.name.name !== 'style') return;
            const sourceCode = context.getSourceCode().getText(node);
            if (PX_SIZE_REGEX.test(sourceCode)) {
              context.report({ node, messageId: 'inlineSize' });
            }
          },
        };
      },
    },

    'no-inline-box-shadow': {
      meta: {
        type: 'problem',
        docs: { description: 'Disallow inline box-shadow. Shadows exist only on modal/toast/popover.' },
        messages: { inlineShadow: 'Donna: inline box-shadow is forbidden. Use shadow-modal / shadow-toast / shadow-popover tokens, or none.' },
      },
      create(context) {
        return {
          JSXAttribute(node) {
            if (node.name.name !== 'style') return;
            const sourceCode = context.getSourceCode().getText(node);
            if (/box-?[sS]hadow/.test(sourceCode)) {
              context.report({ node, messageId: 'inlineShadow' });
            }
          },
        };
      },
    },

    'no-arbitrary-tailwind': {
      meta: {
        type: 'problem',
        docs: { description: 'Disallow Tailwind arbitrary values (the palette is closed).' },
        messages: { arbitrary: 'Donna: arbitrary Tailwind value "{{value}}" is forbidden. The palette/scale is closed.' },
      },
      create(context) {
        return {
          JSXAttribute(node) {
            if (node.name.name !== 'className' && node.name.name !== 'class') return;
            if (!node.value || node.value.type !== 'Literal') return;
            const match = node.value.value.match(ARBITRARY_TW_REGEX);
            if (match) {
              context.report({ node, messageId: 'arbitrary', data: { value: match[0] } });
            }
          },
        };
      },
    },

    'no-italic-class': {
      meta: {
        type: 'problem',
        docs: { description: 'Italic is allowed only via three approved classes.' },
        messages: {
          unauthorized: 'Donna: italic is allowed only via italic-accent-heading, italic-accent-inline, or italic-accent-memory.',
        },
      },
      create(context) {
        return {
          JSXAttribute(node) {
            if (node.name.name !== 'className' && node.name.name !== 'class') return;
            if (!node.value || node.value.type !== 'Literal') return;
            const classes = node.value.value.split(/\s+/);
            for (const cls of classes) {
              if (cls === 'italic' || cls.startsWith('italic-')) {
                if (!ALLOWED_ITALIC.has(cls)) {
                  context.report({ node, messageId: 'unauthorized' });
                  break;
                }
              }
            }
          },
        };
      },
    },
  },
};
