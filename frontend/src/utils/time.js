// Every time the web pages show or compare goes through here, so it is Thai time (Asia/Bangkok) whatever the
// browser's own zone is. The backend sends ISO 8601 with an offset (e.g. 2026-10-22T16:05:09+07:00), so
// new Date(value) is the right instant; only the display zone and the day boundary have to be fixed.

export const THAI_TZ = 'Asia/Bangkok'

const partsFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: THAI_TZ,
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit',
  hourCycle: 'h23'
})

// { year, month, day, hour, minute, second } as zero-padded strings, or null for an unparsable value
export function thaiParts(value) {
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return null
  const out = {}
  for (const p of partsFormat.formatToParts(d)) out[p.type] = p.value
  return out
}

// 'YYYY-MM-DD' of the Thai calendar day
export function thaiDayKey(value) {
  const p = thaiParts(value)
  return p ? `${p.year}-${p.month}-${p.day}` : null
}

export function isThaiToday(value) {
  const key = thaiDayKey(value)
  return key !== null && key === thaiDayKey(new Date())
}

// dd/MM/yyyy HH:mm:ss
export function formatThaiDateTime(value) {
  const p = thaiParts(value)
  return p ? `${p.day}/${p.month}/${p.year} ${p.hour}:${p.minute}:${p.second}` : String(value ?? '')
}

// HH:mm:ss
export function formatThaiClock(value) {
  const p = thaiParts(value)
  return p ? `${p.hour}:${p.minute}:${p.second}` : String(value ?? '')
}

// HH:mm for today, dd/MM HH:mm for another day
export function formatThaiShort(value) {
  const p = thaiParts(value)
  if (!p) return String(value ?? '')
  const time = `${p.hour}:${p.minute}`
  return isThaiToday(value) ? time : `${p.day}/${p.month} ${time}`
}

// "22 ตุลาคม 2569 16:05" (Thai calendar), for settings pages
export function formatThaiLong(value) {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value ?? '')
  return d.toLocaleString('th-TH', {
    timeZone: THAI_TZ, year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit'
  })
}
