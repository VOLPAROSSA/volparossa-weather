// SPDX-License-Identifier: GPL-3.0-only
// New-source recipe only. Observations never authorize output or virtual code.
import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { relative, resolve } from 'node:path';

export default function sourceModuleGraph() {
  let root;
  let plugins;
  const normalize = (id) => {
    if (id.startsWith('\0')) return { id, kind: 'virtual', producer: null };
    const path = relative(root, id.split('?')[0]);
    if (path.startsWith('../') || path.startsWith('/')) throw new Error('SOURCE_GRAPH_EXTERNAL_MODULE');
    return { id: path + (id.includes('?') ? '?' + id.split('?').slice(1).join('?') : ''), kind: 'file' };
  };
  return {
    name: 'volparossa-source-module-graph-v1',
    enforce: 'post',
    configResolved(config) {
      root = resolve(config.root);
      plugins = config.plugins.map((plugin) => plugin.name);
    },
    generateBundle(options, bundle) {
      const outputs = Object.fromEntries(Object.entries(bundle).sort().map(([name, item]) => {
        if (item.type === 'asset') return [name, { type: 'asset', names: item.names ?? [], originalFileNames: item.originalFileNames ?? [] }];
        return [name, {
          type: 'chunk', isEntry: item.isEntry, isDynamicEntry: item.isDynamicEntry,
          imports: [...item.imports].sort(), dynamicImports: [...item.dynamicImports].sort(),
          facadeModuleId: item.facadeModuleId === null ? null : normalize(item.facadeModuleId),
          moduleIds: item.moduleIds.map(normalize),
          modules: Object.entries(item.modules).sort().map(([id, info]) => ({
            ...normalize(id), renderedLength: info.renderedLength, originalLength: info.originalLength,
            renderedExports: info.renderedExports, removedExports: info.removedExports,
          })),
        }];
      }));
      const raw = JSON.stringify({ schema: 1, kind: 'volparossa-drizzli-module-graph', admitted: false,
        format: options.format, plugins, outputs });
      if (Buffer.byteLength(raw) > 8 * 1024 * 1024) throw new Error('SOURCE_GRAPH_BOUND');
      const directory = resolve(root, '.volparossa-source-graphs');
      mkdirSync(directory, { recursive: true, mode: 0o700 });
      writeFileSync(resolve(directory, createHash('sha256').update(raw).digest('hex') + '.json'), raw + '\n', { flag: 'wx', mode: 0o600 });
    },
  };
}
