# SPDX-License-Identifier: GPL-3.0-only
"""Configure the staged, upstream iOS app for the pinned Flutter simulator build."""
import hashlib
from pathlib import Path
import plistlib
import sys


def original(path, sha):
    raw = path.read_bytes()
    if path.is_symlink() or hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError(f"unexpected iOS input {path.name}")
    return raw


def prepare(stage, flutter):
    ios = stage / 'ios'
    project = ios / 'Runner.xcodeproj/project.pbxproj'
    framework = ios / 'Flutter/AppFrameworkInfo.plist'
    settings = ios / 'Runner/Info.plist'
    project_bytes = original(project, '7519814f06f7e88fd86521adb981e5d729156bb2733d4c5f899aee291a726a0b')
    framework_config = plistlib.loads(original(framework, '4844be22b72d16d6f6013ce5a2240728c730ef1fef9cf43a5c55198b18614802'))
    app_config = plistlib.loads(original(settings, '1f49139d04a8031003469f1dc7a2efdb89abe6305f669f2b7b8dc4ed73c9aef1'))
    template = original(flutter / 'packages/flutter_tools/templates/cocoapods/Podfile-ios',
                        'db2da28b10a5ac3ed5d42dbf7208ece60fc886bd1f86f14335dde4037ba32350')
    assert project_bytes.count(b'IPHONEOS_DEPLOYMENT_TARGET = 12.0;') == 3
    assert framework_config['MinimumOSVersion'] == '12.0' and 'NSAppTransportSecurity' not in app_config
    assert template.count(b"# platform :ios, '13.0'") == 1
    # home_widget and workmanager_apple require iOS 14. Preserve the upstream
    # Runner/Flutter target and plugin registration. The simulator uses the
    # regular app entry point and only 127.0.0.1 is admitted for cleartext.
    with (ios / 'Podfile').open('xb') as output:
        output.write(template.replace(b"# platform :ios, '13.0'", b"platform :ios, '14.0'"))
    project.write_bytes(project_bytes.replace(b'IPHONEOS_DEPLOYMENT_TARGET = 12.0;', b'IPHONEOS_DEPLOYMENT_TARGET = 14.0;'))
    framework_config['MinimumOSVersion'] = '14.0'
    framework.write_bytes(plistlib.dumps(framework_config))
    app_config['NSAppTransportSecurity'] = {'NSExceptionDomains': {'127.0.0.1': {'NSExceptionAllowsInsecureHTTPLoads': True}}}
    settings.write_bytes(plistlib.dumps(app_config))


if __name__ == '__main__':
    prepare(Path(sys.argv[1]), Path(sys.argv[2]))
