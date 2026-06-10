/** Sync-pair guard: AD_LOCATIONS must match admin + server + Python migrator. */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { AD_LOCATIONS } from '../js/sponsored-deals.js';

function extractPyFrozensetKeys(source, name) {
  const block = source.match(new RegExp(`${name}[^\\{]*\\{([^}]+)\\}`, 's'));
  if (!block) return [];
  return [...block[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}

function extractAdminAdLocations(source) {
  const block = source.match(/const AD_LOCATIONS = \[([\s\S]*?)\];/);
  if (!block) return [];
  return [...block[1].matchAll(/'([^']+)'/g)].map((m) => m[1]);
}

function extractMigratorLocationKeys(source) {
  const block = source.match(/locations: dict\[str, list\[str\]\] = \{k: \[\] for k in \[([\s\S]*?)\]/);
  if (!block) return [];
  return [...block[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}

function sorted(keys) {
  return [...keys].sort();
}

describe('AD_LOCATIONS sync pairs', () => {
  const serverKeys = extractPyFrozensetKeys(
    readFileSync('shared/sponsors_validate.py', 'utf8'),
    'SPONSOR_AD_LOCATIONS',
  );
  const migratorKeys = extractMigratorLocationKeys(readFileSync('scripts/migrate_sponsors_v2.py', 'utf8'));

  it('has 22 location keys in js/sponsored-deals.js', () => {
    expect(AD_LOCATIONS).toHaveLength(22);
  });

  it('matches shared/sponsors_validate.py SPONSOR_AD_LOCATIONS', () => {
    expect(sorted(serverKeys)).toEqual(sorted(AD_LOCATIONS));
  });

  it.skipIf(!existsSync('admin/admin.js'))('matches admin/admin.js AD_LOCATIONS', () => {
    const adminKeys = extractAdminAdLocations(readFileSync('admin/admin.js', 'utf8'));
    expect(sorted(adminKeys)).toEqual(sorted(AD_LOCATIONS));
  });

  it('matches scripts/migrate_sponsors_v2.py location keys', () => {
    expect(sorted(migratorKeys)).toEqual(sorted(AD_LOCATIONS));
  });
});
