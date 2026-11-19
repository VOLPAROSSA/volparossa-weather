// SPDX-License-Identifier: GPL-3.0-only
import { constants } from 'node:fs';
import { open } from 'node:fs/promises';
import { requireThat } from './forecast.mjs';

export async function readBytes(path, limit) {
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const stat = await file.stat();
    requireThat(stat.isFile() && stat.size > 0 && stat.size <= limit, 'VERIFICATION_FILE_INVALID');
    const bytes = Buffer.alloc(stat.size + 1);
    let offset = 0;
    while (offset < bytes.length) {
      const { bytesRead } = await file.read(bytes, offset, bytes.length - offset, offset);
      if (bytesRead === 0) break;
      offset += bytesRead;
    }
    requireThat(offset === stat.size, 'VERIFICATION_FILE_INVALID');
    return bytes.subarray(0, offset);
  } finally { await file.close(); }
}
