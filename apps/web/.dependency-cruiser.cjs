/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
    {
      name: 'no-circular',
      severity: 'error',
      comment: 'Circular dependencies are forbidden',
      from: {},
      to: { circular: true },
    },
    {
      name: 'ui-no-domain',
      severity: 'error',
      comment: 'UI primitives (components/ui/) must not import from domain logic',
      from: { path: '^src/components/ui/' },
      to: {
        path: '^src/lib/(api|domain-states|server-clock)',
      },
    },
    {
      name: 'no-cross-app-import',
      severity: 'error',
      comment: 'No importing from other apps directly — use packages/contracts',
      from: { path: '^src/' },
      to: { path: '^../../apps/' },
    },
    {
      name: 'components-no-direct-fetch',
      severity: 'error',
      comment: 'Components must not import fetch polyfills — use src/lib/api/ instead. Global fetch enforced by ESLint no-restricted-globals.',
      from: { path: '^src/components/' },
      to: { path: 'node_modules/(node-fetch|cross-fetch|isomorphic-fetch|whatwg-fetch)' },
    },
    {
      name: 'components-no-lib-api',
      severity: 'error',
      comment: 'Components must not call lib/api/ directly — data flows in via props from Server Components',
      from: { path: '^src/components/' },
      to: { path: '^src/lib/api' },
    },
  ],
  options: {
    doNotFollow: {
      path: 'node_modules',
    },
    tsPreCompilationDeps: true,
    tsConfig: {
      fileName: './tsconfig.json',
    },
    enhancedResolveOptions: {
      exportsFields: ['exports'],
      conditionNames: ['import', 'require', 'node', 'default'],
    },
    reporterOptions: {
      dot: {
        collapsePattern: 'node_modules/[^/]+',
      },
    },
  },
}
