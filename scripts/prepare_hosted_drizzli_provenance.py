#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""P14 data checks for four source-derived producers and actual output notices.

No observed hash authorizes code. The observer must enforce the selected loader,
native dispatch, fixed source bytes and transform ordering during compilation.
This parent-side validator binds those receipts to the unchanged package record,
the complete installed archive maps and the files actually left by the adapter.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = '34e3f5cc135d0fec7f0d9837e30413f1a151037b1568911f074048bf941d68e5'
KIT_HOOK = '42da1ec046c9e229f91a2ed83d7f149768231f40f968815c0f7e361a0b66011f'
VITE_HOOK = 'e5cb966ffeb7afe04daa03dfc138efe233ae02dec2060ca731072cb5bc35b376'
ENVIRONMENTS = {
    'ssr': dict(name='ssr', consumer='server', ssr=True, base='/', platform='node'),
    'client': dict(name='client', consumer='client', ssr=False, base='./', platform='browser'),
}
# Derived inertly from the approved archive literals/configuration, before a run.
SOURCES = {
    '\0virtual:__sveltekit/env': ('sveltekit', 'vite-plugin-sveltekit-virtual-modules', KIT_HOOK,
        'kit-load', 359, '3d31b247580a8cd7a2d8db9ba1461d86d1f3fd8771f888fdce12280895349eb5'),
    '\0virtual:__sveltekit/server': ('sveltekit', 'vite-plugin-sveltekit-virtual-modules', KIT_HOOK,
        'kit-load', 195, '044ba569e5e503525a22977de015f67c0bc3f6f5deb1f9cf8a5dfec7b4487904'),
    '\0vite/preload-helper.js': ('vite', 'builtin:vite-build-import-analysis', VITE_HOOK,
        'native-dispatch', 2198, 'a4a1c9fde4f431ffef7ef93071a0c5d554b9a5b395854243ff982a880b726a7a'),
}
RUNTIME = '\0rolldown/runtime.js'
RUNTIME_CODES = {
    'ssr': (3823, '6389c99520e98b0f839779e28a31bd13ea03d6177707348822d88cc0f5887a03'),
    'client': (4405, '2027378d81078b5bb25f18920376547f296bebd7be04bd10dc2e0221a5aa0991'),
}
PRODUCERS = {'sveltekit': ('@sveltejs/kit', '2.70.1'), 'vite': ('vite', '8.3.1'),
    'rolldown': ('rolldown', '1.2.11')}
SUPPLEMENT = {
    ('vite', 'LICENSE.md'): (112425, '387dd7baa307083401a27c58c362c30832f5ba1dba84f10cc22c33401523f45c'),
    ('rolldown', 'LICENSE'): (1302, '23ecfff35a5a2e80d92142f75228912c3b1abc4b5a8337a821ff4397e2f9f734'),
    ('rolldown', 'THIRD-PARTY-LICENSE'): (2209, 'a877291d800ed43692f3f9ae09d8e01cc6f7293ad39d43896059c188ffbb8b7c'),
    ('urlpattern-polyfill', 'LICENSE'): (1074, 'c7b9df332d06b323d491f98324dba24ed5b325161b081fab46e538dcb89bde81'),
}
CSS_INPUT = ('src/routes/layout.css',
    'f824dc020ec4ef5e560a3c1fc963408eed9c6cab4b956ed31323878c599ca783')
CSS_OWNERS = ('tailwindcss', 'tw-animate-css')
STATIC = ('_headers', 'app.webmanifest', 'favicon.svg', 'icons/icon-180.png',
    'icons/icon-192.png', 'icons/icon-512.png', 'icons/icon-maskable-512.png', 'robots.txt')
HTML = ('index.html', 'en/weather/week/index.html')


def require(ok, code):
    if not ok:
        raise ValueError(code)


def digest_record(value):
    return (type(value) is dict and type(value.get('bytes')) is int and value['bytes'] >= 0
        and type(value.get('sha256')) is str and re.fullmatch('[0-9a-f]{64}', value['sha256']) is not None)


def identity(value):
    return {key: value[key] for key in ('bytes', 'sha256')}


