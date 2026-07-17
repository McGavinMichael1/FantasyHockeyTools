// Redirect CSS-module imports to a stub so Node's test runner can load compiled
// components. CSS modules are a bundler concern; under `node --test` they carry no
// styling, and their `.css` files are never emitted into `.test-build`.
const Module = require('node:module');
const path = require('node:path');

const stubPath = path.join(__dirname, 'test-css-stub.cjs');
const originalResolve = Module._resolveFilename;

Module._resolveFilename = function (request, ...rest) {
  if (typeof request === 'string' && request.endsWith('.css')) {
    return stubPath;
  }
  return originalResolve.call(this, request, ...rest);
};
