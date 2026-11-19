// SPDX-License-Identifier: GPL-3.0-only
// Prepare the same source-native synthetic responses used by the mobile trials.
import { nativeFixtureState } from '../../integrations/overmorrow/native-android-fixture.mjs';
const fixture = nativeFixtureState();
fixture.setPhase('initial');
process.stdout.write(JSON.stringify({weather: fixture.product(false), air: fixture.product(true)}));