def notices(inputs, archives=None):
    """Fixed original texts; an arbitrary supplemental component cannot enter."""
    contract = inputs.document(inputs.read(ROOT / 'integrations/drizzli/output-notices-v1.json'))
    require(type(contract) is dict and set(contract) == {'schema', 'kind', 'admitted', 'notices'}
        and contract['schema'] == 1 and contract['kind'] == 'p14-drizzli-supplemental-notices'
        and contract['admitted'] is False and type(contract['notices']) is list, 'P14_NOTICE_CONTRACT')
    approved = inputs.load_package_inputs('drizzli')['dependencies']['packages']
    found, result = set(), {}
    for item in contract['notices']:
        require(type(item) is dict and set(item) == {'package', 'version', 'integrity', 'archive',
            'member', 'bytes', 'sha256', 'source', 'output'}, 'P14_NOTICE_RECORD')
        key = (item['package'], item['member'])
        require(key in SUPPLEMENT and key not in found, 'P14_NOTICE_PRODUCER')
        found.add(key)
        entry = approved['node_modules/' + item['package']]
        require(item['version'] == entry['input']['version'] and item['integrity'] == entry['input']['integrity']
            and item['archive'] == entry['archive'], 'P14_NOTICE_PACKAGE_BINDING')
        size, checksum = SUPPLEMENT[key]
        source = 'third_party/client-notices/p14-drizzli/' + item['package'] + '-' + item['member']
        require(item['source'] == source and item['output'] == 'VOLPAROSSA-NOTICES/' + Path(source).name
            and (item['bytes'], item['sha256']) == (size, checksum), 'P14_NOTICE_SOURCE_BINDING')
        raw = inputs.read(ROOT / source, 128 * 1024)
        raw.decode('utf-8')
        require(len(raw) == size and inputs.sha(raw) == checksum, 'P14_NOTICE_CHANGED')
        if archives is not None:
            archive = archives['node_modules/' + item['package']]
            member = archive['archive']['files'].get(item['member'], {})
            require(archive['input'] == entry['input'] and member.get('type') == 'file'
                and member.get('bytes') == size and member.get('sha256') == checksum,
                'P14_NOTICE_ARCHIVE_BINDING')
        result[item['output']] = dict(raw=raw, **item)
    require(found == set(SUPPLEMENT), 'P14_NOTICE_MISSING')
    return result


def expected_virtual(identifier, environment):
    require(identifier in SOURCES or identifier == RUNTIME, 'UNREVIEWED_VIRTUAL_MODULE')
    if identifier == RUNTIME:
        size, checksum = RUNTIME_CODES[environment]
        producer, plugin, hook, kind = 'rolldown', 'rolldown-runtime-module-task', None, 'runtime-task'
    else:
        producer, plugin, hook, kind, size, checksum = SOURCES[identifier]
        require((producer == 'sveltekit' and environment == 'ssr')
            or (producer == 'vite' and environment == 'client'), 'P14_VIRTUAL_CONTEXT')
    return dict(id=identifier, producer=producer, plugin=plugin, hook_sha256=hook,
        load=dict(kind=kind, bytes=size, sha256=checksum), transformed=dict(bytes=size, sha256=checksum),
        native_member_sha256=NATIVE if producer in ('rolldown', 'vite') else None)


