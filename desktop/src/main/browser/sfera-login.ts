import type { WebContents } from 'electron'
import type { LoginCredential } from './credentials'

export const GICAR_ORIGIN = 'https://autenticaciogicar5.extranet.gencat.cat'
const REALM = '/realms/gicar-ad/'
export function isGicarLogin(url: string): boolean {
  try { const value = new URL(url); return value.origin === GICAR_ORIGIN && value.pathname.startsWith(REALM) } catch { return false }
}

/** Private, fixed adapter; no renderer-provided script or selectors. */
export async function submitSferaLogin(contents: WebContents, credential: LoginCredential): Promise<boolean> {
  if (!isGicarLogin(contents.getURL())) return false
  const code = `(() => {
    if (location.origin !== ${JSON.stringify(GICAR_ORIGIN)} || !location.pathname.startsWith(${JSON.stringify(REALM)})) return false;
    const form = document.getElementById('kc-form-login');
    const username = form?.querySelector('input[name="username"]');
    const password = form?.querySelector('input[name="password"][type="password"]');
    const button = form?.querySelector('[name="login"]');
    if (!(form instanceof HTMLFormElement) || !(username instanceof HTMLInputElement) || !(password instanceof HTMLInputElement)) return false;
    const action = new URL(form.action, location.href);
    if (action.origin !== ${JSON.stringify(GICAR_ORIGIN)} || !action.pathname.startsWith('/realms/gicar-ad/login-actions/authenticate')) return false;
    const credential = ${JSON.stringify({ username: credential.username, password: credential.password })};
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    set.call(username, credential.username); set.call(password, credential.password);
    username.dispatchEvent(new Event('input', { bubbles: true })); password.dispatchEvent(new Event('input', { bubbles: true }));
    HTMLFormElement.prototype.requestSubmit.call(form, button instanceof HTMLButtonElement || button instanceof HTMLInputElement ? button : undefined);
    return true;
  })()`
  return contents.executeJavaScriptInIsolatedWorld(999, [{ code }]) as Promise<boolean>
}
