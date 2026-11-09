// Utilidades de fechas, dinero y texto (inglés para el invoice, español para los mensajes).
// Las fechas se manejan como texto 'YYYY-MM-DD' para evitar problemas de zona horaria.

export const DAY_KEYS = ['lun', 'mar', 'mie', 'jue', 'vie', 'sab', 'dom'];

const EN_DAYS_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const EN_DAYS_LONG = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const EN_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const ES_DAYS_SHORT = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
const ES_DAYS_LONG = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'];
const ES_MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];

function parts(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return { y, m, d };
}

export function isISODate(s) {
  if (typeof s !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const { y, m, d } = parts(s);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d;
}

export function addDays(iso, n) {
  const { y, m, d } = parts(iso);
  const dt = new Date(Date.UTC(y, m - 1, d + n));
  return dt.toISOString().slice(0, 10);
}

/** 0 = lunes ... 6 = domingo */
export function weekdayIndex(iso) {
  const { y, m, d } = parts(iso);
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
}

export function mondayOf(iso) {
  return addDays(iso, -weekdayIndex(iso));
}

/** Fecha de hoy en la zona horaria del negocio. */
export function todayIn(timeZone) {
  return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
}

export const year = (iso) => parts(iso).y;

// ---------- Inglés (invoice y correo) ----------
export const enShort = (iso) => `${EN_MONTHS[parts(iso).m - 1].slice(0, 3)} ${parts(iso).d}`; // "Sep 28"
export const enDayLabel = (iso) => `${EN_DAYS_SHORT[weekdayIndex(iso)]}, ${enShort(iso)}`; // "Mon, Sep 28"
export const enWeekday = (iso) => EN_DAYS_LONG[weekdayIndex(iso)]; // "Monday"
export const enDayShort = (i) => EN_DAYS_SHORT[i];
export const enLong = (iso) => `${EN_MONTHS[parts(iso).m - 1]} ${parts(iso).d}, ${parts(iso).y}`; // "October 2, 2026"

/** "September 28-October 4, 2026" (sep = '-') o "November 3–6, 2026" (sep = '–') */
export function enRange(a, b, sep = '-') {
  const A = parts(a);
  const B = parts(b);
  if (a === b) return enLong(a);
  if (A.y !== B.y) return `${enLong(a)}${sep}${enLong(b)}`;
  if (A.m !== B.m) return `${EN_MONTHS[A.m - 1]} ${A.d}${sep}${EN_MONTHS[B.m - 1]} ${B.d}, ${B.y}`;
  return `${EN_MONTHS[A.m - 1]} ${A.d}${sep}${B.d}, ${B.y}`;
}

// ---------- Español (correo y WhatsApp) ----------
export const esLong = (iso) => `${parts(iso).d} de ${ES_MONTHS[parts(iso).m - 1]} de ${parts(iso).y}`;
export const esWeekday = (iso) => ES_DAYS_LONG[weekdayIndex(iso)];
/** "Mar 3 nov" */
export const esDayLabel = (iso) => `${ES_DAYS_SHORT[weekdayIndex(iso)]} ${parts(iso).d} ${ES_MONTHS[parts(iso).m - 1].slice(0, 3)}`;

/** "del 28 de septiembre al 2 de octubre de 2026" / "del 3 al 6 de noviembre de 2026" / "del 15 de noviembre de 2026" */
export function esRange(a, b) {
  const A = parts(a);
  const B = parts(b);
  if (a === b) return `del ${esLong(a)}`;
  if (A.y !== B.y) return `del ${esLong(a)} al ${esLong(b)}`;
  if (A.m !== B.m) return `del ${A.d} de ${ES_MONTHS[A.m - 1]} al ${B.d} de ${ES_MONTHS[B.m - 1]} de ${B.y}`;
  return `del ${A.d} al ${B.d} de ${ES_MONTHS[B.m - 1]} de ${B.y}`;
}

/** "2–8 nov 2026" (para los resúmenes cortos) */
export function esRangeShort(a, b) {
  const A = parts(a);
  const B = parts(b);
  const mon = (p) => ES_MONTHS[p.m - 1].slice(0, 3);
  if (A.y !== B.y) return `${A.d} ${mon(A)} ${A.y}–${B.d} ${mon(B)} ${B.y}`;
  if (A.m !== B.m) return `${A.d} ${mon(A)}–${B.d} ${mon(B)} ${B.y}`;
  return `${A.d}–${B.d} ${mon(B)} ${B.y}`;
}

// ---------- Números ----------
/** Centavos -> "$1,234.56" */
export function money(cents) {
  const neg = cents < 0;
  const abs = Math.abs(Math.round(cents));
  const dollars = Math.floor(abs / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const c = String(abs % 100).padStart(2, '0');
  return `${neg ? '-' : ''}$${dollars}.${c}`;
}

/** Dólares (número) -> centavos enteros */
export const toCents = (dollars) => Math.round(Number(dollars || 0) * 100);

/** 10 -> "10", 7.5 -> "7.5", 7.25 -> "7.25" */
export function hrs(n) {
  return String(Math.round(n * 100) / 100);
}

export const plural = (n, one, many) => (n === 1 ? one : many);

/** "MAIN STREET PLAZA" -> "Main Street Plaza" */
export function titleCase(s) {
  return String(s)
    .toLowerCase()
    .replace(/(^|[\s\-/(])([a-záéíóúñü])/g, (_, p, ch) => p + ch.toUpperCase());
}