def graph_closure(inputs, graphs, archives):
    """Conservatively retain notices for every file owner, including zero JS bytes.

    CSS imports are checked separately below. This preserves the original target,
    inactive, longest-package-prefix, version and SRI checks and strengthens the
    member existence and all-reference virtual checks for this P14 path only.
    """
    require(type(graphs) is list and len(graphs) == 2, 'P14_GRAPH_COUNT')
    approved = inputs.load_package_inputs('drizzli')['dependencies']['packages']
    original, bundle = inputs.notice_inputs()
    supplemental = notices(inputs, archives)
    components, needed, environments, virtuals, files = set(), {}, set(), set(), set()

    def component(name, package=None):
        if package is None:
            entry = approved['node_modules/' + name]
            package = archives.get('node_modules/' + name)
            require(package is not None and package['input'] == entry['input'], 'P14_PRODUCER_PACKAGE_BINDING')
        pin = package['input']
        require(inputs.npm_target_selection(pin)['included'], 'EXCLUDED_NPM_MODULE_PRESENT')
        require(not package.get('inactive') and not pin.get('inactive_optional_data'), 'INACTIVE_NPM_MODULE_CONTRIBUTION')
        owner = original['npm']['components'].get(name)
        if owner is not None:
            require(owner['version'] == pin['version'] and owner['integrity'] == pin['integrity']
                and owner['notices'], 'UNRESOLVED_RUNTIME_NOTICE')
            for checksum in owner['notices']:
                record = original['npm']['records'][checksum]
                needed[checksum] = bundle[record['offset']:record['offset'] + record['bytes']]
        else:
            records = [item for item in supplemental.values() if item['package'] == name
                and item['version'] == pin['version'] and item['integrity'] == pin['integrity']]
            require(records, 'UNRESOLVED_RUNTIME_NOTICE')
            for item in records:
                needed[item['sha256']] = item['raw']
        components.add(name)

    for name, version in PRODUCERS.values():
        require(approved['node_modules/' + name]['input']['version'] == version, 'P14_PRODUCER_VERSION')
        component(name)
    native = archives.get('node_modules/@rolldown/binding-linux-x64-gnu')
    require(native is not None and native['input'] == approved['node_modules/@rolldown/binding-linux-x64-gnu']['input']
        and native['input']['version'] == '1.2.11'
        and native['archive']['files'].get('rolldown-binding.linux-x64-gnu.node', {}).get('sha256') == NATIVE,
        'P14_NATIVE_BINDING')
    for graph in graphs:
        require(type(graph) is dict and set(graph) == {'schema', 'kind', 'admitted', 'format', 'plugins',
            'environment', 'virtualModules', 'outputs'} and type(graph['schema']) is int and graph['schema'] == 2
            and graph['kind'] == 'volparossa-drizzli-module-graph' and graph['admitted'] is False
            and graph['format'] == 'es' and type(graph['plugins']) is list
            and all(type(p) is str and len(p) <= 256 for p in graph['plugins'])
            and type(graph['outputs']) is dict and 0 < len(graph['outputs']) <= 8192, 'P14_GRAPH_SCHEMA')
        environment = graph['environment']
        require(type(environment) is dict and environment.get('name') in ENVIRONMENTS
            and environment == ENVIRONMENTS[environment['name']] and type(environment['ssr']) is bool,
            'P14_GRAPH_ENVIRONMENT')
        context = environment['name']
        require(context not in environments, 'P14_GRAPH_AMBIGUOUS_ENVIRONMENT')
        environments.add(context)
        require(type(graph['virtualModules']) is list and len(graph['virtualModules']) <= 4, 'P14_VIRTUAL_RECEIPTS')
        receipts, used = {}, set()
        for item in graph['virtualModules']:
            require(type(item) is dict and type(item.get('id')) is str, 'P14_VIRTUAL_RECEIPT')
            identifier = item['id']
            require(identifier not in receipts, 'P14_AMBIGUOUS_VIRTUAL_PRODUCER')
            require(item == expected_virtual(identifier, context), 'P14_VIRTUAL_PRODUCER_OR_CODE_CHANGED')
            receipts[identifier] = item

        def reference(value):
            require(type(value) is dict and value.get('kind') in ('file', 'virtual')
                and type(value.get('id')) is str and len(value['id']) <= 8192, 'GRAPH_MODULE')
            identifier = value['id']
            if value['kind'] == 'virtual':
                expected = expected_virtual(identifier, context)
                require(identifier in receipts and value.get('producer') == expected['producer'], 'P14_UNBOUND_VIRTUAL_REFERENCE')
                used.add(identifier)
                virtuals.add(identifier)
                return
            path = identifier.split('?', 1)[0]
            inputs.safe_path(path)
            files.add(path)
            if path.startswith('node_modules/'):
                matches = [prefix for prefix in approved if path.startswith(prefix + '/')]
                require(matches, 'UNLOCKED_OUTPUT_MODULE')
                prefix = max(matches, key=len)
                package = archives.get(prefix)
                require(package is not None and package['input'] == approved[prefix]['input'], 'P14_OUTPUT_PACKAGE_BINDING')
                require(package['archive']['files'].get(path[len(prefix) + 1:], {}).get('type') == 'file', 'P14_OUTPUT_MODULE_MEMBER')
                component(package['input']['name'], package)

        for name, output in graph['outputs'].items():
            inputs.safe_path(name)
            require(type(output) is dict and output.get('type') in ('chunk', 'asset') and digest_record(output), 'P14_GRAPH_OUTPUT')
            if output['type'] == 'asset':
                continue
            require(type(output.get('modules')) is list and len(output['modules']) <= 100000
                and type(output.get('moduleIds')) is list and len(output['moduleIds']) <= 100000, 'GRAPH_MODULE_BOUND')
            if output.get('facadeModuleId') is not None:
                reference(output['facadeModuleId'])
            for item in output['moduleIds']:
                reference(item)
            for item in output['modules']:
                require(type(item) is dict and type(item.get('renderedLength')) is int
                    and item['renderedLength'] >= 0, 'GRAPH_MODULE')
                require((item.get('rendered_sha256') is None and item.get('rendered_bytes') is None)
                    or digest_record(dict(sha256=item.get('rendered_sha256'), bytes=item.get('rendered_bytes'))), 'P14_RENDERED_MODULE')
                require(item.get('kind') != 'virtual' or item.get('rendered_sha256') is not None,
                    'P14_VIRTUAL_RENDERED_CODE_MISSING')
                reference(item)
        require(used == set(receipts), 'P14_UNUSED_OR_MISSING_VIRTUAL_RECEIPT')
    require(environments == set(ENVIRONMENTS) and virtuals == set(SOURCES) | {RUNTIME}, 'P14_VIRTUAL_SET')
    for name in CSS_OWNERS:
        component(name)
    return dict(notices=needed, components=sorted(components), virtual_modules=sorted(virtuals),
        file_modules=sorted(files), supplemental=supplemental)


