// Prueba SOLO la conexión con Gmail: entra con la contraseña de aplicación y deja un borrador de prueba.
//   npm run probar-correo

import { loadEnv, settings } from '../src/config.js';
import { DraftMailbox, composeRaw, newMessageId, explainMailError } from '../src/email.js';

loadEnv();
const s = settings();
const mailbox = new DraftMailbox({ host: s.imapHost, port: s.imapPort, user: s.gmailUser, pass: s.gmailPass });

if (!mailbox.enabled) {
  console.error('❌ Falta GMAIL_USER o GMAIL_APP_PASSWORD en el archivo .env');
  process.exit(1);
}

try {
  console.log(`Conectando a ${s.imapHost} como ${s.gmailUser}...`);
  const { draftsPath } = await mailbox.test();
  console.log(`✅ Entré bien. Carpeta de borradores: "${draftsPath}"`);
  const raw = await composeRaw({
    from: s.gmailUser,
    to: [s.gmailUser],
    subject: 'Prueba del bot de invoices (puedes borrar este borrador)',
    text: 'Si ves este borrador en Gmail, la conexión funciona. ✅',
    html: '<p>Si ves este borrador en Gmail, la conexión funciona. ✅</p>',
    messageId: newMessageId(s.gmailUser),
    attachments: [],
  });
  await mailbox.createDraft(raw);
  console.log('✅ Dejé un borrador de prueba. Abre Gmail -> Borradores para verlo y luego bórralo.');
} catch (err) {
  console.error(`❌ ${explainMailError(err)}`);
  process.exit(1);
}
