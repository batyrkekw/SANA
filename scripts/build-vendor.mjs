import { build } from 'esbuild';
await build({
  entryPoints: ['src/vendor.js'],
  outfile: 'dist/vendor/supabase.js',
  bundle: true,
  minify: true,
  format: 'esm',
  platform: 'browser',
  target: 'es2022',
  legalComments: 'linked',
});
