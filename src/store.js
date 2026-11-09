// Guarda el estado del bot en data/estado.json (número de invoice, chats autorizados, último invoice por chat)
// y los archivos en data/ (recibos pendientes y copia de cada invoice).

import fs from 'node:fs';
import path from 'node:path';

const safe = (s) => String(s).replace(/[^a-zA-Z0-9._-]+/g, '_');

export class Store {
  constructor(dir, { firstNumber = 1 } = {}) {
    this.dir = dir;
    this.file = path.join(dir, 'estado.json');
    fs.mkdirSync(dir, { recursive: true });
    this.state = { ultimoNumero: firstNumber - 1, autorizados: {}, chats: {}, procesados: [] };
    if (fs.existsSync(this.file)) {
      this.state = { ...this.state, ...JSON.parse(fs.readFileSync(this.file, 'utf8')) };
    }
    this.save();
  }

  save() {
    const tmp = `${this.file}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(this.state, null, 2));
    fs.renameSync(tmp, this.file);
  }

  // ----- números de invoice -----
  peekNextNumber() {
    return this.state.ultimoNumero + 1;
  }
  commitNumber(n) {
    if (n > this.state.ultimoNumero) this.state.ultimoNumero = n;
    this.save();
  }
  setNextNumber(n) {
    this.state.ultimoNumero = n - 1;
    this.save();
  }
  rollbackNumber(n) {
    if (this.state.ultimoNumero === n) {
      this.state.ultimoNumero = n - 1;
      this.save();
    }
  }

  // ----- autorizaciones -----
  isAuthorized(keys) {
    return keys.some((k) => this.state.autorizados[k]);
  }
  authorize(keys, name) {
    for (const k of keys) this.state.autorizados[k] = { nombre: name || '', desde: new Date().toISOString() };
    this.save();
  }

  // ----- mensajes ya procesados (para no duplicar invoices si WhatsApp reenvía) -----
  alreadyProcessed(id) {
    if (!id) return false;
    if (this.state.procesados.includes(id)) return true;
    this.state.procesados.push(id);
    if (this.state.procesados.length > 500) this.state.procesados = this.state.procesados.slice(-500);
    this.save();
    return false;
  }

  // ----- estado por chat -----
  /** Si el mismo chat llega con otro ID (WhatsApp cambia entre número y @lid), usa el que ya tiene historial. */
  resolveKey(keys) {
    return keys.find((k) => this.state.chats[k]) || keys[0];
  }
  chat(key) {
    return (this.state.chats[key] ||= {});
  }
  updateChat(key, patch) {
    Object.assign(this.chat(key), patch);
    for (const [k, v] of Object.entries(patch)) if (v === undefined) delete this.state.chats[key][k];
    this.save();
  }

  // ----- recibos pendientes -----
  pendingDir(key) {
    return path.join(this.dir, 'recibos-pendientes', safe(key));
  }
  addPending(key, { filename, content }) {
    const dir = this.pendingDir(key);
    fs.mkdirSync(dir, { recursive: true });
    const n = fs.readdirSync(dir).length + 1;
    const name = `${String(n).padStart(2, '0')}_${safe(filename)}`;
    fs.writeFileSync(path.join(dir, name), content);
    return n;
  }
  listPending(key) {
    const dir = this.pendingDir(key);
    if (!fs.existsSync(dir)) return [];
    return fs.readdirSync(dir).sort().map((f) => path.join(dir, f));
  }

  /** Mueve los recibos pendientes a la carpeta del invoice y devuelve las rutas. */
  takePending(key, invoiceNumber) {
    const dest = path.join(this.invoiceDir(invoiceNumber), 'recibos');
    const out = [];
    for (const file of this.listPending(key)) {
      fs.mkdirSync(dest, { recursive: true });
      let target = path.join(dest, path.basename(file));
      if (fs.existsSync(target)) target = path.join(dest, `${Date.now()}_${path.basename(file)}`);
      fs.renameSync(file, target);
      out.push(target);
    }
    return out;
  }

  invoiceDir(invoiceNumber) {
    const dir = path.join(this.dir, 'facturas', safe(invoiceNumber));
    fs.mkdirSync(dir, { recursive: true });
    return dir;
  }
}