def output_closure(inputs, stage, output_map, source_seal, notice_records, graphs, closure):
    """Cover every distributed path; intermediate SSR files are not distribution.

    JS/CSS are byte-bound to the client graph. Static files must be exact sealed
    source copies. Only the two reviewed Kit-generated HTML paths and Kit version
    data are allowed in addition to original distribution notices. No arbitrary
    copied asset, font or HTML prefix is accepted.
    """
    require(source_seal.get(CSS_INPUT[0], {}).get('sha256') == CSS_INPUT[1], 'P14_CSS_INPUT_CHANGED')
    original, bundle = inputs.notice_inputs()
    original_notices = {
        'LICENSE.DRIZZLI': source_seal.get('LICENSE'),
        'LICENSE.VOLPAROSSA': source_seal.get('LICENSE.VOLPAROSSA'),
        'npm-originals.txt': dict(bytes=len(bundle), sha256=inputs.sha(bundle)),
        'message-format.LICENSE': source_seal.get('volparossa-build-plugins/message-format.LICENSE'),
        'm-function-matcher.LICENSE': source_seal.get('volparossa-build-plugins/m-function-matcher.LICENSE'),
    }
    expected_names = set(original_notices) | {Path(path).name for path in closure['supplemental']}
    require(set(notice_records) == expected_names and all(expected is not None
        and identity(notice_records[name]) == identity(expected) for name, expected in original_notices.items()),
        'P14_REQUIRED_ORIGINAL_NOTICE_MISSING')
    client = next(graph for graph in graphs if graph['environment']['name'] == 'client')
    covered, kinds = set(), {}
    for name, output in client['outputs'].items():
        if name not in output_map:
            # Kit keeps its Vite manifest as an intermediate, outside distribution.
            require(name == '.vite/manifest.json', 'P14_CLIENT_OUTPUT_MISSING')
            continue
        require(name.endswith(('.js', '.css')) or name == '_app/version.json', 'P14_UNREVIEWED_BUNDLE_ASSET')
        require(identity(output_map[name]) == identity(output), 'P14_OUTPUT_GRAPH_BYTES_CHANGED')
        covered.add(name)
        kinds[name] = 'client-module-graph'
    for name in STATIC:
        expected = source_seal.get('static/' + name)
        require(expected is not None and name in output_map and identity(output_map[name]) == identity(expected), 'P14_STATIC_OUTPUT_CHANGED')
        covered.add(name)
        kinds[name] = 'sealed-drizzli-static-copy'
    for name in HTML:
        require(name in output_map, 'P14_HTML_OUTPUT_MISSING')
        raw = inputs.read(stage / 'build' / name, 16 * 1024**2)
        raw.decode('utf-8')
        require(inputs.sha(raw) == output_map[name]['sha256'] and b'<html' in raw.lower()
            and b'</html>' in raw.lower(), 'P14_HTML_OUTPUT_CHANGED')
        covered.add(name)
        kinds[name] = 'kit-reviewed-ssr-prerender' if name != 'index.html' else 'kit-reviewed-ssr-fallback'
    name = '_app/version.json'
    require(name in output_map, 'P14_VERSION_OUTPUT_MISSING')
    version = inputs.document(inputs.read(stage / 'build' / name, 1024))
    require(version == {'version': 'd2a6839e2b3f2e561b849d83014fc5959bed39cc'}
        and identity(output_map[name]) == dict(bytes=54,
            sha256='2c0cc88ecd8923672749361be76efb816897aa2b818e126591bfb25317747b56'),
        'P14_VERSION_OUTPUT_CHANGED')
    covered.add(name)
    kinds[name] = 'kit-fixed-source-version-data'
    for name, record in notice_records.items():
        path = 'VOLPAROSSA-NOTICES/' + name
        require(path in output_map and identity(output_map[path]) == identity(record), 'P14_OUTPUT_NOTICE_MISSING')
        covered.add(path)
        kinds[path] = 'original-distribution-notice'
    for path, record in closure['supplemental'].items():
        require(path in output_map and identity(output_map[path]) == identity(record), 'P14_OUTPUT_NOTICE_MISSING')
        covered.add(path)
        kinds[path] = 'original-distribution-notice'
    require(covered == set(output_map), 'P14_UNCOVERED_DISTRIBUTED_OUTPUT')
    return dict(complete=True, files=kinds, files_count=len(covered),
        components=closure['components'], css_source_owners=list(CSS_OWNERS),
        virtual_producers=['@sveltejs/kit@2.70.1', 'vite@8.3.1', 'rolldown@1.2.11'],
        html_provenance='sealed-app-template-and-source; reviewed-kit-ssr-graph-prerender-fallback; adapter-static-copy',
        intermediate_ssr_is_distribution=False, independent_reproduction=False,
        scope='actual-candidate-output-and-required-original-notices; no product or release admission')
