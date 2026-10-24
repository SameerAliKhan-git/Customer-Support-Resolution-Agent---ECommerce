/* Auth tokens remain in memory. Only short-lived PKCE state uses session storage. */
const nativeFetch = window.fetch.bind(window);
let portalConfig = {}, portalUser = null, accessToken = null, demoReviewer = false;
function portalToken() {
  if (portalConfig.demo) return demoReviewer ? 'rev_supervisor' : document.getElementById('customer-id').value;
  return accessToken;
}
function isReviewer() { return portalConfig.demo ? demoReviewer : ['reviewer','admin'].includes(portalUser?.role); }
window.fetch = async (input, options = {}) => {
  const url = typeof input === 'string' ? input : input.url;
  const target = new URL(url, location.origin);
  if (target.origin === location.origin && target.pathname.startsWith('/api/')) {
    const headers = new Headers(options.headers || {});
    headers.delete('Authorization');
    const token = portalToken();
    if (token) headers.set('Authorization', `Bearer ${token}`);
    return nativeFetch(input, {...options, headers});
  }
  return nativeFetch(input, options);
};
function announce(text) { document.getElementById('portal-status').textContent = text; }
const base64url = bytes => btoa(String.fromCharCode(...bytes)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
async function discovery() {
  const issuer = portalConfig.issuer.replace(/\/$/,'');
  const res = await nativeFetch(issuer+'/.well-known/openid-configuration');
  if (!res.ok) throw new Error('Identity provider is unavailable.');
  const data = await res.json();
  if (data.issuer !== issuer || ['authorization_endpoint','token_endpoint'].some(k => new URL(data[k]).origin !== new URL(issuer).origin)) throw new Error('Invalid identity provider configuration.');
  return data;
}
async function signIn() {
  try {
    if (portalConfig.demo) {
      demoReviewer = !demoReviewer;
      await updateSession();
      if (currentRunState) updateUIWithState(currentRunState);
      await refreshPendingApprovals();
      return;
    }
    if (portalConfig.auth_mode !== 'oidc') {
      accessToken = document.getElementById('session-token').value.trim();
      document.getElementById('session-token').value = '';
      await updateSession();
      return;
    }
    const data = await discovery();
    const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)));
    const state = base64url(crypto.getRandomValues(new Uint8Array(24)));
    sessionStorage.setItem('supportPKCE', JSON.stringify({verifier,state,created:Date.now()}));
    const challenge = base64url(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifier))));
    const redirect = location.origin + '/';
    const url = new URL(data.authorization_endpoint);
    url.search = new URLSearchParams({client_id:portalConfig.client_id,redirect_uri:redirect,response_type:'code',scope:'openid profile',state,code_challenge:challenge,code_challenge_method:'S256'});
    location.assign(url);
  } catch (err) { announce(err.message); }
}
async function updateSession() {
  const response = await fetch('/api/session/me');
  if (!response.ok) { portalUser = null; throw new Error('Sign in with an authorized account.'); }
  portalUser = await response.json();
  document.getElementById('identity-label').textContent = `${portalUser.name} · ${portalUser.role}`;
  document.getElementById('reviewer-card').hidden = !isReviewer();
  if (!portalConfig.demo && portalUser.role === 'customer') {
    document.getElementById('customer-id').value = portalUser.id;
    document.getElementById('customer-id').readOnly = true;
  }
  announce('Signed in.');
  await loadHistory();
}
async function initializePortal() {
  portalConfig = await (await nativeFetch('/api/session/config')).json();
  document.querySelector('.scenarios-container').hidden = !portalConfig.demo;
  document.getElementById('reviewer-card').hidden = true;
  document.getElementById('session-token').hidden = portalConfig.auth_mode === 'oidc' || portalConfig.demo;
  document.getElementById('sign-in').textContent = portalConfig.demo ? 'Switch customer / demo reviewer' : 'Sign in';
  document.getElementById('sign-in').addEventListener('click', signIn);
  document.getElementById('sign-out').addEventListener('click', () => { accessToken = null; portalUser = null; localStorage.removeItem('supportRun'); location.assign('/'); });
  const params = new URLSearchParams(location.search);
  if (params.has('code')) {
    try {
      const pending = JSON.parse(sessionStorage.getItem('supportPKCE') || 'null');
      sessionStorage.removeItem('supportPKCE');
      history.replaceState({},'', '/');
      if (!pending || pending.state !== params.get('state') || Date.now()-pending.created > 600000) throw new Error('Login state expired or invalid. Start sign in again.');
      const data = await discovery();
      const response = await nativeFetch(data.token_endpoint, {method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'authorization_code',client_id:portalConfig.client_id,redirect_uri:location.origin+'/',code:params.get('code'),code_verifier:pending.verifier})});
      if (!response.ok) throw new Error('Sign in could not be completed.');
      const tokens = await response.json(); accessToken = tokens.access_token;
      setTimeout(() => {accessToken = null; announce('Session expired. Sign in again.');}, Math.max(0,(tokens.expires_in || 300)*1000));
    } catch (error) { announce(error.message); }
  }
  if (portalConfig.demo || accessToken) await updateSession();
  else announce('Sign in to submit or review a support case.');
  document.getElementById('clarification-form').addEventListener('submit', async event => {
    event.preventDefault();
    const response = await fetch(`/api/workflows/${currentRunState.run_id}/messages`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:document.getElementById('clarification-message').value,order_id:document.getElementById('clarification-order').value || null})});
    const state = await response.json();
    if (!response.ok) return announce(state.detail || 'Could not save information.');
    currentRunState = state; updateUIWithState(state); await loadHistory();
  });
  for (const name of ['blur','input']) document.addEventListener(name,event => {
    const field = event.target;
    if (field.matches?.('input,textarea,select')) {
      const invalid = CSS.supports('selector(:user-invalid)') ? field.matches(':user-invalid') : !field.validity.valid;
      field.setAttribute('aria-invalid',String(invalid));
    }
  },true);
}
async function loadHistory() {
  const response = await fetch('/api/workflows');
  if (!response.ok) return;
  const items = await response.json(), container = document.getElementById('case-history');
  container.replaceChildren();
  for (const item of items) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'btn';
    button.textContent = `${item.ticket_id} · ${item.execution_status}`;
    button.addEventListener('click',async () => {
      const response = await fetch(`/api/workflows/${item.run_id}`); if (!response.ok) return;
      currentRunState = await response.json(); currentTicketId = currentRunState.ticket_id;
      localStorage.setItem('supportRun', currentRunState.run_id); updateUIWithState(currentRunState); await loadTicketAuditTrail(currentTicketId);
    }); container.appendChild(button);
  }
}
setInterval(async () => {
  if (!currentRunState || !portalToken() || currentRunState.is_completed) return;
  const response = await fetch(`/api/workflows/${currentRunState.run_id}`);
  if (response.ok) { currentRunState = await response.json(); updateUIWithState(currentRunState); }
},3000);
