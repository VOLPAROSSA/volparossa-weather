// SPDX-License-Identifier: GPL-3.0-only
// Prime the trial with the original envelope produced by the normal content
// publish CLI, using the same store method as a completed named download.
use std::{
    env,
    error::Error,
    fs,
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

use ed25519_dalek::VerifyingKey;
use volparossa_content::{CacheLimits, ChunkStore, SignedManifest};

fn main() -> Result<(), Box<dyn Error>> {
    let [cache, manifest, publisher] =
        <[String; 3]>::try_from(env::args().skip(1).collect::<Vec<_>>())
            .map_err(|_| "expected cache, signed manifest and trusted public key")?;
    let signed = SignedManifest::decode(&fs::read(manifest)?)?;
    let key = VerifyingKey::from_bytes(
        &hex::decode(publisher)?
            .try_into()
            .map_err(|_| "publisher key length")?,
    )?;
    let mut store = ChunkStore::open(
        Path::new(&cache),
        CacheLimits {
            max_bytes: 131_072,
            max_entries: 16,
            min_free_bytes: 67_108_864,
        },
    )?;
    store.remember_named_manifest(&signed, &key, SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())?;
    Ok(())
}
