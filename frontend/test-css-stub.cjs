// Stand-in for a compiled CSS module: every class name resolves to its own key
// so rendered markup stays inspectable in tests without a bundler.
const classNames = new Proxy(
  {},
  {
    get(_target, property) {
      if (property === '__esModule') return true;
      if (property === 'default') return classNames;
      return typeof property === 'string' ? property : undefined;
    },
  },
);

module.exports = classNames;
