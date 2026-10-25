import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";

const root = join(process.cwd(), "app", "static");
const types = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript" };

createServer((request, response) => {
  const urlPath = request.url === "/" ? "/index.html" : request.url.replace(/^\/assets/, "");
  const file = normalize(join(root, urlPath.split("?")[0]));
  if (!file.startsWith(root) || !existsSync(file) || statSync(file).isDirectory()) {
    response.writeHead(404).end("Not found");
    return;
  }
  response.writeHead(200, { "Content-Type": types[extname(file)] || "application/octet-stream" });
  createReadStream(file).pipe(response);
}).listen(4173, "127.0.0.1", () => console.log("Preview: http://127.0.0.1:4173"));

