// SPDX-License-Identifier: GPL-3.0-only
/// This build profile never selects an upstream weather fallback.
const volparossaProfile = bool.fromEnvironment('VOLPAROSSA_WEATHER');
const volparossaNativeOrigin = String.fromEnvironment('VOLPAROSSA_CORE_ORIGIN');
