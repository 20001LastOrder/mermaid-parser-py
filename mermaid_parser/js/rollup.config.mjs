import commonjs from '@rollup/plugin-commonjs';
import resolve from '@rollup/plugin-node-resolve';
import MagicString from 'magic-string';


// override the sanitizeText function to avoid using DOMPurify,
// since it is not available on the server side
function patchSanitizeText() {
  // Matches the whole sanitizeText assignment you showed, even if Rollup adds __name$N
  const pattern = /var\s+sanitizeText\s*=\s*\/\*[\s\S]*?\*\/\s*__name\$\d*\s*\(\s*\(text\s*,\s*config2\)\s*=>\s*\{[\s\S]*?\}\s*,\s*["']sanitizeText["']\s*\)\s*;/m;

  return {
    name: 'patch-sanitize-text',
    renderChunk(code) {
      const match = code.match(pattern);
      if (!match) return null;

      const ms = new MagicString(code);
      const replacement =
        `var sanitizeText = /* @__PURE__ */ ((text, config2) => { return text; });`;
      ms.overwrite(match.index, match.index + match[0].length, replacement);

      return {
        code: ms.toString(),
        map: ms.generateMap({ hires: true })
      };
    }
  };
}


export default {
  input: 'parser.mjs',
  output: {
    file: 'parser.bundle.js',
    format: 'cjs',
    inlineDynamicImports: true,
  },
  plugins: [
    resolve({ browser: true, preferBuiltins: false }),
    commonjs(),
    patchSanitizeText(),
  ],
};