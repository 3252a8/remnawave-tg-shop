import fs from 'node:fs';
import http from 'node:http';
import https from 'node:https';

import { handler } from './build/handler.js';

const host = process.env.WEB_HOST || process.env.HOST || '0.0.0.0';
const port = Number(process.env.WEB_PORT || process.env.PORT || 3000);
const certPath = process.env.WEB_SSL_CERT_PATH || process.env.SSL_CERT_PATH || '';
const keyPath = process.env.WEB_SSL_KEY_PATH || process.env.SSL_KEY_PATH || '';
const caPath = process.env.WEB_SSL_CA_PATH || process.env.SSL_CA_PATH || '';

const hasTls = Boolean(certPath && keyPath && fs.existsSync(certPath) && fs.existsSync(keyPath));

if (hasTls) {
  const options = {
    cert: fs.readFileSync(certPath),
    key: fs.readFileSync(keyPath),
    ca: caPath && fs.existsSync(caPath) ? fs.readFileSync(caPath) : undefined,
  };

  https.createServer(options, handler).listen(port, host, () => {
    console.log(`Web portal listening on https://${host}:${port}`);
  });
} else {
  http.createServer(handler).listen(port, host, () => {
    console.log(`Web portal listening on http://${host}:${port}`);
  });
}
