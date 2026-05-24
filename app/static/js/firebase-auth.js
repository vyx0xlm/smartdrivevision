import { initializeApp } from 'https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js';
import {
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
} from 'https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js';

const cfg = window.FIREBASE_CONFIG;
const msgEl = document.getElementById('auth-message');
const googleBtn = document.getElementById('btn-google');

function showMsg(text, isError) {
  if (!msgEl) return;
  msgEl.textContent = text;
  msgEl.style.display = 'block';
  msgEl.className = isError ? 'flash error' : 'flash success';
  if (!isError) {
    msgEl.style.background = 'rgba(0, 186, 124, 0.15)';
    msgEl.style.color = '#00ba7c';
    msgEl.style.border = '1px solid rgba(0, 186, 124, 0.35)';
  }
}

async function finishGoogleLogin(user) {
  const idToken = await user.getIdToken();
  const res = await fetch('/auth/firebase', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ idToken }),
    credentials: 'same-origin',
  });
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    showMsg('Server error. Check terminal and serviceAccountKey.json.', true);
    return;
  }
  if (data.ok) {
    window.location.href = data.redirect || '/dashboard';
  } else {
    showMsg(data.error || 'Sign-in failed', true);
  }
}

if (cfg?.apiKey && googleBtn) {
  const auth = getAuth(initializeApp(cfg));
  googleBtn.addEventListener('click', async () => {
    try {
      googleBtn.disabled = true;
      googleBtn.textContent = 'Signing in…';
      const provider = new GoogleAuthProvider();
      provider.setCustomParameters({ prompt: 'select_account' });
      const result = await signInWithPopup(auth, provider);
      await finishGoogleLogin(result.user);
    } catch (e) {
      showMsg(e.message || 'Google sign-in failed', true);
      googleBtn.disabled = false;
      googleBtn.textContent = 'Continue with Google';
    }
  });
}
