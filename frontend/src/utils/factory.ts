const LEGACY_FACTORY_IDS = new Set(['factory-sh-01', 'F01'])

export function getActiveFactoryId(fallback = 'FAC_MECH_001'): string {
  const stored = localStorage.getItem('active_factory_id') || ''
  if (LEGACY_FACTORY_IDS.has(stored)) {
    localStorage.setItem('active_factory_id', fallback)
    return fallback
  }
  return stored || fallback
}
