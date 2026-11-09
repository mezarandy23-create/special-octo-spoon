// Carga .env (claves) y config.json (datos de la empresa y proyectos).

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export function loadEnv() {
  const file = path.join(ROOT, '.env');
  if (fs.existsSync(file)) process.loadEnvFile(file);
}

export function loadConfig() {
  const file = path.join(ROOT, 'config.json');
  if (!fs.existsSync(file)) {
    fs.copyFileSync(path.join(ROOT, 'config.example.json'), file);
    console.warn('⚠️  No existía config.json: lo creé copiando config.example.json. Ábrelo y pon los correos de destino reales ("para").');
  }
  let config;
  try {
    config = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (err) {
    throw new Error(`config.json tiene un error de formato (revisa comas y comillas): ${err.message}`);
  }
  if (!Array.isArray(config.proyectos) || !config.proyectos.length) throw new Error('config.json necesita al menos un proyecto en "proyectos".');
  return config;
}

export function settings() {
  const env = process.env;
  const yes = (v, def) => (v == null || v === '' ? def : /^(1|si|sí|true|yes|on)$/i.test(v));
  return {
    anthropicKey: env.ANTHROPIC_API_KEY || '',
    model: env.CLAUDE_MODEL || 'claude-opus-5-5',
    effort: env.CLAUDE_EFFORT || 'medium',
    fallback: env.CLAUDE_FALLBACK || 'default',
    gmailUser: env.GMAIL_USER || '',
    gmailPass: env.GMAIL_APP_PASSWORD || '',
    imapHost: env.IMAP_HOST || 'imap.gmail.com',
    imapPort: env.IMAP_PORT || '993',
    accessCode: env.CODIGO_ACCESO || '',
    allowedNumbers: (env.NUMEROS_PERMITIDOS || '').split(',').map((s) => s.trim()).filter(Boolean),
    whatsapp: yes(env.WHATSAPP, true),
    pairingNumber: env.WHATSAPP_NUMERO_BOT || '',
    baileysLogLevel: env.LOG_WHATSAPP || 'error',
    telegramToken: env.TELEGRAM_BOT_TOKEN || '',
    dataDir: path.resolve(ROOT, env.DATA_DIR || 'data'),
  };
}

export function makeLogger() {
  const stamp = () => new Date().toLocaleTimeString('es-US', { hour12: false });
  return {
    info: (...a) => console.log(`[${stamp()}]`, ...a),
    warn: (...a) => console.warn(`[${stamp()}] ⚠️`, ...a),
    error: (...a) => console.error(`[${stamp()}] ❌`, ...a),
  };
}
