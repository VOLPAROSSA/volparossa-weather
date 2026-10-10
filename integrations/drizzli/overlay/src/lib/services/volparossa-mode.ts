// SPDX-License-Identifier: GPL-3.0-only
// Compile-time opt-in; upstream provider behavior is unchanged in ordinary builds.
export const VOLPAROSSA_WEATHER = import.meta.env.VITE_VOLPAROSSA_WEATHER === '1';
