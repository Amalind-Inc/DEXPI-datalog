/**
 * THROWAWAY SPIKE — reports Pi auth status without reading credential values.
 *
 * Uses AuthStorage.list() and getAuthStatus(), never get(), getAll(),
 * getApiKey(), login(), or logout(). Run: npm run prototype:pi-auth
 */
import os from "node:os";
import path from "node:path";
import { AuthStorage } from "@earendil-works/pi-coding-agent";

const authPath = path.join(os.homedir(), ".pi", "agent", "auth.json");
const auth = AuthStorage.create(authPath);
const providers = auth.list().sort();

console.log(JSON.stringify({
  authPath: "~/.pi/agent/auth.json",
  providers: providers.map((provider) => ({ provider, status: auth.getAuthStatus(provider) })),
  credentialValuesRead: false,
  loginAttempted: false,
}, null, 2));
