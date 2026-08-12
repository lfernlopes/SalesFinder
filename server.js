// Static server for the Grand Street / Unified Fencing Group acquisition map.
import express from 'express';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = process.env.PORT || 4800;

app.use(express.static(join(__dirname, 'public')));
app.listen(PORT, () => console.log(`Acquisition map running at http://localhost:${PORT}`));
